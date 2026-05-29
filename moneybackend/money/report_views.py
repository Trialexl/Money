from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import BudgetExpense, BudgetIncome, FlowOfFunds, MONEY_QUANTIZER, ZERO_AMOUNT
from .serializers import (
    BudgetReportQuerySerializer,
    BudgetReportResponseSerializer,
    CashFlowReportQuerySerializer,
    CashFlowReportResponseSerializer,
)


TRANSFER_DOCUMENT_TYPE = 2


def _money(value):
    if value is None:
        value = ZERO_AMOUNT
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(MONEY_QUANTIZER)


def _money_str(value):
    return f'{_money(value):.2f}'


def _serialize_report_filters(validated_data, **extra):
    filters = {}
    for key, value in validated_data.items():
        if hasattr(value, 'isoformat'):
            filters[key] = value.isoformat()
        else:
            filters[key] = str(value)
    for key, value in extra.items():
        if hasattr(value, 'isoformat'):
            filters[key] = value.isoformat()
        else:
            filters[key] = str(value)
    return filters


def _apply_period_filters(queryset, date_from=None, date_to=None):
    if date_from is not None:
        queryset = queryset.filter(period__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(period__lte=date_to)
    return queryset


def _serialize_uuid(value):
    return str(value) if value is not None else None


class ReportViewSet(viewsets.ViewSet):
    """Отчетные endpoints по мотивам 1С-отчетов."""

    permission_classes = [permissions.IsAdminUser]

    @extend_schema(
        parameters=[CashFlowReportQuerySerializer],
        responses=CashFlowReportResponseSerializer,
        description='Аналог отчета 1С по движению денежных средств.',
    )
    @action(detail=False, methods=['get'], url_path='cash-flow')
    def cash_flow(self, request):
        query = CashFlowReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        validated = query.validated_data

        date_from = validated.get('date_from')
        date_to = validated.get('date_to')
        if validated.get('limit_by_today'):
            today = timezone.now()
            if date_to is None or date_to > today:
                date_to = today

        base_queryset = FlowOfFunds.objects.select_related('wallet', 'cash_flow_item').filter(
            cash_flow_item__isnull=False
        ).exclude(type_of_document=TRANSFER_DOCUMENT_TYPE)

        wallet_id = validated.get('wallet')
        if wallet_id:
            base_queryset = base_queryset.filter(wallet_id=wallet_id)

        cash_flow_item_id = validated.get('cash_flow_item')
        if cash_flow_item_id:
            base_queryset = base_queryset.filter(cash_flow_item_id=cash_flow_item_id)

        wallet_balance_queryset = FlowOfFunds.objects.select_related('wallet').filter(wallet__isnull=False)
        if wallet_id:
            wallet_balance_queryset = wallet_balance_queryset.filter(wallet_id=wallet_id)

        opening_balance = ZERO_AMOUNT
        wallet_opening_balances = []
        if date_from is not None:
            opening_queryset = base_queryset.filter(period__lt=date_from)
            opening_balance = _money(opening_queryset.aggregate(total=Sum('amount'))['total'])
            wallet_opening_queryset = wallet_balance_queryset.filter(period__lt=date_from)
            wallet_opening_balances = [
                {
                    'wallet_id': _serialize_uuid(row['wallet_id']),
                    'wallet_name': row['wallet__name'],
                    'opening_balance': _money_str(row['opening_balance']),
                }
                for row in wallet_opening_queryset.values('wallet_id', 'wallet__name').annotate(
                    opening_balance=Sum('amount')
                ).order_by('wallet__name')
            ]

        queryset = _apply_period_filters(base_queryset, date_from=date_from, date_to=date_to)

        month_rows = []
        monthly_queryset = queryset.annotate(period_month=TruncMonth('period')).values('period_month').annotate(
            income_total=Sum('amount', filter=Q(amount__gt=0)),
            expense_total=Sum('amount', filter=Q(amount__lt=0)),
        ).order_by('period_month')
        for row in monthly_queryset:
            month_rows.append({
                'period': row['period_month'],
                'income': _money_str(row['income_total']),
                'expense': _money_str(-(row['expense_total'] or ZERO_AMOUNT)),
            })

        detail_rows = [
            {
                'period': row.period,
                'document_id': _serialize_uuid(row.document_id),
                'document_type': row.get_type_of_document_display(),
                'wallet_id': _serialize_uuid(row.wallet_id),
                'wallet_name': getattr(row.wallet, 'name', None),
                'cash_flow_item_id': _serialize_uuid(row.cash_flow_item_id),
                'cash_flow_item_name': getattr(row.cash_flow_item, 'name', None),
                'income': _money_str(row.amount if row.amount > ZERO_AMOUNT else ZERO_AMOUNT),
                'expense': _money_str(-row.amount if row.amount < ZERO_AMOUNT else ZERO_AMOUNT),
            }
            for row in queryset.order_by('period', 'id')
        ]

        wallet_balance_movement_rows = [
            {
                'period': row['period_date'],
                'wallet_id': _serialize_uuid(row['wallet_id']),
                'wallet_name': row['wallet__name'],
                'amount': _money_str(row['amount']),
            }
            for row in _apply_period_filters(wallet_balance_queryset, date_from=date_from, date_to=date_to)
            .annotate(period_date=TruncDate('period'))
            .values('period_date', 'wallet_id', 'wallet__name')
            .annotate(amount=Sum('amount'))
            .order_by('period_date', 'wallet__name')
        ]

        income_total = _money(
            queryset.aggregate(total=Sum('amount', filter=Q(amount__gt=0)))['total']
        )
        expense_total = _money(
            -(queryset.aggregate(total=Sum('amount', filter=Q(amount__lt=0)))['total'] or ZERO_AMOUNT)
        )

        return Response({
            'filters': _serialize_report_filters(validated, effective_date_to=date_to) if validated.get('limit_by_today') else _serialize_report_filters(validated),
            'totals': {
                'income': _money_str(income_total),
                'expense': _money_str(expense_total),
            },
            'opening_balance': _money_str(opening_balance),
            'wallet_opening_balances': wallet_opening_balances,
            'wallet_balance_movements': wallet_balance_movement_rows,
            'months': month_rows,
            'details': detail_rows,
        })

    def _build_budget_report(self, request, model_class, actual_type_ids):
        query = BudgetReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        validated = query.validated_data

        date_from = validated.get('date_from')
        date_to = validated.get('date_to')
        actual_date_to = date_to
        if validated.get('limit_by_today'):
            today = timezone.now()
            if actual_date_to is None or actual_date_to > today:
                actual_date_to = today

        plan_queryset = model_class.objects.select_related('project', 'cash_flow_item').filter(type_of_document=5)
        actual_queryset = model_class.objects.select_related('project', 'cash_flow_item').filter(
            type_of_document__in=actual_type_ids
        )

        plan_queryset = _apply_period_filters(plan_queryset, date_from=date_from, date_to=date_to)
        actual_queryset = _apply_period_filters(actual_queryset, date_from=date_from, date_to=actual_date_to)

        project_id = validated.get('project')
        if project_id:
            plan_queryset = plan_queryset.filter(project_id=project_id)
            actual_queryset = actual_queryset.filter(project_id=project_id)
        else:
            plan_queryset = plan_queryset.filter(project__isnull=True)
            actual_queryset = actual_queryset.filter(project__isnull=True)

        cash_flow_item_id = validated.get('cash_flow_item')
        if cash_flow_item_id:
            plan_queryset = plan_queryset.filter(cash_flow_item_id=cash_flow_item_id)
            actual_queryset = actual_queryset.filter(cash_flow_item_id=cash_flow_item_id)

        summary_rows = {}
        for row in plan_queryset.annotate(period_month=TruncMonth('period')).values(
            'period_month',
            'project_id',
            'project__name',
            'cash_flow_item_id',
            'cash_flow_item__name',
        ).annotate(total_amount=Sum('amount')):
            key = (
                row['period_month'],
                row['project_id'],
                row['project__name'],
                row['cash_flow_item_id'],
                row['cash_flow_item__name'],
            )
            summary_rows[key] = {
                'period': row['period_month'],
                'project_id': row['project_id'],
                'project_name': row['project__name'],
                'cash_flow_item_id': row['cash_flow_item_id'],
                'cash_flow_item_name': row['cash_flow_item__name'],
                'actual': ZERO_AMOUNT,
                'budget': _money(row['total_amount']),
            }

        for row in actual_queryset.annotate(period_month=TruncMonth('period')).values(
            'period_month',
            'project_id',
            'project__name',
            'cash_flow_item_id',
            'cash_flow_item__name',
        ).annotate(total_amount=Sum('amount')):
            key = (
                row['period_month'],
                row['project_id'],
                row['project__name'],
                row['cash_flow_item_id'],
                row['cash_flow_item__name'],
            )
            if key not in summary_rows:
                summary_rows[key] = {
                    'period': row['period_month'],
                    'project_id': row['project_id'],
                    'project_name': row['project__name'],
                    'cash_flow_item_id': row['cash_flow_item_id'],
                    'cash_flow_item_name': row['cash_flow_item__name'],
                    'actual': ZERO_AMOUNT,
                    'budget': ZERO_AMOUNT,
                }
            summary_rows[key]['actual'] = _money(row['total_amount'])

        summary = []
        for row in summary_rows.values():
            balance = _money(row['budget'] - row['actual'])
            summary.append({
                'period': row['period'],
                'project_id': _serialize_uuid(row['project_id']),
                'project_name': row['project_name'],
                'cash_flow_item_id': _serialize_uuid(row['cash_flow_item_id']),
                'cash_flow_item_name': row['cash_flow_item_name'],
                'actual': _money_str(row['actual']),
                'budget': _money_str(row['budget']),
                'balance': _money_str(balance),
                '_sort_project': row['project_name'] or '',
                '_sort_item': row['cash_flow_item_name'] or '',
            })
        summary.sort(
            key=lambda row: (
                row['period'],
                row['project_id'] is None,
                row['_sort_project'],
                row['_sort_item'],
            )
        )
        for row in summary:
            row.pop('_sort_project')
            row.pop('_sort_item')

        detail_rows = [
            {
                'period': row.period,
                'document_id': _serialize_uuid(row.document_id),
                'document_type': row.get_type_of_document_display(),
                'entry_type': 'budget',
                'project_id': _serialize_uuid(row.project_id),
                'project_name': getattr(row.project, 'name', None),
                'cash_flow_item_id': _serialize_uuid(row.cash_flow_item_id),
                'cash_flow_item_name': getattr(row.cash_flow_item, 'name', None),
                'amount': _money_str(row.amount),
            }
            for row in plan_queryset.order_by('period', 'id')
        ]
        detail_rows.extend([
            {
                'period': row.period,
                'document_id': _serialize_uuid(row.document_id),
                'document_type': row.get_type_of_document_display(),
                'entry_type': 'actual',
                'project_id': _serialize_uuid(row.project_id),
                'project_name': getattr(row.project, 'name', None),
                'cash_flow_item_id': _serialize_uuid(row.cash_flow_item_id),
                'cash_flow_item_name': getattr(row.cash_flow_item, 'name', None),
                'amount': _money_str(row.amount),
            }
            for row in actual_queryset.order_by('period', 'id')
        ])
        detail_rows.sort(key=lambda row: (row['period'], row['entry_type'], str(row['document_id'] or '')))

        budget_total = _money(plan_queryset.aggregate(total=Sum('amount'))['total'])
        actual_total = _money(actual_queryset.aggregate(total=Sum('amount'))['total'])
        balance_total = _money(budget_total - actual_total)

        return Response({
            'filters': _serialize_report_filters(
                validated,
                effective_actual_date_to=actual_date_to if validated.get('limit_by_today') else date_to,
            ),
            'totals': {
                'actual': _money_str(actual_total),
                'budget': _money_str(budget_total),
                'balance': _money_str(balance_total),
            },
            'summary': summary,
            'details': detail_rows,
        })

    @extend_schema(
        parameters=[BudgetReportQuerySerializer],
        responses=BudgetReportResponseSerializer,
        description='Аналог 1С-отчета по бюджетированию расходов.',
    )
    @action(detail=False, methods=['get'], url_path='budget-expense')
    def budget_expense(self, request):
        return self._build_budget_report(request, BudgetExpense, [1, 2, 4])

    @extend_schema(
        parameters=[BudgetReportQuerySerializer],
        responses=BudgetReportResponseSerializer,
        description='Аналог 1С-отчета по бюджетированию доходов.',
    )
    @action(detail=False, methods=['get'], url_path='budget-income')
    def budget_income(self, request):
        return self._build_budget_report(request, BudgetIncome, [3])
