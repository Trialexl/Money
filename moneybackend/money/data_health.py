from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from investments.services import get_market_data_health
from ops.models import ScheduledJobState

from .models import (
    AiPendingConfirmation,
    AutoPayment,
    Budget,
    BudgetExpense,
    BudgetIncome,
    Expenditure,
    FlowOfFunds,
    OneCSyncOutbox,
    Receipt,
    Transfer,
)


DETAIL_LIMIT = 50
STATUS_ORDER = {
    'ok': 0,
    'warning': 1,
    'error': 2,
}


@dataclass(frozen=True)
class DocumentConfig:
    label: str
    model: type
    document_type: int


DOCUMENT_CONFIGS = [
    DocumentConfig('Автоплатеж', AutoPayment, 1),
    DocumentConfig('Перевод', Transfer, 2),
    DocumentConfig('Приход', Receipt, 3),
    DocumentConfig('Расход', Expenditure, 4),
    DocumentConfig('Бюджет', Budget, 5),
]


DOCUMENT_TYPE_MAP = {config.document_type: config for config in DOCUMENT_CONFIGS}


def generate_data_health_report(*, detail_limit=DETAIL_LIMIT):
    checks = [
        _check_register_consistency(detail_limit=detail_limit),
        _check_orphan_registers(detail_limit=detail_limit),
        _check_onec_outbox(detail_limit=detail_limit),
        _check_ai_pending_confirmations(detail_limit=detail_limit),
        _check_scheduled_jobs(detail_limit=detail_limit),
        _check_market_data(detail_limit=detail_limit),
    ]
    status = _overall_status(checks)
    counts = Counter(check['status'] for check in checks)
    return {
        'status': status,
        'generated_at': timezone.now().isoformat(),
        'summary': {
            'checks_total': len(checks),
            'ok': counts['ok'],
            'warning': counts['warning'],
            'error': counts['error'],
        },
        'checks': checks,
    }


def _overall_status(checks):
    status = 'ok'
    for check in checks:
        if STATUS_ORDER[check['status']] > STATUS_ORDER[status]:
            status = check['status']
    return status


def _check_payload(key, title, status, summary, *, count=0, items=None, meta=None):
    return {
        'key': key,
        'title': title,
        'status': status,
        'summary': summary,
        'count': count,
        'items': items or [],
        'meta': meta or {},
    }


def _admin_url(document):
    meta = document._meta
    return f'/admin/{meta.app_label}/{meta.model_name}/{document.id}/change/'


def _money(value):
    if value is None:
        value = Decimal('0')
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return f'{value:.2f}'


def _dt(value):
    return value.isoformat() if value is not None else None


def _id(value):
    return str(value) if value is not None else None


def _flow_signature(row):
    return (
        _dt(row.period),
        _id(row.wallet_id),
        _id(row.cash_flow_item_id),
        _money(row.amount),
    )


def _budget_signature(row):
    return (
        _dt(row.period),
        _id(row.project_id),
        _id(row.cash_flow_item_id),
        _money(row.amount),
    )


def _sum_amount(rows):
    return sum((row.amount for row in rows), Decimal('0'))


def _register_delta(expected_rows, actual_rows, signature):
    expected = Counter(signature(row) for row in expected_rows)
    actual = Counter(signature(row) for row in actual_rows)
    return expected, actual, expected == actual


def _document_snapshot(document, config):
    return {
        'document_type': config.label,
        'document_type_id': config.document_type,
        'document_id': str(document.id),
        'number': getattr(document, 'number', ''),
        'date': _dt(getattr(document, 'date', None)),
        'posted': bool(getattr(document, 'posted', True)),
        'deleted': bool(getattr(document, 'deleted', False)),
        'admin_url': _admin_url(document),
    }


def _mismatch_item(document, config, register_name, expected_rows, actual_rows):
    item = _document_snapshot(document, config)
    item.update({
        'register': register_name,
        'expected_count': len(expected_rows),
        'actual_count': len(actual_rows),
        'expected_total': _money(_sum_amount(expected_rows)),
        'actual_total': _money(_sum_amount(actual_rows)),
    })
    return item


def _check_register_consistency(*, detail_limit):
    mismatches = []
    checked_documents = 0

    for config in DOCUMENT_CONFIGS:
        queryset = config.model.objects.all().order_by('-date', '-id')
        for document in queryset.iterator():
            checked_documents += 1
            if document.registers_enabled():
                expected_flow = document.create_flow_records()
                expected_budget = document.create_budget_records()
            else:
                expected_flow = []
                expected_budget = []

            actual_flow = list(
                FlowOfFunds.objects.filter(
                    document_id=document.id,
                    type_of_document=config.document_type,
                )
            )
            _, _, flow_ok = _register_delta(expected_flow, actual_flow, _flow_signature)
            if not flow_ok and len(mismatches) < detail_limit:
                mismatches.append(_mismatch_item(document, config, 'flow_of_funds', expected_flow, actual_flow))
            elif not flow_ok:
                mismatches.append(None)

            expected_income = [row for row in expected_budget if isinstance(row, BudgetIncome)]
            actual_income = list(
                BudgetIncome.objects.filter(
                    document_id=document.id,
                    type_of_document=config.document_type,
                )
            )
            _, _, income_ok = _register_delta(expected_income, actual_income, _budget_signature)
            if not income_ok and len([item for item in mismatches if item is not None]) < detail_limit:
                mismatches.append(_mismatch_item(document, config, 'budget_income', expected_income, actual_income))
            elif not income_ok:
                mismatches.append(None)

            expected_expense = [row for row in expected_budget if isinstance(row, BudgetExpense)]
            actual_expense = list(
                BudgetExpense.objects.filter(
                    document_id=document.id,
                    type_of_document=config.document_type,
                )
            )
            _, _, expense_ok = _register_delta(expected_expense, actual_expense, _budget_signature)
            if not expense_ok and len([item for item in mismatches if item is not None]) < detail_limit:
                mismatches.append(_mismatch_item(document, config, 'budget_expense', expected_expense, actual_expense))
            elif not expense_ok:
                mismatches.append(None)

    mismatch_count = len(mismatches)
    items = [item for item in mismatches if item is not None]
    status = 'error' if mismatch_count else 'ok'
    summary = (
        f'Найдено расхождений регистров: {mismatch_count}.'
        if mismatch_count
        else f'Проверено документов: {checked_documents}, расхождений регистров нет.'
    )
    return _check_payload(
        'register_consistency',
        'Документы и регистры',
        status,
        summary,
        count=mismatch_count,
        items=items,
        meta={'checked_documents': checked_documents, 'detail_limit': detail_limit},
    )


def _register_snapshot(row, register_name):
    return {
        'register': register_name,
        'register_id': str(row.id),
        'document_id': _id(row.document_id),
        'document_type_id': row.type_of_document,
        'period': _dt(row.period),
        'amount': _money(row.amount),
    }


def _missing_document_ids(register_model, document_type, document_model):
    document_ids = list(
        register_model.objects
        .filter(type_of_document=document_type)
        .exclude(document_id__isnull=True)
        .values_list('document_id', flat=True)
        .distinct()
    )
    existing_ids = set(document_model.objects.filter(id__in=document_ids).values_list('id', flat=True))
    return [document_id for document_id in document_ids if document_id not in existing_ids]


def _collect_orphans_for_register(register_model, register_name, *, detail_limit):
    orphan_filters = []
    items = []
    count = 0

    null_document_count = register_model.objects.filter(document_id__isnull=True).count()
    count += null_document_count
    if null_document_count and len(items) < detail_limit:
        for row in register_model.objects.filter(document_id__isnull=True).order_by('-period')[:detail_limit - len(items)]:
            items.append(_register_snapshot(row, register_name))

    supported_types = set(DOCUMENT_TYPE_MAP)
    invalid_type_queryset = register_model.objects.exclude(type_of_document__in=supported_types)
    invalid_type_count = invalid_type_queryset.count()
    count += invalid_type_count
    if invalid_type_count and len(items) < detail_limit:
        for row in invalid_type_queryset.order_by('-period')[:detail_limit - len(items)]:
            items.append(_register_snapshot(row, register_name))

    for document_type, config in DOCUMENT_TYPE_MAP.items():
        missing_ids = _missing_document_ids(register_model, document_type, config.model)
        if not missing_ids:
            continue
        orphan_filters.extend((document_type, missing_ids))
        count += register_model.objects.filter(type_of_document=document_type, document_id__in=missing_ids).count()

    for document_type, missing_ids in orphan_filters:
        if len(items) >= detail_limit:
            break
        rows = register_model.objects.filter(
            type_of_document=document_type,
            document_id__in=missing_ids,
        ).order_by('-period')[:detail_limit - len(items)]
        for row in rows:
            snapshot = _register_snapshot(row, register_name)
            snapshot['document_type'] = DOCUMENT_TYPE_MAP[document_type].label
            items.append(snapshot)

    return count, items


def _check_orphan_registers(*, detail_limit):
    total_count = 0
    items = []
    for register_model, register_name in (
        (FlowOfFunds, 'flow_of_funds'),
        (BudgetIncome, 'budget_income'),
        (BudgetExpense, 'budget_expense'),
    ):
        count, register_items = _collect_orphans_for_register(
            register_model,
            register_name,
            detail_limit=max(detail_limit - len(items), 0),
        )
        total_count += count
        items.extend(register_items[:max(detail_limit - len(items), 0)])

    status = 'error' if total_count else 'ok'
    summary = (
        f'Найдено регистров без существующего документа: {total_count}.'
        if total_count
        else 'Регистров без существующего документа нет.'
    )
    return _check_payload(
        'orphan_registers',
        'Регистры без документов',
        status,
        summary,
        count=total_count,
        items=items,
        meta={'detail_limit': detail_limit},
    )


def _check_onec_outbox(*, detail_limit):
    now = timezone.now()
    stale_cutoff = now - timedelta(hours=24)
    queryset = OneCSyncOutbox.objects.all().order_by('changed_at')
    total_count = queryset.count()
    stale_count = queryset.filter(changed_at__lt=stale_cutoff).count()
    items = [
        {
            'entity_type': row.entity_type,
            'object_id': str(row.object_id),
            'operation': row.operation,
            'route': row.route,
            'changed_at': _dt(row.changed_at),
        }
        for row in queryset[:detail_limit]
    ]
    status = 'warning' if stale_count else 'ok'
    summary = (
        f'В очереди 1С {total_count}, старше 24 часов: {stale_count}.'
        if total_count
        else 'Очередь 1С пуста.'
    )
    return _check_payload(
        'onec_outbox',
        'Очередь синхронизации 1С',
        status,
        summary,
        count=stale_count,
        items=items,
        meta={'total': total_count, 'stale_hours': 24},
    )


def _check_ai_pending_confirmations(*, detail_limit):
    now = timezone.now()
    stale_cutoff = now - timedelta(hours=1)
    queryset = AiPendingConfirmation.objects.filter(is_active=True).order_by('updated_at')
    total_count = queryset.count()
    stale_count = queryset.filter(updated_at__lt=stale_cutoff).count()
    items = [
        {
            'id': str(row.id),
            'source': row.source,
            'intent': row.intent,
            'provider': row.provider,
            'missing_fields': row.missing_fields,
            'updated_at': _dt(row.updated_at),
        }
        for row in queryset[:detail_limit]
    ]
    status = 'warning' if stale_count else 'ok'
    summary = (
        f'Активных AI-уточнений: {total_count}, старше 1 часа: {stale_count}.'
        if total_count
        else 'Активных AI-уточнений нет.'
    )
    return _check_payload(
        'ai_pending_confirmations',
        'AI уточнения',
        status,
        summary,
        count=stale_count,
        items=items,
        meta={'total': total_count, 'stale_hours': 1},
    )


def _check_scheduled_jobs(*, detail_limit):
    queryset = ScheduledJobState.objects.filter(enabled=True)
    problem_jobs = queryset.exclude(
        last_status__in=[
            ScheduledJobState.STATUS_SUCCESS,
            ScheduledJobState.STATUS_NEVER,
            ScheduledJobState.STATUS_SKIPPED,
        ]
    ).order_by('job_key')
    problem_count = problem_jobs.count()
    items = [
        {
            'job_key': row.job_key,
            'title': row.title,
            'last_status': row.last_status,
            'last_started_at': _dt(row.last_started_at),
            'last_finished_at': _dt(row.last_finished_at),
            'last_error': row.last_error,
        }
        for row in problem_jobs[:detail_limit]
    ]
    status = 'warning' if problem_count else 'ok'
    summary = (
        f'Регламентных заданий с проблемным статусом: {problem_count}.'
        if problem_count
        else 'Регламентные задания без проблемного статуса.'
    )
    return _check_payload(
        'scheduled_jobs',
        'Регламентные задания',
        status,
        summary,
        count=problem_count,
        items=items,
        meta={'enabled_total': queryset.count()},
    )


def _check_market_data(*, detail_limit):
    max_age_days = getattr(settings, 'SCHEDULED_JOBS_MARKET_MAX_AGE_DAYS', 2)
    market = get_market_data_health(max_age_days=max_age_days)
    problem_items = []
    for item in market['prices']['items']:
        if item['status'] != 'ok':
            problem_items.append({
                'kind': 'price',
                **item,
                'latest_at': _dt(item.get('latest_at')),
                'price_usd': _money(item.get('price_usd')) if item.get('price_usd') is not None else None,
            })
    for item in market['fx_rates']['items']:
        if item['status'] != 'ok':
            problem_items.append({
                'kind': 'fx_rate',
                **item,
                'latest_at': _dt(item.get('latest_at')),
                'rate': str(item.get('rate')) if item.get('rate') is not None else None,
            })

    status = market['status']
    summary = (
        'Рыночные данные актуальны.'
        if status == 'ok'
        else (
            f"Проблемы рыночных данных: prices missing={market['prices']['missing']}, "
            f"prices stale={market['prices']['stale']}, fx missing={market['fx_rates']['missing']}, "
            f"fx stale={market['fx_rates']['stale']}."
        )
    )
    return _check_payload(
        'market_data',
        'Курсы и цены инструментов',
        status,
        summary,
        count=len(problem_items),
        items=problem_items[:detail_limit],
        meta={
            'as_of': market['as_of'],
            'max_age_days': market['max_age_days'],
            'latest_successful_price_at': _dt(market['latest_successful_price_at']),
            'latest_successful_fx_at': _dt(market['latest_successful_fx_at']),
        },
    )
