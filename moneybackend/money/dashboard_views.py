from calendar import monthrange
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    BudgetExpense,
    BudgetIncome,
    CashFlowItem,
    Expenditure,
    FlowOfFunds,
    MONEY_QUANTIZER,
    Receipt,
    Transfer,
    Wallet,
    ZERO_AMOUNT,
)
from .serializers import (
    DashboardBudgetExpenseBreakdownQuerySerializer,
    DashboardBudgetExpenseBreakdownResponseSerializer,
    DashboardOverviewQuerySerializer,
    DashboardOverviewResponseSerializer,
    DashboardRecentActivityQuerySerializer,
    DashboardRecentActivityResponseSerializer,
)


PERCENT_QUANTIZER = Decimal('0.01')
TRANSFER_DOCUMENT_TYPE = 2


def _money(value):
    if value is None:
        value = ZERO_AMOUNT
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(MONEY_QUANTIZER)


def _money_str(value):
    return f'{_money(value):.2f}'


def _percent_str(value):
    return f'{_money(value).quantize(PERCENT_QUANTIZER):.2f}'


def _month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_end(dt):
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


def _shift_month(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _month_end(dt):
    return _shift_month(_month_start(dt), 1) - timedelta(microseconds=1)


def _parse_selected_at(raw_value, fallback):
    if not raw_value:
        return fallback

    parsed = parse_datetime(str(raw_value))
    if parsed is None:
        return fallback
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _flow_period_totals(date_from, date_to):
    totals = FlowOfFunds.objects.filter(
        period__gte=date_from,
        period__lte=date_to,
        cash_flow_item__isnull=False,
    ).exclude(type_of_document=TRANSFER_DOCUMENT_TYPE).aggregate(
        income_total=Sum('amount', filter=Q(amount__gt=0)),
        expense_total=Sum('amount', filter=Q(amount__lt=0)),
    )

    income_total = _money(totals['income_total'])
    expense_total = _money(-(totals['expense_total'] or ZERO_AMOUNT))
    return income_total, expense_total


def _serialize_uuid(value):
    return str(value) if value is not None else None


class DashboardViewSet(viewsets.ViewSet):
    """Сводный dashboard по мотивам общей формы 1С."""

    permission_classes = [permissions.IsAdminUser]

    def _build_recent_activity_items(self, *, selected_day_end, hide_hidden_wallets, limit):
        receipt_queryset = Receipt.objects.filter(
            deleted=False,
            date__lte=selected_day_end,
        ).select_related('wallet', 'cash_flow_item').order_by('-date')
        expenditure_queryset = Expenditure.objects.filter(
            deleted=False,
            date__lte=selected_day_end,
        ).select_related('wallet', 'cash_flow_item').order_by('-date')
        transfer_queryset = Transfer.objects.filter(
            deleted=False,
            date__lte=selected_day_end,
        ).select_related('wallet_out', 'wallet_in').order_by('-date')

        if hide_hidden_wallets:
            receipt_queryset = receipt_queryset.filter(wallet__hidden=False)
            expenditure_queryset = expenditure_queryset.filter(wallet__hidden=False)
            transfer_queryset = transfer_queryset.filter(
                wallet_out__hidden=False,
                wallet_in__hidden=False,
            )

        items = []

        for receipt in receipt_queryset[:limit]:
            items.append({
                'id': _serialize_uuid(receipt.id),
                'kind': 'receipt',
                'date': receipt.date.isoformat(),
                'amount': _money_str(receipt.amount),
                'description': receipt.comment or None,
                'wallet': _serialize_uuid(receipt.wallet_id),
                'wallet_name': getattr(receipt.wallet, 'name', None),
                'cash_flow_item': _serialize_uuid(receipt.cash_flow_item_id),
                'cash_flow_item_name': getattr(receipt.cash_flow_item, 'name', None),
                '_sort_date': receipt.date,
            })

        for expenditure in expenditure_queryset[:limit]:
            items.append({
                'id': _serialize_uuid(expenditure.id),
                'kind': 'expenditure',
                'date': expenditure.date.isoformat(),
                'amount': _money_str(expenditure.amount),
                'description': expenditure.comment or None,
                'wallet': _serialize_uuid(expenditure.wallet_id),
                'wallet_name': getattr(expenditure.wallet, 'name', None),
                'cash_flow_item': _serialize_uuid(expenditure.cash_flow_item_id),
                'cash_flow_item_name': getattr(expenditure.cash_flow_item, 'name', None),
                '_sort_date': expenditure.date,
            })

        for transfer in transfer_queryset[:limit]:
            items.append({
                'id': _serialize_uuid(transfer.id),
                'kind': 'transfer',
                'date': transfer.date.isoformat(),
                'amount': _money_str(transfer.amount),
                'description': transfer.comment or None,
                'wallet_from': _serialize_uuid(transfer.wallet_out_id),
                'wallet_from_name': getattr(transfer.wallet_out, 'name', None),
                'wallet_to': _serialize_uuid(transfer.wallet_in_id),
                'wallet_to_name': getattr(transfer.wallet_in, 'name', None),
                '_sort_date': transfer.date,
            })

        items.sort(
            key=lambda row: (
                row['_sort_date'],
                row['kind'],
                str(row['id']),
            ),
            reverse=True,
        )
        items = items[:limit]

        for item in items:
            item.pop('_sort_date')

        return items

    @extend_schema(
        parameters=[DashboardOverviewQuerySerializer],
        responses=DashboardOverviewResponseSerializer,
        description='Сводный dashboard с остатками, бюджетом и сравнением месяцев.',
    )
    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        query = DashboardOverviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        selected_at = query.validated_data.get('date')
        if selected_at is None:
            selected_at = timezone.localtime(timezone.now())
        else:
            selected_at = _parse_selected_at(
                request.query_params.get('date'),
                selected_at,
            )
        hide_hidden_wallets = query.validated_data.get('hide_hidden_wallets', True)

        selected_day_end = _day_end(selected_at)
        selected_month_start = _month_start(selected_at)
        selected_month_end = _month_end(selected_month_start)
        previous_month_start = _shift_month(selected_month_start, -1)
        previous_month_end = _month_end(previous_month_start)

        wallets_queryset = Wallet.objects.filter(deleted=False)
        if hide_hidden_wallets:
            wallets_queryset = wallets_queryset.filter(hidden=False)

        wallet_totals = {
            row['wallet_id']: _money(row['total_amount'])
            for row in FlowOfFunds.objects.filter(
                wallet__in=wallets_queryset,
                period__lte=selected_day_end,
            ).values('wallet_id').annotate(total_amount=Sum('amount'))
        }

        wallet_rows = []
        wallet_total = ZERO_AMOUNT
        for wallet in wallets_queryset:
            balance = wallet_totals.get(wallet.id, ZERO_AMOUNT)
            if balance == ZERO_AMOUNT:
                continue
            wallet_total += balance
            wallet_rows.append({
                'wallet_id': str(wallet.id),
                'wallet_name': wallet.name,
                'hidden': wallet.hidden,
                'balance': _money_str(balance),
                '_balance': balance,
            })
        wallet_rows.sort(key=lambda row: (row['_balance'], row['wallet_name']), reverse=True)
        for row in wallet_rows:
            row.pop('_balance')

        budget_expense_turnovers = BudgetExpense.objects.filter(
            period__gte=selected_month_start,
            period__lte=selected_month_end,
            project__isnull=True,
            cash_flow_item__isnull=False,
        ).values(
            'cash_flow_item_id',
            'cash_flow_item__name',
        ).annotate(
            planned_total=Sum('amount', filter=Q(type_of_document=5)),
            actual_total=Sum(
                'amount',
                filter=Q(type_of_document__in=[1, 2, 4], period__lte=selected_day_end),
            ),
        )

        budget_items = []
        budget_remaining_total = ZERO_AMOUNT
        budget_overrun_total = ZERO_AMOUNT
        for row in budget_expense_turnovers:
            planned_total = _money(row['planned_total'])
            actual_total = _money(row['actual_total'])
            remaining = max(planned_total - actual_total, ZERO_AMOUNT)
            overrun = max(actual_total - planned_total, ZERO_AMOUNT)
            budget_remaining_total += remaining
            budget_overrun_total += overrun
            budget_items.append({
                'cash_flow_item_id': str(row['cash_flow_item_id']),
                'cash_flow_item_name': row['cash_flow_item__name'],
                'remaining': _money_str(remaining),
                'overrun': _money_str(overrun),
                '_remaining': remaining,
                '_overrun': overrun,
            })
        budget_items.sort(key=lambda row: (row['_remaining'], row['_overrun'], row['cash_flow_item_name']), reverse=True)
        for row in budget_items:
            row.pop('_remaining')
            row.pop('_overrun')

        budget_income_totals = BudgetIncome.objects.filter(
            period__gte=selected_month_start,
            period__lte=selected_month_end,
            project__isnull=True,
        ).aggregate(
            planned_total=Sum('amount', filter=Q(type_of_document=5)),
            actual_total=Sum('amount', filter=Q(type_of_document=3, period__lte=selected_day_end)),
        )
        income_planned_total = _money(budget_income_totals['planned_total'])
        income_actual_total = _money(budget_income_totals['actual_total'])
        income_remaining_total = max(_money(income_planned_total - income_actual_total), ZERO_AMOUNT)

        previous_income_total, previous_expense_total = _flow_period_totals(previous_month_start, previous_month_end)
        current_income_total, current_expense_total = _flow_period_totals(selected_month_start, selected_day_end)

        if previous_expense_total == ZERO_AMOUNT:
            expense_difference = ZERO_AMOUNT
        else:
            expense_difference = _money(
                (previous_expense_total - current_expense_total) / previous_expense_total * 100
            )

        if current_income_total == ZERO_AMOUNT:
            income_difference = Decimal('100.00')
        else:
            income_difference = _money(
                (current_income_total - previous_income_total) / current_income_total * 100
            )

        cash_with_budget = _money(
            wallet_total - budget_remaining_total + income_remaining_total
        )

        return Response({
            'date': selected_day_end.isoformat(),
            'hide_hidden_wallets': hide_hidden_wallets,
            'wallets': wallet_rows,
            'wallet_total': _money_str(wallet_total),
            'budget_expense': {
                'items': budget_items,
                'remaining_total': _money_str(budget_remaining_total),
                'overrun_total': _money_str(budget_overrun_total),
            },
            'budget_income': {
                'planned_total': _money_str(income_planned_total),
                'actual_total': _money_str(income_actual_total),
                'remaining_total': _money_str(income_remaining_total),
            },
            'cash_with_budget': _money_str(cash_with_budget),
            'month_comparison': {
                'previous_month': {
                    'start': previous_month_start.isoformat(),
                    'expense': _money_str(previous_expense_total),
                    'income': _money_str(previous_income_total),
                },
                'current_month': {
                    'start': selected_month_start.isoformat(),
                    'expense': _money_str(current_expense_total),
                    'income': _money_str(current_income_total),
                },
                'difference_percent': {
                    'expense': _percent_str(expense_difference),
                    'income': _percent_str(income_difference),
                },
            },
        })

    @extend_schema(
        parameters=[DashboardRecentActivityQuerySerializer],
        responses=DashboardRecentActivityResponseSerializer,
        description='Последние документы для dashboard с учетом даты среза.',
    )
    @action(detail=False, methods=['get'], url_path='recent-activity')
    def recent_activity(self, request):
        query = DashboardRecentActivityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        selected_at = query.validated_data.get('date')
        if selected_at is None:
            selected_at = timezone.localtime(timezone.now())
        else:
            selected_at = _parse_selected_at(
                request.query_params.get('date'),
                selected_at,
            )

        selected_day_end = _day_end(selected_at)
        hide_hidden_wallets = query.validated_data.get('hide_hidden_wallets', True)
        limit = query.validated_data.get('limit', 20)

        items = self._build_recent_activity_items(
            selected_day_end=selected_day_end,
            hide_hidden_wallets=hide_hidden_wallets,
            limit=limit,
        )

        return Response({
            'date': selected_day_end.isoformat(),
            'hide_hidden_wallets': hide_hidden_wallets,
            'limit': limit,
            'items': items,
        })

    @extend_schema(
        parameters=[DashboardBudgetExpenseBreakdownQuerySerializer],
        responses=DashboardBudgetExpenseBreakdownResponseSerializer,
        description='Расшифровка план-факт и остатка по статье расходного бюджета для dashboard.',
    )
    @action(detail=False, methods=['get'], url_path='budget-expense-breakdown')
    def budget_expense_breakdown(self, request):
        query = DashboardBudgetExpenseBreakdownQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        selected_at = query.validated_data.get('date')
        if selected_at is None:
            selected_at = timezone.localtime(timezone.now())
        else:
            selected_at = _parse_selected_at(
                request.query_params.get('date'),
                selected_at,
            )

        cash_flow_item_id = query.validated_data['cash_flow_item']
        cash_flow_item = CashFlowItem.objects.filter(pk=cash_flow_item_id).first()
        if cash_flow_item is None:
            return Response({'detail': 'Статья не найдена.'}, status=status.HTTP_404_NOT_FOUND)

        selected_day_end = _day_end(selected_at)
        selected_month_start = _month_start(selected_at)

        base_queryset = BudgetExpense.objects.select_related('cash_flow_item').filter(
            period__gte=selected_month_start,
            period__lte=selected_day_end,
            project__isnull=True,
            cash_flow_item_id=cash_flow_item_id,
        )
        plan_queryset = base_queryset.filter(type_of_document=5)
        actual_queryset = base_queryset.filter(type_of_document__in=[1, 2, 4])

        planned_total = _money(plan_queryset.aggregate(total=Sum('amount'))['total'])
        actual_total = _money(actual_queryset.aggregate(total=Sum('amount'))['total'])
        remaining = _money(max(planned_total - actual_total, ZERO_AMOUNT))
        overrun = _money(max(actual_total - planned_total, ZERO_AMOUNT))

        details = [
            {
                'period': row.period.isoformat(),
                'document_id': _serialize_uuid(row.document_id),
                'document_type': row.get_type_of_document_display(),
                'entry_type': 'budget',
                'amount': _money_str(row.amount),
            }
            for row in plan_queryset.order_by('period', 'id')
        ]
        details.extend([
            {
                'period': row.period.isoformat(),
                'document_id': _serialize_uuid(row.document_id),
                'document_type': row.get_type_of_document_display(),
                'entry_type': 'actual',
                'amount': _money_str(row.amount),
            }
            for row in actual_queryset.order_by('period', 'id')
        ])
        details.sort(key=lambda row: (row['period'], row['entry_type'], str(row['document_id'] or '')))

        return Response({
            'date': selected_day_end.isoformat(),
            'cash_flow_item_id': str(cash_flow_item.id),
            'cash_flow_item_name': cash_flow_item.name,
            'planned_total': _money_str(planned_total),
            'actual_total': _money_str(actual_total),
            'remaining': _money_str(remaining),
            'overrun': _money_str(overrun),
            'details': details,
        })
