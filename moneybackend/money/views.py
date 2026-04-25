from calendar import monthrange
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import mimetypes
import re
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import InvalidPage
from django.http import HttpResponse
from django.db import transaction
from rest_framework import permissions, serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema

from .ai_service import AiOperationService
from .models import *
from .onec_context import is_onec_sync_request
from .serializers import *
from .permissions import IsAdminOrReadOnly


PERCENT_QUANTIZER = Decimal('0.01')


def _dashboard_money(value):
    if value is None:
        value = ZERO_AMOUNT
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(MONEY_QUANTIZER)


def _dashboard_money_str(value):
    return f'{_dashboard_money(value):.2f}'


def _dashboard_percent_str(value):
    return f'{_dashboard_money(value).quantize(PERCENT_QUANTIZER):.2f}'


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


def _parse_dashboard_selected_at(raw_value, fallback):
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
    ).aggregate(
        income_total=Sum('amount', filter=Q(amount__gt=0)),
        expense_total=Sum('amount', filter=Q(amount__lt=0)),
    )

    income_total = _dashboard_money(totals['income_total'])
    expense_total = _dashboard_money(-(totals['expense_total'] or ZERO_AMOUNT))
    return income_total, expense_total


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


class OneCSyncSoftDeleteCompatibilityMixin:
    """Позволяет 1С-синхронизации обращаться к detail endpoint уже удаленных записей."""

    soft_delete_field = 'deleted'

    def include_soft_deleted_for_onec_detail(self):
        if not is_onec_sync_request(self.request):
            return False

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        return lookup_url_kwarg in getattr(self, 'kwargs', {})

    def filter_soft_deleted(self, queryset):
        if self.include_soft_deleted_for_onec_detail():
            return queryset
        return queryset.filter(**{self.soft_delete_field: False})


class CatalogPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    allowed_page_sizes = {20, 50, 100}

    def get_page_size(self, request):
        raw_value = request.query_params.get(self.page_size_query_param)
        if raw_value is None:
            return self.page_size

        try:
            page_size = int(raw_value)
        except (TypeError, ValueError):
            return self.page_size

        if page_size not in self.allowed_page_sizes:
            return self.page_size
        return page_size

    def paginate_queryset(self, queryset, request, view=None):
        self.request = request
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        page_number = request.query_params.get(self.page_query_param, 1)

        if page_number in self.last_page_strings:
            page_number = paginator.num_pages

        try:
            self.page = paginator.page(page_number)
        except InvalidPage:
            fallback_page = paginator.num_pages or 1
            self.page = paginator.page(fallback_page)

        if paginator.num_pages > 1 and self.template is not None:
            self.display_page_controls = True

        return list(self.page)


class FinancialOperationListFilteringMixin:
    list_query_serializer_class = None
    search_fields = ()

    def get_list_filters(self):
        serializer_class = self.list_query_serializer_class
        if serializer_class is None:
            return {}

        serializer = serializer_class(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def apply_search_filter(self, queryset, search):
        if not search or not self.search_fields:
            return queryset

        conditions = Q()
        for field_name in self.search_fields:
            conditions |= Q(**{f'{field_name}__icontains': search})
        return queryset.filter(conditions)


# Справочники
class CashFlowItemViewSet(OneCSyncSoftDeleteCompatibilityMixin, viewsets.ModelViewSet):
    """
    API для управления статьями движения денежных средств
    
    Поддерживает иерархическую структуру через поле parent.
    Админы имеют полный доступ, пользователи - только чтение.
    """
    queryset = CashFlowItem.objects.all()
    serializer_class = CashFlowItemSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        """Фильтрация неудаленных записей"""
        return self.filter_soft_deleted(self.queryset)
    
    @action(detail=False, methods=['get'])
    def hierarchy(self, request):
        """Получить иерархическую структуру статей"""
        root_items = self.get_queryset().filter(parent=None)
        # Здесь можно добавить логику построения дерева
        serializer = self.get_serializer(root_items, many=True)
        return Response({'hierarchy': serializer.data})
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по статьям движения средств"""
        queryset = self.get_queryset()
        
        # Фильтрация по периоду
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        
        flow_queryset = FlowOfFunds.objects.all()
        if date_from:
            flow_queryset = flow_queryset.filter(period__gte=date_from)
        if date_to:
            flow_queryset = flow_queryset.filter(period__lte=date_to)
        
        # Сумма по статьям
        item_summary = flow_queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount'),
            record_count=Count('id')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = flow_queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_amount': float(total_amount),
            'item_summary': list(item_summary),
            'period_filter': {
                'date_from': date_from,
                'date_to': date_to
            }
        })


class WalletViewSet(OneCSyncSoftDeleteCompatibilityMixin, viewsets.ModelViewSet):
    """
    API для управления кошельками
    
    Включает фильтрацию скрытых кошельков и статистику.
    """
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        """Фильтрация неудаленных и скрытых кошельков"""
        queryset = self.filter_soft_deleted(self.queryset)
        if not self.request.user.is_staff:
            queryset = queryset.filter(hidden=False)
        return queryset

    def _build_wallet_recent_operations(self, wallet, limit=10):
        receipt_queryset = Receipt.objects.filter(
            deleted=False,
            wallet=wallet,
        ).order_by('-date')
        expenditure_queryset = Expenditure.objects.filter(
            deleted=False,
            wallet=wallet,
        ).order_by('-date')

        items = []

        for receipt in receipt_queryset[:limit]:
            items.append({
                'id': _serialize_uuid(receipt.id),
                'kind': 'receipt',
                'date': receipt.date.isoformat(),
                'amount': _dashboard_money_str(receipt.amount),
                'description': receipt.comment or None,
                '_sort_date': receipt.date,
            })

        for expenditure in expenditure_queryset[:limit]:
            items.append({
                'id': _serialize_uuid(expenditure.id),
                'kind': 'expenditure',
                'date': expenditure.date.isoformat(),
                'amount': _dashboard_money_str(expenditure.amount),
                'description': expenditure.comment or None,
                '_sort_date': expenditure.date,
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
        responses={200: WalletBalanceResponseSerializer},
    )
    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        """Получить баланс кошелька на основе регистра движения средств"""
        wallet = self.get_object()
        
        # Подсчитываем баланс из регистра FlowOfFunds
        balance = FlowOfFunds.objects.filter(
            wallet=wallet
        ).aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        return Response({
            'wallet_id': str(wallet.id),
            'wallet_name': wallet.name,
            'balance': float(balance),
            'currency': 'RUB',  # Можно добавить поле валюты в модель Wallet
            'last_updated': timezone.now()
        })

    @extend_schema(
        responses={200: WalletSummaryResponseSerializer},
    )
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Компактная сводка по кошельку для быстрой загрузки detail page."""
        wallet = self.get_object()

        balance = _dashboard_money(
            FlowOfFunds.objects.filter(wallet=wallet).aggregate(total=Sum('amount'))['total']
        )
        income_total = _dashboard_money(
            Receipt.objects.filter(wallet=wallet, deleted=False).aggregate(total=Sum('amount'))['total']
        )
        expense_total = _dashboard_money(
            Expenditure.objects.filter(wallet=wallet, deleted=False).aggregate(total=Sum('amount'))['total']
        )

        return Response({
            'wallet_id': str(wallet.id),
            'wallet_name': wallet.name,
            'balance': _dashboard_money_str(balance),
            'income_total': _dashboard_money_str(income_total),
            'expense_total': _dashboard_money_str(expense_total),
            'recent_operations': self._build_wallet_recent_operations(wallet),
        })
    
    @extend_schema(
        responses={200: WalletBalancesResponseSerializer},
    )
    @action(detail=False, methods=['get'])
    def balances(self, request):
        """Получить балансы всех кошельков"""
        wallets = self.get_queryset()
        balances = []
        
        for wallet in wallets:
            balance = (
                FlowOfFunds.objects.filter(wallet=wallet).aggregate(total=Sum('amount'))['total']
                or ZERO_AMOUNT
            )
            balance = _dashboard_money(balance)
            if balance == ZERO_AMOUNT:
                continue
            
            balances.append({
                'wallet_id': str(wallet.id),
                'wallet_name': wallet.name,
                'balance': float(balance),
                'currency': 'RUB'
            })
        
        # Сортируем по балансу (от большего к меньшему)
        balances.sort(key=lambda x: x['balance'], reverse=True)
        
        return Response({
            'balances': balances,
            'total_wallets': len(balances),
            'total_balance': sum(b['balance'] for b in balances)
        })


# Регистры
class FlowOfFundsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра движения средств
    
    Только для чтения. Поддерживает фильтрацию по кошельку, статье, периоду.
    """
    queryset = FlowOfFunds.objects.all()
    serializer_class = FlowOfFundsSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Фильтрация по параметрам запроса"""
        queryset = self.queryset.select_related('wallet', 'cash_flow_item')
        
        # Фильтрация по кошельку
        wallet_id = self.request.query_params.get('wallet')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)
        
        # Фильтрация по статье
        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)
        
        # Фильтрация по периоду (с даты)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)
        
        # Фильтрация по периоду (до даты)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)
        
        return queryset.order_by('-period')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по движению средств"""
        queryset = self.get_queryset()
        
        # Сумма по кошелькам
        wallet_summary = queryset.values('wallet__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Сумма по статьям
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_amount': float(total_amount),
            'wallet_summary': list(wallet_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count()
        })


class BudgetIncomeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра доходов бюджета
    
    Только для чтения. Поддерживает фильтрацию по проекту, статье, периоду.
    """
    queryset = BudgetIncome.objects.all()
    serializer_class = BudgetIncomeSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Фильтрация по параметрам запроса"""
        queryset = self.queryset.select_related('project', 'cash_flow_item')
        
        # Фильтрация по проекту
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        # Фильтрация по статье
        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)
        
        # Фильтрация по периоду
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)
        
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)
        
        return queryset.order_by('-period')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по доходам бюджета"""
        queryset = self.get_queryset()
        
        # Сумма по проектам
        project_summary = queryset.values('project__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Сумма по статьям
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_income': float(total_amount),
            'project_summary': list(project_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count()
        })


class BudgetExpenseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра расходов бюджета
    
    Только для чтения. Поддерживает фильтрацию по проекту, статье, периоду.
    """
    queryset = BudgetExpense.objects.all()
    serializer_class = BudgetExpenseSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Фильтрация по параметрам запроса"""
        queryset = self.queryset.select_related('project', 'cash_flow_item')
        
        # Фильтрация по проекту
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        # Фильтрация по статье
        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)
        
        # Фильтрация по периоду
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)
        
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)
        
        return queryset.order_by('-period')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по расходам бюджета"""
        queryset = self.get_queryset()
        
        # Сумма по проектам
        project_summary = queryset.values('project__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Сумма по статьям
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_expense': float(total_amount),
            'project_summary': list(project_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count()
        })

    
class ProjectViewSet(OneCSyncSoftDeleteCompatibilityMixin, viewsets.ModelViewSet):
    """API для управления проектами"""
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        """Фильтрация неудаленных проектов"""
        return self.filter_soft_deleted(self.queryset)


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
                'amount': _dashboard_money_str(receipt.amount),
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
                'amount': _dashboard_money_str(expenditure.amount),
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
                'amount': _dashboard_money_str(transfer.amount),
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
            selected_at = _parse_dashboard_selected_at(
                request.query_params.get('date'),
                selected_at,
            )
        hide_hidden_wallets = query.validated_data.get('hide_hidden_wallets', True)

        selected_day_end = _day_end(selected_at)
        selected_month_start = _month_start(selected_at)
        previous_month_start = _shift_month(selected_month_start, -1)
        previous_month_end = _month_end(previous_month_start)

        wallets_queryset = Wallet.objects.filter(deleted=False)
        if hide_hidden_wallets:
            wallets_queryset = wallets_queryset.filter(hidden=False)

        wallet_totals = {
            row['wallet_id']: _dashboard_money(row['total_amount'])
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
                'balance': _dashboard_money_str(balance),
                '_balance': balance,
            })
        wallet_rows.sort(key=lambda row: (row['_balance'], row['wallet_name']), reverse=True)
        for row in wallet_rows:
            row.pop('_balance')

        budget_expense_turnovers = BudgetExpense.objects.filter(
            period__gte=selected_month_start,
            period__lte=selected_day_end,
            project__isnull=True,
            cash_flow_item__isnull=False,
        ).values(
            'cash_flow_item_id',
            'cash_flow_item__name',
        ).annotate(
            planned_total=Sum('amount', filter=Q(type_of_document=5)),
            actual_total=Sum('amount', filter=Q(type_of_document__in=[1, 2, 4])),
        )

        budget_items = []
        budget_remaining_total = ZERO_AMOUNT
        budget_overrun_total = ZERO_AMOUNT
        for row in budget_expense_turnovers:
            planned_total = _dashboard_money(row['planned_total'])
            actual_total = _dashboard_money(row['actual_total'])
            remaining = max(planned_total - actual_total, ZERO_AMOUNT)
            overrun = max(actual_total - planned_total, ZERO_AMOUNT)
            budget_remaining_total += remaining
            budget_overrun_total += overrun
            budget_items.append({
                'cash_flow_item_id': str(row['cash_flow_item_id']),
                'cash_flow_item_name': row['cash_flow_item__name'],
                'remaining': _dashboard_money_str(remaining),
                'overrun': _dashboard_money_str(overrun),
                '_remaining': remaining,
                '_overrun': overrun,
            })
        budget_items.sort(key=lambda row: (row['_remaining'], row['_overrun'], row['cash_flow_item_name']), reverse=True)
        for row in budget_items:
            row.pop('_remaining')
            row.pop('_overrun')

        budget_income_totals = BudgetIncome.objects.filter(
            period__gte=selected_month_start,
            period__lte=selected_day_end,
            project__isnull=True,
        ).aggregate(
            planned_total=Sum('amount', filter=Q(type_of_document=5)),
            actual_total=Sum('amount', filter=Q(type_of_document=3)),
        )
        income_planned_total = _dashboard_money(budget_income_totals['planned_total'])
        income_actual_total = _dashboard_money(budget_income_totals['actual_total'])
        income_remaining_total = _dashboard_money(income_planned_total - income_actual_total)

        previous_income_total, previous_expense_total = _flow_period_totals(previous_month_start, previous_month_end)
        current_income_total, current_expense_total = _flow_period_totals(selected_month_start, selected_day_end)

        if previous_expense_total == ZERO_AMOUNT:
            expense_difference = ZERO_AMOUNT
        else:
            expense_difference = _dashboard_money(
                (previous_expense_total - current_expense_total) / previous_expense_total * 100
            )

        if current_income_total == ZERO_AMOUNT:
            income_difference = Decimal('100.00')
        else:
            income_difference = _dashboard_money(
                (current_income_total - previous_income_total) / current_income_total * 100
            )

        cash_with_budget = _dashboard_money(
            wallet_total - budget_remaining_total + income_remaining_total
        )

        return Response({
            'date': selected_day_end.isoformat(),
            'hide_hidden_wallets': hide_hidden_wallets,
            'wallets': wallet_rows,
            'wallet_total': _dashboard_money_str(wallet_total),
            'budget_expense': {
                'items': budget_items,
                'remaining_total': _dashboard_money_str(budget_remaining_total),
                'overrun_total': _dashboard_money_str(budget_overrun_total),
            },
            'budget_income': {
                'planned_total': _dashboard_money_str(income_planned_total),
                'actual_total': _dashboard_money_str(income_actual_total),
                'remaining_total': _dashboard_money_str(income_remaining_total),
            },
            'cash_with_budget': _dashboard_money_str(cash_with_budget),
            'month_comparison': {
                'previous_month': {
                    'start': previous_month_start.isoformat(),
                    'expense': _dashboard_money_str(previous_expense_total),
                    'income': _dashboard_money_str(previous_income_total),
                },
                'current_month': {
                    'start': selected_month_start.isoformat(),
                    'expense': _dashboard_money_str(current_expense_total),
                    'income': _dashboard_money_str(current_income_total),
                },
                'difference_percent': {
                    'expense': _dashboard_percent_str(expense_difference),
                    'income': _dashboard_percent_str(income_difference),
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
            selected_at = _parse_dashboard_selected_at(
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

        queryset = FlowOfFunds.objects.select_related('wallet', 'cash_flow_item')
        queryset = _apply_period_filters(queryset, date_from=date_from, date_to=date_to)

        wallet_id = validated.get('wallet')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)

        cash_flow_item_id = validated.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)

        month_rows = []
        monthly_queryset = queryset.annotate(period_month=TruncMonth('period')).values('period_month').annotate(
            income_total=Sum('amount', filter=Q(amount__gt=0)),
            expense_total=Sum('amount', filter=Q(amount__lt=0)),
        ).order_by('period_month')
        for row in monthly_queryset:
            month_rows.append({
                'period': row['period_month'],
                'income': _dashboard_money_str(row['income_total']),
                'expense': _dashboard_money_str(-(row['expense_total'] or ZERO_AMOUNT)),
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
                'income': _dashboard_money_str(row.amount if row.amount > ZERO_AMOUNT else ZERO_AMOUNT),
                'expense': _dashboard_money_str(-row.amount if row.amount < ZERO_AMOUNT else ZERO_AMOUNT),
            }
            for row in queryset.order_by('period', 'id')
        ]

        income_total = _dashboard_money(
            queryset.aggregate(total=Sum('amount', filter=Q(amount__gt=0)))['total']
        )
        expense_total = _dashboard_money(
            -(queryset.aggregate(total=Sum('amount', filter=Q(amount__lt=0)))['total'] or ZERO_AMOUNT)
        )

        return Response({
            'filters': _serialize_report_filters(validated, effective_date_to=date_to) if validated.get('limit_by_today') else _serialize_report_filters(validated),
            'totals': {
                'income': _dashboard_money_str(income_total),
                'expense': _dashboard_money_str(expense_total),
            },
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
                'budget': _dashboard_money(row['total_amount']),
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
            summary_rows[key]['actual'] = _dashboard_money(row['total_amount'])

        summary = []
        for row in summary_rows.values():
            balance = _dashboard_money(row['budget'] - row['actual'])
            summary.append({
                'period': row['period'],
                'project_id': _serialize_uuid(row['project_id']),
                'project_name': row['project_name'],
                'cash_flow_item_id': _serialize_uuid(row['cash_flow_item_id']),
                'cash_flow_item_name': row['cash_flow_item_name'],
                'actual': _dashboard_money_str(row['actual']),
                'budget': _dashboard_money_str(row['budget']),
                'balance': _dashboard_money_str(balance),
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
                'amount': _dashboard_money_str(row.amount),
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
                'amount': _dashboard_money_str(row.amount),
            }
            for row in actual_queryset.order_by('period', 'id')
        ])
        detail_rows.sort(key=lambda row: (row['period'], row['entry_type'], str(row['document_id'] or '')))

        budget_total = _dashboard_money(plan_queryset.aggregate(total=Sum('amount'))['total'])
        actual_total = _dashboard_money(actual_queryset.aggregate(total=Sum('amount'))['total'])
        balance_total = _dashboard_money(budget_total - actual_total)

        return Response({
            'filters': _serialize_report_filters(
                validated,
                effective_actual_date_to=actual_date_to if validated.get('limit_by_today') else date_to,
            ),
            'totals': {
                'actual': _dashboard_money_str(actual_total),
                'budget': _dashboard_money_str(budget_total),
                'balance': _dashboard_money_str(balance_total),
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


# Финансовые операции
class ReceiptViewSet(OneCSyncSoftDeleteCompatibilityMixin, FinancialOperationListFilteringMixin, viewsets.ModelViewSet):
    """
    API для управления приходами денежных средств
    
    При создании/обновлении автоматически обновляются регистры.
    """
    queryset = Receipt.objects.all()
    serializer_class = ReceiptSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = CatalogPageNumberPagination
    list_query_serializer_class = ReceiptListQuerySerializer
    search_fields = ('comment', 'number', 'wallet__name', 'cash_flow_item__name')
    
    def get_queryset(self):
        """Фильтрация неудаленных записей"""
        queryset = self.filter_soft_deleted(
            self.queryset.select_related('wallet', 'cash_flow_item')
        ).order_by('-date')

        if getattr(self, 'action', None) != 'list':
            return queryset

        filters = self.get_list_filters()
        queryset = self.apply_search_filter(queryset, filters.get('search'))

        if filters.get('wallet'):
            queryset = queryset.filter(wallet_id=filters['wallet'])
        if filters.get('cash_flow_item'):
            queryset = queryset.filter(cash_flow_item_id=filters['cash_flow_item'])
        if filters.get('date_from'):
            queryset = queryset.filter(date__date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(date__date__lte=filters['date_to'])
        if filters.get('amount_min') is not None:
            queryset = queryset.filter(amount__gte=filters['amount_min'])
        if filters.get('amount_max') is not None:
            queryset = queryset.filter(amount__lte=filters['amount_max'])

        return queryset

    @extend_schema(
        parameters=[ReceiptListQuerySerializer],
        responses={200: ReceiptSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров"""
        instance.deleted = True
        instance.save()  # Триггер очистки регистров через миксин


class DocumentGraphicReplacementMixin:
    """Атомарно заменяет все строки графика документа без пересчета шапки."""

    graphic_model = None
    graphic_serializer_class = None

    def get_graphic_replace_serializer(self, *args, **kwargs):
        return GraphicReplaceSerializer(*args, **kwargs)

    def validate_graphic_replacement(self, document, rows):
        return None

    @action(detail=True, methods=['put'], url_path='replace-graphics')
    def replace_graphics(self, request, pk=None):
        """Атомарно заменяет все строки графика документа без пересчета шапки."""
        document = self.get_object()
        payload = self.get_graphic_replace_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        rows = payload.validated_data['rows']
        self.validate_graphic_replacement(document, rows)

        with transaction.atomic():
            document.items.all().delete()
            self.graphic_model.objects.bulk_create([
                self.graphic_model(
                    document=document,
                    date_start=row['date_start'],
                    amount=row['amount'],
                )
                for row in rows
            ])
            sync_document_registers(document)

        return Response(
            self.graphic_serializer_class(document.items.order_by('date_start'), many=True).data,
            status=status.HTTP_200_OK,
        )


class ExpenditureViewSet(OneCSyncSoftDeleteCompatibilityMixin, FinancialOperationListFilteringMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления расходами денежных средств
    
    Поддерживает фильтрацию по включению в бюджет.
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """
    queryset = Expenditure.objects.all()
    serializer_class = ExpenditureSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = ExpenditureGraphic
    graphic_serializer_class = ExpenditureGraphicSerializer
    pagination_class = CatalogPageNumberPagination
    list_query_serializer_class = ExpenditureListQuerySerializer
    search_fields = ('comment', 'number', 'wallet__name', 'cash_flow_item__name')
    
    def get_queryset(self):
        """Фильтрация с возможностью фильтра по бюджету"""
        queryset = self.filter_soft_deleted(
            self.queryset.select_related('wallet', 'cash_flow_item')
        ).order_by('-date')

        if getattr(self, 'action', None) != 'list':
            return queryset

        filters = self.get_list_filters()
        queryset = self.apply_search_filter(queryset, filters.get('search'))

        if filters.get('wallet'):
            queryset = queryset.filter(wallet_id=filters['wallet'])
        if filters.get('cash_flow_item'):
            queryset = queryset.filter(cash_flow_item_id=filters['cash_flow_item'])
        if filters.get('date_from'):
            queryset = queryset.filter(date__date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(date__date__lte=filters['date_to'])
        if filters.get('amount_min') is not None:
            queryset = queryset.filter(amount__gte=filters['amount_min'])
        if filters.get('amount_max') is not None:
            queryset = queryset.filter(amount__lte=filters['amount_max'])
        
        # Фильтр по включению в бюджет
        include_in_budget = filters.get('include_in_budget')
        if include_in_budget is not None:
            queryset = queryset.filter(include_in_budget=include_in_budget)
            
        return queryset

    @extend_schema(
        parameters=[ExpenditureListQuerySerializer],
        responses={200: ExpenditureSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров"""
        instance.deleted = True
        instance.save()

    def validate_graphic_replacement(self, document, rows):
        """Атомарно заменяет весь график бюджетного распределения расхода.

        Для расходов график считается корректировкой бюджетного распределения,
        а не новым источником суммы документа, поэтому шапка не пересчитывается.
        """
        error = document.get_distribution_validation_error(
            graphic_amounts=[row['amount'] for row in rows]
        )
        if error:
            raise serializers.ValidationError(error)


class TransferViewSet(OneCSyncSoftDeleteCompatibilityMixin, FinancialOperationListFilteringMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления переводами между кошельками
    
    Поддерживает валидацию кошельков и автообновление регистров.
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """
    queryset = Transfer.objects.all()
    serializer_class = TransferSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = TransferGraphic
    graphic_serializer_class = TransferGraphicSerializer
    pagination_class = CatalogPageNumberPagination
    list_query_serializer_class = TransferListQuerySerializer
    search_fields = ('comment', 'number', 'wallet_out__name', 'wallet_in__name')
    
    def get_queryset(self):
        """Фильтрация неудаленных переводов"""
        queryset = self.filter_soft_deleted(
            self.queryset.select_related('wallet_out', 'wallet_in')
        ).order_by('-date')

        if getattr(self, 'action', None) != 'list':
            return queryset

        filters = self.get_list_filters()
        queryset = self.apply_search_filter(queryset, filters.get('search'))

        if filters.get('wallet_from'):
            queryset = queryset.filter(wallet_out_id=filters['wallet_from'])
        if filters.get('wallet_to'):
            queryset = queryset.filter(wallet_in_id=filters['wallet_to'])
        if filters.get('date_from'):
            queryset = queryset.filter(date__date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(date__date__lte=filters['date_to'])
        if filters.get('amount_min') is not None:
            queryset = queryset.filter(amount__gte=filters['amount_min'])
        if filters.get('amount_max') is not None:
            queryset = queryset.filter(amount__lte=filters['amount_max'])

        return queryset

    @extend_schema(
        parameters=[TransferListQuerySerializer],
        responses={200: TransferSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_create(self, serializer):
        """Валидация при создании перевода"""
        wallet_in = serializer.validated_data.get('wallet_in')
        wallet_out = serializer.validated_data.get('wallet_out')
        
        if wallet_in == wallet_out:
            raise serializers.ValidationError(
                "Входящий и исходящий кошелек не могут быть одинаковыми"
            )
        
        serializer.save()
    
    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров"""
        instance.deleted = True
        instance.save()


class PlanningGraphicGenerationMixin:
    """Штатная синхронизация шапки и графика для плановых документов.

    `generate-graphics` обновляет поля шапки, пересоздает строки графика и
    только затем пересобирает регистры. Прямое редактирование строк графика
    допустимо, но рассматривается как точечная корректировка без пересчета шапки.
    """

    graphic_model = None
    graphic_serializer_class = None

    def get_graphic_generation_serializer(self, *args, **kwargs):
        return PlanningGraphicGenerationSerializer(*args, **kwargs)

    @action(detail=True, methods=['post'], url_path='generate-graphics')
    def generate_graphics(self, request, pk=None):
        document = self.get_object()
        payload = self.get_graphic_generation_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        updated_fields = []
        for field_name in ('amount', 'amount_month', 'date_start'):
            if field_name in payload.validated_data:
                setattr(document, field_name, payload.validated_data[field_name])
                updated_fields.append(field_name)

        try:
            rows, updated_amount = document.build_generated_graphic_rows(
                monthly_amount=payload.validated_data.get('monthly_amount'),
                without_rounding=payload.validated_data.get('without_rounding', False),
            )
            document.amount = updated_amount
            if 'amount' not in updated_fields:
                updated_fields.append('amount')
            document.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages)

        with transaction.atomic():
            document.__class__.objects.filter(pk=document.pk).update(
                **{field_name: getattr(document, field_name) for field_name in updated_fields}
            )
            document.items.all().delete()
            self.graphic_model.objects.bulk_create([
                self.graphic_model(
                    document=document,
                    date_start=period,
                    amount=amount,
                )
                for period, amount in rows
            ])
            sync_document_registers(document)

        return Response(
            {
                'document': self.get_serializer(document).data,
                'rows': self.graphic_serializer_class(document.items.order_by('date_start'), many=True).data,
            },
            status=status.HTTP_200_OK,
        )


class BudgetViewSet(OneCSyncSoftDeleteCompatibilityMixin, PlanningGraphicGenerationMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления бюджетами
    
    Поддерживает фильтрацию по типу бюджета (доход/расход).
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """
    queryset = Budget.objects.all()
    serializer_class = BudgetSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = BudgetGraphic
    graphic_serializer_class = BudgetGraphicSerializer
    
    def get_queryset(self):
        """Фильтрация с возможностью фильтра по типу"""
        queryset = self.filter_soft_deleted(self.queryset).order_by('-date')
        
        # Фильтр по типу бюджета
        budget_type = self.request.query_params.get('type')
        if budget_type == 'income':
            queryset = queryset.filter(type_of_budget=True)
        elif budget_type == 'expense':
            queryset = queryset.filter(type_of_budget=False)
            
        return queryset

    @extend_schema(
        parameters=[BudgetListQuerySerializer],
        responses={200: BudgetSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров"""
        instance.deleted = True
        instance.save()

class AutoPaymentViewSet(OneCSyncSoftDeleteCompatibilityMixin, PlanningGraphicGenerationMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления автоматическими платежами
    
    Поддерживает фильтрацию по типу (transfer/payment).
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """
    queryset = AutoPayment.objects.all()
    serializer_class = AutoPaymentSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = AutoPaymentGraphic
    graphic_serializer_class = AutoPaymentGraphicSerializer
    
    def get_queryset(self):
        """Фильтрация с возможностью фильтра по типу"""
        queryset = self.filter_soft_deleted(self.queryset).order_by('-date')
        
        # Фильтр по типу автоплатежа
        is_transfer = self.request.query_params.get('is_transfer')
        if is_transfer is not None:
            queryset = queryset.filter(is_transfer=is_transfer.lower() == 'true')
            
        return queryset

    @extend_schema(
        parameters=[AutoPaymentListQuerySerializer],
        responses={200: AutoPaymentSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
    
    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров"""
        instance.deleted = True
        instance.save()


# Графики планирования
class GraphicRegisterSyncMixin:
    """Пересобирает регистры родительского документа после изменения строк графика.

    Прямое редактирование строк графика не пересчитывает шапку документа.
    """

    def sync_parent_documents(self, *documents):
        seen_documents = {}
        for document in documents:
            if document is None:
                continue
            seen_documents[document.pk] = document

        for document in seen_documents.values():
            sync_document_registers(document)

    def perform_create(self, serializer):
        instance = serializer.save()
        self.sync_parent_documents(instance.document)

    def perform_update(self, serializer):
        previous_document = serializer.instance.document
        instance = serializer.save()
        self.sync_parent_documents(previous_document, instance.document)

    def perform_destroy(self, instance):
        document = instance.document
        instance.delete()
        self.sync_parent_documents(document)


class ExpenditureGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """
    API для управления графиками планирования расходов

    Изменение строки графика пересобирает бюджетные регистры родительского расхода,
    но не пересчитывает сумму в шапке документа. Для полной замены графика
    штатным способом считается `PUT /expenditures/{id}/replace-graphics/`.
    """
    queryset = ExpenditureGraphic.objects.all()
    serializer_class = ExpenditureGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]  # Ограничиваем редактирование
    
    def get_queryset(self):
        """Фильтрация по документу"""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')

    def perform_destroy(self, instance):
        error = instance.document.get_distribution_validation_error(
            graphic_amounts=instance.document.items.exclude(pk=instance.pk).values_list('amount', flat=True)
        )
        if error:
            raise serializers.ValidationError(error)
        super().perform_destroy(instance)


class TransferGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """API для управления графиками планирования переводов"""
    queryset = TransferGraphic.objects.all()
    serializer_class = TransferGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        """Фильтрация по документу"""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')


class BudgetGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """API для управления графиками планирования бюджетов"""
    queryset = BudgetGraphic.objects.all()
    serializer_class = BudgetGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        """Фильтрация по документу"""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')


class AutoPaymentGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """API для управления графиками планирования автоплатежей"""
    queryset = AutoPaymentGraphic.objects.all()
    serializer_class = AutoPaymentGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]
    
    def get_queryset(self):
        """Фильтрация по документу"""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')


class OneCSyncOutboxViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAdminUser]

    def _validated_query(self, request):
        serializer = OneCSyncOutboxQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _build_queryset(self, validated_query):
        queryset = OneCSyncOutbox.objects.all().order_by('changed_at', 'id')
        entity_type = validated_query.get('entity_type')
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)
        return queryset

    @extend_schema(
        parameters=[OneCSyncOutboxQuerySerializer],
        responses={200: OneCSyncOutboxListResponseSerializer},
    )
    def list(self, request):
        validated_query = self._validated_query(request)
        queryset = self._build_queryset(validated_query)
        serializer = OneCSyncOutboxSerializer(queryset[:validated_query['limit']], many=True)
        return Response({
            'count': queryset.count(),
            'results': serializer.data,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        request=OneCSyncOutboxAckRequestSerializer,
        responses={200: OneCSyncOutboxAckResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='ack')
    def ack(self, request):
        serializer = OneCSyncOutboxAckRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        deleted_count, _ = OneCSyncOutbox.objects.filter(
            id__in=serializer.validated_data['ids'],
        ).delete()

        return Response({'deleted_count': deleted_count}, status=status.HTTP_200_OK)


class AiAssistantViewSet(viewsets.ViewSet):
    operation_service_class = AiOperationService
    serializer_class = AiAssistantExecuteSerializer

    def get_permissions(self):
        if getattr(self, 'action', None) == 'telegram_webhook':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_operation_service(self):
        return self.operation_service_class()

    def get_serializer_class(self):
        if getattr(self, 'action', None) == 'telegram_webhook':
            return AiAssistantTelegramWebhookSerializer
        if getattr(self, 'action', None) == 'telegram_link_token':
            return TelegramLinkTokenResponseSerializer
        return self.serializer_class

    def _normalize_duplicate_text(self, text):
        if not text:
            return ''
        return re.sub(r'\s+', ' ', text.strip().lower().replace('ё', 'е'))

    def _build_input_fingerprint(self, *, source, actor_key, text, image_bytes, wallet_id=None):
        payload = {
            'source': source,
            'actor_key': actor_key,
            'text': self._normalize_duplicate_text(text),
            'image_sha256': hashlib.sha256(image_bytes).hexdigest() if image_bytes else '',
            'wallet_id': str(wallet_id) if wallet_id else '',
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest(), payload['text'], payload['image_sha256']

    def _serialize_ai_result_for_storage(self, result):
        payload = dict(result)
        parsed = payload.get('parsed')
        if isinstance(parsed, dict):
            payload['parsed'] = self._serialize_result_parsed_payload(parsed)
        return payload

    def _serialize_result_parsed_payload(self, parsed):
        if not isinstance(parsed, dict):
            return {}
        if 'wallet_id' in parsed:
            return parsed

        normalized_keys = {
            'intent',
            'confidence',
            'amount',
            'wallet',
            'wallet_from',
            'wallet_to',
            'cash_flow_item',
            'comment',
            'include_in_budget',
            'occurred_at',
            'operation_sign',
            'raw',
        }
        if any(key in parsed for key in normalized_keys):
            return self.get_operation_service().serialize_normalized(parsed)

        return parsed

    def _build_response_payload(self, result):
        return self._serialize_ai_result_for_storage(result)

    def _load_duplicate_result(self, processed_input):
        return self._load_processed_result(processed_input, annotate_duplicate=True)

    def _load_processed_result(self, processed_input, *, annotate_duplicate):
        payload = dict(processed_input.response_payload)
        if annotate_duplicate:
            payload['status'] = 'duplicate'
            if payload.get('reply_text'):
                payload['reply_text'] = f'Повторный ввод обнаружен. {payload["reply_text"]}'
            else:
                payload['reply_text'] = 'Повторный ввод обнаружен.'
        return payload

    def _semantic_fingerprint_from_result(self, result):
        parsed = result.get('parsed') or {}
        wallet = parsed.get('wallet')
        wallet_from = parsed.get('wallet_from')
        wallet_to = parsed.get('wallet_to')
        cash_flow_item = parsed.get('cash_flow_item')
        payload = {
            'intent': result.get('intent'),
            'amount': str(parsed.get('amount') or ''),
            'wallet_id': str(getattr(wallet, 'id', '')) if wallet else '',
            'wallet_from_id': str(getattr(wallet_from, 'id', '')) if wallet_from else '',
            'wallet_to_id': str(getattr(wallet_to, 'id', '')) if wallet_to else '',
            'cash_flow_item_id': str(getattr(cash_flow_item, 'id', '')) if cash_flow_item else '',
            'occurred_at_minute': (
                parsed['occurred_at'].replace(second=0, microsecond=0).isoformat()
                if parsed.get('occurred_at') else ''
            ),
            'comment': self._normalize_duplicate_text(parsed.get('comment', ''))[:120],
        }
        if not any(payload.values()):
            return ''
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest()

    def _recent_duplicate(self, *, source, fingerprint, user=None, telegram_binding=None):
        threshold = timezone.now() - timedelta(
            seconds=getattr(settings, 'AI_DUPLICATE_WINDOW_SECONDS', 600)
        )
        queryset = AiProcessedInput.objects.filter(
            source=source,
            fingerprint=fingerprint,
            created_at__gte=threshold,
        ).order_by('-created_at')

        if user is not None:
            queryset = queryset.filter(user=user)
        if telegram_binding is not None:
            queryset = queryset.filter(telegram_binding=telegram_binding)
        return queryset.first()

    def _recent_semantic_duplicate(self, *, source, semantic_fingerprint, user=None, telegram_binding=None):
        if not semantic_fingerprint:
            return None
        threshold = timezone.now() - timedelta(
            seconds=getattr(settings, 'AI_DUPLICATE_WINDOW_SECONDS', 600)
        )
        queryset = AiProcessedInput.objects.filter(
            source=source,
            semantic_fingerprint=semantic_fingerprint,
            created_at__gte=threshold,
        ).order_by('-created_at')
        if user is not None:
            queryset = queryset.filter(user=user)
        if telegram_binding is not None:
            queryset = queryset.filter(telegram_binding=telegram_binding)
        return queryset.first()

    def _store_processed_input(
        self,
        *,
        source,
        fingerprint,
        normalized_text,
        image_sha256,
        wallet_id_hint,
        result,
        user=None,
        telegram_binding=None,
        telegram_update_id=None,
    ):
        if result.get('status') != 'created':
            return

        semantic_fingerprint = self._semantic_fingerprint_from_result(result)
        AiProcessedInput.objects.create(
            source=source,
            user=user,
            telegram_binding=telegram_binding,
            telegram_update_id=telegram_update_id,
            fingerprint=fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=wallet_id_hint,
            status=AiProcessedInput.STATUS_CREATED,
            response_payload=self._serialize_ai_result_for_storage(result),
        )

    def _create_audit_log(
        self,
        *,
        source,
        result,
        input_text='',
        image_sha256='',
        user=None,
        telegram_binding=None,
        processed_input=None,
        pending_confirmation=None,
        confirmed_fields=None,
    ):
        parsed = result.get('parsed') or {}
        normalized_payload = self._serialize_result_parsed_payload(parsed)
        AiAuditLog.objects.create(
            source=source,
            user=user,
            telegram_binding=telegram_binding,
            processed_input=processed_input,
            pending_confirmation=pending_confirmation,
            provider=result.get('provider', ''),
            input_text=input_text or '',
            image_sha256=image_sha256 or '',
            raw_provider_payload=parsed.get('raw', {}) if isinstance(parsed, dict) else {},
            normalized_payload=normalized_payload,
            final_response_payload=self._serialize_ai_result_for_storage(result),
            confirmed_fields=confirmed_fields or [],
        )

    def _telegram_sender(self, message):
        sender = message.get('from') or {}
        chat = message.get('chat') or {}
        return {
            'telegram_user_id': sender.get('id'),
            'telegram_chat_id': chat.get('id'),
            'telegram_username': sender.get('username') or '',
            'first_name': sender.get('first_name') or '',
            'last_name': sender.get('last_name') or '',
        }

    def _resolve_telegram_binding(self, message):
        sender = self._telegram_sender(message)
        if not sender['telegram_user_id'] or not sender['telegram_chat_id']:
            return None

        binding, _ = TelegramUserBinding.objects.get_or_create(
            telegram_user_id=sender['telegram_user_id'],
            defaults={
                'telegram_chat_id': sender['telegram_chat_id'],
                'telegram_username': sender['telegram_username'],
                'first_name': sender['first_name'],
                'last_name': sender['last_name'],
            },
        )
        binding.telegram_chat_id = sender['telegram_chat_id']
        binding.telegram_username = sender['telegram_username']
        binding.first_name = sender['first_name']
        binding.last_name = sender['last_name']

        if binding.user_id is None and binding.telegram_username:
            matched_user = get_user_model().objects.filter(
                username=binding.telegram_username,
                is_active=True,
            ).first()
            if matched_user:
                binding.user = matched_user
                binding.linked_at = timezone.now()

        binding.save()
        return binding

    def _largest_telegram_photo(self, message):
        photos = message.get('photo') or []
        if not photos:
            return None
        return max(
            photos,
            key=lambda item: (item.get('file_size') or 0, item.get('width') or 0, item.get('height') or 0),
        )

    def _telegram_audio_attachment(self, message):
        return message.get('voice') or message.get('audio')

    def _telegram_bot_api_url(self, path, *, query=None, file_download=False):
        token = getattr(settings, 'AI_TELEGRAM_BOT_TOKEN', '')
        if not token:
            raise ValueError('AI_TELEGRAM_BOT_TOKEN is not configured.')

        base_url = getattr(settings, 'AI_TELEGRAM_API_BASE_URL', 'https://api.telegram.org').rstrip('/')
        if file_download:
            url = f'{base_url}/file/bot{token}/{path.lstrip("/")}'
        else:
            url = f'{base_url}/bot{token}/{path.lstrip("/")}'
            if query:
                url = f'{url}?{urlparse.urlencode(query)}'
        return url

    def _download_telegram_file(self, *, file_id):
        if not file_id:
            return None, None, None, None

        file_request = urlrequest.Request(
            self._telegram_bot_api_url('getFile', query={'file_id': file_id}),
            method='GET',
        )
        try:
            with urlrequest.urlopen(file_request, timeout=20) as response:
                file_meta = json.loads(response.read().decode('utf-8'))
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'Telegram getFile failed: {error_body or exc.reason}') from exc
        except urlerror.URLError as exc:
            raise ValueError(f'Telegram getFile failed: {exc.reason}') from exc

        file_result = (file_meta or {}).get('result') or {}
        file_path = file_result.get('file_path')
        if not file_path:
            raise ValueError('Telegram getFile response does not contain file_path.')

        download_request = urlrequest.Request(
            self._telegram_bot_api_url(file_path, file_download=True),
            method='GET',
        )
        try:
            with urlrequest.urlopen(download_request, timeout=20) as response:
                image_bytes = response.read()
                content_type = response.headers.get_content_type() if response.headers else None
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'Telegram file download failed: {error_body or exc.reason}') from exc
        except urlerror.URLError as exc:
            raise ValueError(f'Telegram file download failed: {exc.reason}') from exc

        guessed_content_type, _ = mimetypes.guess_type(file_path)
        resolved_content_type = content_type if content_type and content_type != 'application/octet-stream' else guessed_content_type
        return image_bytes, resolved_content_type or 'application/octet-stream', file_path, file_result.get('file_size')

    def _download_telegram_photo(self, message):
        photo = self._largest_telegram_photo(message)
        if photo is None:
            return None, None

        image_bytes, content_type, _, _ = self._download_telegram_file(file_id=photo.get('file_id'))
        return image_bytes, content_type or 'image/jpeg'

    def _download_telegram_audio(self, message):
        attachment = self._telegram_audio_attachment(message)
        if attachment is None:
            return None, None, None

        file_size = attachment.get('file_size') or 0
        if file_size and file_size > 20 * 1024 * 1024:
            raise ValueError('Telegram не позволяет скачать аудиофайл больше 20 MB через стандартный Bot API.')

        audio_bytes, content_type, file_path, _ = self._download_telegram_file(file_id=attachment.get('file_id'))
        file_name = attachment.get('file_name')
        if not file_name and file_path:
            file_name = file_path.rsplit('/', 1)[-1]
        return audio_bytes, content_type or attachment.get('mime_type') or 'audio/ogg', file_name

    def _build_telegram_photo_error_response(self, error_message):
        return {
            'status': 'needs_confirmation',
            'intent': 'unknown',
            'provider': 'telegram',
            'confidence': 0.0,
            'reply_text': error_message,
            'missing_fields': ['image'],
            'parsed': {'source': 'telegram'},
        }

    def _build_telegram_audio_error_response(self, error_message):
        return {
            'status': 'needs_confirmation',
            'intent': 'unknown',
            'provider': 'telegram',
            'confidence': 0.0,
            'reply_text': error_message,
            'missing_fields': ['audio'],
            'parsed': {'source': 'telegram'},
        }

    def _send_telegram_reply(self, *, binding=None, message=None, result=None):
        if not result:
            return
        reply_text = result.get('reply_text')
        if not reply_text:
            return
        if not getattr(settings, 'AI_TELEGRAM_BOT_TOKEN', ''):
            return

        chat_id = getattr(binding, 'telegram_chat_id', None) if binding is not None else None
        if chat_id is None and message:
            chat_id = (message.get('chat') or {}).get('id')
        if chat_id is None:
            return

        payload = {
            'chat_id': chat_id,
            'text': reply_text,
        }
        message_id = (message or {}).get('message_id')
        if message_id is not None:
            payload['reply_to_message_id'] = message_id

        send_request = urlrequest.Request(
            self._telegram_bot_api_url('sendMessage'),
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urlrequest.urlopen(send_request, timeout=20) as response:
                raw = json.loads(response.read().decode('utf-8'))
        except urlerror.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'Telegram sendMessage failed: {error_body or exc.reason}') from exc
        except urlerror.URLError as exc:
            raise ValueError(f'Telegram sendMessage failed: {exc.reason}') from exc

        if not raw.get('ok', False):
            raise ValueError('Telegram sendMessage response is not ok.')

    def _telegram_response(self, *, binding=None, message=None, result=None, http_status=status.HTTP_200_OK):
        self._send_telegram_reply(binding=binding, message=message, result=result)
        return Response(self._build_response_payload(result), status=http_status)

    def _build_unbound_response(self):
        return {
            'status': 'needs_confirmation',
            'intent': 'unknown',
            'provider': 'telegram',
            'confidence': 0.0,
            'reply_text': (
                'Telegram аккаунт пока не привязан. '
                'Сгенерируйте код в web API и отправьте в бота команду /link CODE.'
            ),
            'missing_fields': ['binding'],
            'parsed': {'source': 'telegram'},
        }

    def _build_telegram_help_response(self, *, binding):
        include_link_hint = binding is None or binding.user_id is None
        return self.get_operation_service().build_help_result(
            provider_name='telegram',
            source='telegram',
            include_telegram_link_hint=include_link_hint,
        )

    def _handle_telegram_link_command(self, *, binding, text):
        parts = (text or '').strip().split(maxsplit=1)
        if len(parts) != 2:
            return {
                'status': 'needs_confirmation',
                'intent': 'unknown',
                'provider': 'telegram',
                'confidence': 1.0,
                'reply_text': 'Используйте формат /link CODE.',
                'missing_fields': ['binding'],
                'parsed': {'source': 'telegram'},
            }

        code = parts[1].strip().upper()
        token = TelegramLinkToken.objects.filter(
            code=code,
            is_used=False,
            expires_at__gte=timezone.now(),
        ).select_related('user').first()
        if token is None:
            return {
                'status': 'needs_confirmation',
                'intent': 'unknown',
                'provider': 'telegram',
                'confidence': 1.0,
                'reply_text': 'Код привязки не найден или просрочен.',
                'missing_fields': ['binding'],
                'parsed': {'source': 'telegram'},
            }

        binding.user = token.user
        binding.linked_at = timezone.now()
        binding.save(update_fields=['user', 'linked_at', 'updated_at', 'telegram_chat_id', 'telegram_username', 'first_name', 'last_name'])

        token.is_used = True
        token.used_by_binding = binding
        token.save(update_fields=['is_used', 'used_by_binding'])
        return {
            'status': 'created',
            'intent': 'link_telegram',
            'provider': 'telegram',
            'confidence': 1.0,
            'reply_text': f'Telegram привязан к пользователю {binding.user.username}.',
            'parsed': {'source': 'telegram'},
            'created_object': {
                'model': 'TelegramUserBinding',
                'id': str(binding.id),
                'number': code,
            },
        }

    def _handle_telegram_unlink_command(self, *, binding):
        if binding.user_id is None:
            return self._build_unbound_response()
        username = binding.user.username
        binding.user = None
        binding.linked_at = None
        binding.save(update_fields=['user', 'linked_at', 'updated_at'])
        AiPendingConfirmation.objects.filter(telegram_binding=binding, is_active=True).update(is_active=False)
        return {
            'status': 'created',
            'intent': 'unlink_telegram',
            'provider': 'telegram',
            'confidence': 1.0,
            'reply_text': f'Telegram отвязан от пользователя {username}.',
            'parsed': {'source': 'telegram'},
            'created_object': {
                'model': 'TelegramUserBinding',
                'id': str(binding.id),
                'number': 'UNLINK',
            },
        }

    def _looks_like_new_command(self, text):
        normalized_text = (text or '').strip().lower()
        command_prefixes = (
            'приход',
            'доход',
            'расход',
            'трата',
            'перевод',
            'остаток',
            'остатки',
            'баланс',
            'балансы',
            '/start',
            '/bind',
            '/link',
            '/unlink',
            '/cancel',
        )
        return normalized_text.startswith(command_prefixes)

    def _upsert_pending_confirmation(self, *, binding, result):
        if result.get('status') != 'needs_confirmation':
            return

        missing_fields = result.get('missing_fields') or []
        if not missing_fields or any(field in {'intent', 'binding'} for field in missing_fields):
            return

        AiPendingConfirmation.objects.filter(
            telegram_binding=binding,
            is_active=True,
        ).update(is_active=False)

        AiPendingConfirmation.objects.create(
            source=AiPendingConfirmation.SOURCE_TELEGRAM,
            user=binding.user,
            telegram_binding=binding,
            intent=result.get('intent') or 'unknown',
            provider=result.get('provider', ''),
            normalized_payload=self._serialize_result_parsed_payload(result['parsed']),
            missing_fields=missing_fields,
            options_payload=result.get('options') or {},
            prompt_text=result.get('reply_text', ''),
        )

    def _close_pending_confirmation(self, pending):
        if pending and pending.is_active:
            pending.is_active = False
            pending.save(update_fields=['is_active', 'updated_at'])

    @extend_schema(
        request=AiAssistantExecuteSerializer,
        responses={200: AiAssistantResponseSerializer, 201: AiAssistantResponseSerializer},
        description=(
            'AI-ввод операции или запроса на остаток. '
            'Поддерживает текст и изображение. '
            'Используется как backend для web-клиента.'
        ),
    )
    @action(detail=False, methods=['post'], url_path='execute')
    def execute(self, request):
        payload = AiAssistantExecuteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        image = payload.validated_data.get('image')
        image_bytes = image.read() if image else None
        wallet_id = payload.validated_data.get('wallet')
        fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
            source='web',
            actor_key=f'user:{request.user.pk}',
            text=payload.validated_data.get('text'),
            image_bytes=image_bytes,
            wallet_id=wallet_id,
        )
        duplicate = self._recent_duplicate(
            source='web',
            fingerprint=fingerprint,
            user=request.user,
        )
        if duplicate:
            return Response(self._build_response_payload(self._load_duplicate_result(duplicate)), status=status.HTTP_200_OK)

        requested_dry_run = payload.validated_data.get('dry_run', False)
        result = self.get_operation_service().process(
            text=payload.validated_data.get('text'),
            image_bytes=image_bytes,
            image_mime_type=getattr(image, 'content_type', None) if image else None,
            wallet_id=wallet_id,
            dry_run=True,
            source='web',
        )
        if result.get('status') == 'preview' and not requested_dry_run:
            semantic_duplicate = self._recent_semantic_duplicate(
                source='web',
                semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                user=request.user,
            )
            if semantic_duplicate:
                duplicate_result = self._load_duplicate_result(semantic_duplicate)
                self._create_audit_log(
                    source='web',
                    result=duplicate_result,
                    input_text=payload.validated_data.get('text') or '',
                    image_sha256=image_sha256,
                    user=request.user,
                    processed_input=semantic_duplicate,
                )
                return Response(self._build_response_payload(duplicate_result), status=status.HTTP_200_OK)
            result = self.get_operation_service().create_from_normalized(
                normalized=result['parsed'],
                provider_name=result['provider'],
            )
        self._store_processed_input(
            source='web',
            fingerprint=fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=wallet_id,
            result=result,
            user=request.user,
        )
        created_input = AiProcessedInput.objects.filter(
            source='web',
            fingerprint=fingerprint,
            user=request.user,
        ).order_by('-created_at').first()
        self._create_audit_log(
            source='web',
            result=result,
            input_text=payload.validated_data.get('text') or '',
            image_sha256=image_sha256,
            user=request.user,
            processed_input=created_input if result.get('status') == 'created' else None,
        )
        http_status = status.HTTP_201_CREATED if result['status'] == 'created' else status.HTTP_200_OK
        return Response(self._build_response_payload(result), status=http_status)

    @extend_schema(
        responses={200: TelegramLinkTokenResponseSerializer},
        description='Сгенерировать одноразовый код привязки Telegram-бота к текущему пользователю.',
    )
    @action(detail=False, methods=['post'], url_path='telegram-link-token')
    def telegram_link_token(self, request):
        TelegramLinkToken.objects.filter(
            user=request.user,
            is_used=False,
            expires_at__lt=timezone.now(),
        ).delete()
        token = TelegramLinkToken.objects.create(
            user=request.user,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        return Response(
            {'code': token.code, 'expires_at': token.expires_at},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=AiAssistantTelegramWebhookSerializer,
        responses={200: AiAssistantResponseSerializer},
        description=(
            'Webhook для Telegram-бота. '
            'Принимает text, caption, photo, voice или audio из update и возвращает нормализованный reply.'
        ),
    )
    @action(detail=False, methods=['post'], url_path='telegram-webhook')
    def telegram_webhook(self, request):
        expected_secret = getattr(settings, 'AI_TELEGRAM_BOT_SECRET', '')
        if expected_secret:
            actual_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
            if actual_secret != expected_secret:
                return Response({'detail': 'Invalid Telegram secret token.'}, status=status.HTTP_403_FORBIDDEN)

        payload = AiAssistantTelegramWebhookSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        update_id = payload.validated_data.get('update_id')
        message = payload.validated_data.get('message') or payload.validated_data.get('edited_message') or {}
        binding = self._resolve_telegram_binding(message)
        text = message.get('text') or message.get('caption')
        has_photo = bool(message.get('photo'))
        has_audio = bool(self._telegram_audio_attachment(message))
        effective_text = text
        audio_bytes = None
        audio_mime_type = None
        audio_file_name = None

        if text and self.get_operation_service().detect_meta_intent(text):
            result = self._build_telegram_help_response(binding=binding)
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=text,
                user=binding.user if binding and binding.user_id else None,
                telegram_binding=binding,
            )
            return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        if binding and text and text.strip().lower().startswith('/link'):
            result = self._handle_telegram_link_command(binding=binding, text=text)
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=text,
                user=binding.user,
                telegram_binding=binding,
            )
            return self._telegram_response(
                binding=binding,
                message=message,
                result=result,
                http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
            )

        if binding and text and text.strip().lower().startswith('/unlink'):
            result = self._handle_telegram_unlink_command(binding=binding)
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=text,
                user=binding.user,
                telegram_binding=binding,
            )
            return self._telegram_response(
                binding=binding,
                message=message,
                result=result,
                http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
            )

        if binding is None or binding.user_id is None:
            result = self._build_unbound_response()
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=effective_text or '',
                telegram_binding=binding,
            )
            return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        pending = AiPendingConfirmation.objects.filter(
            telegram_binding=binding,
            is_active=True,
        ).order_by('-updated_at').first()

        existing_update = None
        if update_id is not None:
            existing_update = AiProcessedInput.objects.filter(
                source='telegram',
                telegram_binding=binding,
                telegram_update_id=update_id,
            ).order_by('-created_at').first()
            if existing_update:
                duplicate_result = self._load_processed_result(existing_update, annotate_duplicate=False)
                self._create_audit_log(
                    source='telegram',
                    result=duplicate_result,
                    input_text=effective_text or '',
                    user=binding.user,
                    telegram_binding=binding,
                    processed_input=existing_update,
                )
                return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)

        image_bytes = None
        image_mime_type = None
        if has_photo:
            try:
                image_bytes, image_mime_type = self._download_telegram_photo(message)
            except ValueError as exc:
                result = self._build_telegram_photo_error_response(str(exc))
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=text or '',
                    user=binding.user,
                    telegram_binding=binding,
                )
                return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        if has_audio:
            try:
                audio_bytes, audio_mime_type, audio_file_name = self._download_telegram_audio(message)
                transcript_text = self.get_operation_service().transcribe_audio(
                    audio_bytes=audio_bytes,
                    audio_mime_type=audio_mime_type,
                    file_name=audio_file_name,
                )
            except ValueError as exc:
                result = self._build_telegram_audio_error_response(str(exc))
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=text or '',
                    user=binding.user,
                    telegram_binding=binding,
                )
                return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

            effective_text = (
                f'{text.strip()}\n{transcript_text}'
                if text and text.strip()
                else transcript_text
            )
            if self.get_operation_service().detect_meta_intent(effective_text):
                result = self._build_telegram_help_response(binding=binding)
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=effective_text,
                    user=binding.user,
                    telegram_binding=binding,
                )
                return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        if text and text.strip().lower() == '/cancel':
            self._close_pending_confirmation(pending)
            result = {
                'status': 'created',
                'intent': 'cancel_confirmation',
                'provider': 'telegram',
                'confidence': 1.0,
                'reply_text': 'Текущая незавершенная команда отменена.',
                'parsed': {'source': 'telegram'},
                'created_object': {
                    'model': 'AiPendingConfirmation',
                    'id': str(pending.id) if pending else str(binding.id),
                    'number': 'CANCEL',
                },
            }
            self._create_audit_log(
                source='telegram',
                result=result,
                input_text=effective_text or text,
                user=binding.user,
                telegram_binding=binding,
                pending_confirmation=pending,
            )
            return self._telegram_response(binding=binding, message=message, result=result, http_status=status.HTTP_200_OK)

        is_new_command = has_photo or self._looks_like_new_command(effective_text)

        if pending and not is_new_command:
            result = self.get_operation_service().continue_confirmation(
                normalized_payload=pending.normalized_payload,
                missing_fields=pending.missing_fields,
                answer_text=effective_text,
                provider_name=pending.provider or 'telegram-confirmation',
                dry_run=True,
                options_payload=pending.options_payload,
            )
            pending.confirmation_history = list(pending.confirmation_history) + [{'answer_text': effective_text}]
            if result.get('status') == 'needs_confirmation':
                pending.normalized_payload = self._serialize_result_parsed_payload(result['parsed'])
                pending.missing_fields = result.get('missing_fields') or []
                pending.options_payload = result.get('options') or {}
                pending.prompt_text = result.get('reply_text', '')
                pending.save(update_fields=['normalized_payload', 'missing_fields', 'options_payload', 'prompt_text', 'confirmation_history', 'updated_at'])
            else:
                semantic_duplicate = self._recent_semantic_duplicate(
                    source='telegram',
                    semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                    user=binding.user,
                    telegram_binding=binding,
                )
                if semantic_duplicate:
                    duplicate_result = self._load_duplicate_result(semantic_duplicate)
                    self._create_audit_log(
                        source='telegram',
                        result=duplicate_result,
                        input_text=effective_text,
                        user=binding.user,
                        telegram_binding=binding,
                        processed_input=semantic_duplicate,
                        pending_confirmation=pending,
                        confirmed_fields=pending.missing_fields,
                    )
                    self._close_pending_confirmation(pending)
                    return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)
                result = self.get_operation_service().create_from_normalized(
                    normalized=result['parsed'],
                    provider_name=result['provider'],
                )
                self._close_pending_confirmation(pending)
                fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
                    source='telegram',
                    actor_key=f'tg:{binding.telegram_user_id}',
                    text=effective_text,
                    image_bytes=audio_bytes,
                )
                duplicate = self._recent_duplicate(
                    source='telegram',
                    fingerprint=fingerprint,
                    user=binding.user,
                    telegram_binding=binding,
                )
                if duplicate:
                    return self._telegram_response(
                        binding=binding,
                        message=message,
                        result=self._load_duplicate_result(duplicate),
                        http_status=status.HTTP_200_OK,
                    )
                self._store_processed_input(
                    source='telegram',
                    fingerprint=fingerprint,
                    normalized_text=normalized_text,
                    image_sha256=image_sha256,
                    wallet_id_hint=None,
                    result=result,
                    user=binding.user,
                    telegram_binding=binding,
                    telegram_update_id=update_id,
                )
                created_input = AiProcessedInput.objects.filter(
                    source='telegram',
                    fingerprint=fingerprint,
                    telegram_binding=binding,
                ).order_by('-created_at').first()
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=effective_text,
                    image_sha256=image_sha256,
                    user=binding.user,
                    telegram_binding=binding,
                    processed_input=created_input,
                    pending_confirmation=pending,
                    confirmed_fields=pending.missing_fields,
                )
            if result.get('status') == 'needs_confirmation':
                self._create_audit_log(
                    source='telegram',
                    result=result,
                    input_text=effective_text,
                    user=binding.user,
                    telegram_binding=binding,
                    pending_confirmation=pending,
                    confirmed_fields=pending.missing_fields,
                )
            return self._telegram_response(
                binding=binding,
                message=message,
                result=result,
                http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
            )

        if pending and is_new_command:
            self._close_pending_confirmation(pending)

        fingerprint, normalized_text, image_sha256 = self._build_input_fingerprint(
            source='telegram',
            actor_key=f'tg:{binding.telegram_user_id}',
            text=effective_text,
            image_bytes=image_bytes or audio_bytes,
        )
        duplicate = self._recent_duplicate(
            source='telegram',
            fingerprint=fingerprint,
            user=binding.user,
            telegram_binding=binding,
        )
        if duplicate:
            duplicate_result = self._load_duplicate_result(duplicate)
            self._create_audit_log(
                source='telegram',
                result=duplicate_result,
                input_text=effective_text,
                user=binding.user,
                telegram_binding=binding,
                processed_input=duplicate,
            )
            return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)

        result = self.get_operation_service().process(
            text=effective_text,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            dry_run=True,
            source='telegram',
        )
        if result.get('status') == 'preview':
            semantic_duplicate = self._recent_semantic_duplicate(
                source='telegram',
                semantic_fingerprint=self._semantic_fingerprint_from_result(result),
                user=binding.user,
                telegram_binding=binding,
            )
            if semantic_duplicate:
                duplicate_result = self._load_duplicate_result(semantic_duplicate)
                self._create_audit_log(
                    source='telegram',
                    result=duplicate_result,
                    input_text=effective_text,
                    user=binding.user,
                    telegram_binding=binding,
                    processed_input=semantic_duplicate,
                )
                return self._telegram_response(binding=binding, message=message, result=duplicate_result, http_status=status.HTTP_200_OK)
            result = self.get_operation_service().create_from_normalized(
                normalized=result['parsed'],
                provider_name=result['provider'],
            )
        self._upsert_pending_confirmation(binding=binding, result=result)
        self._store_processed_input(
            source='telegram',
            fingerprint=fingerprint,
            normalized_text=normalized_text,
            image_sha256=image_sha256,
            wallet_id_hint=None,
            result=result,
            user=binding.user,
            telegram_binding=binding,
            telegram_update_id=update_id,
        )
        created_input = AiProcessedInput.objects.filter(
            source='telegram',
            fingerprint=fingerprint,
            telegram_binding=binding,
        ).order_by('-created_at').first()
        self._create_audit_log(
            source='telegram',
            result=result,
            input_text=effective_text,
            image_sha256=image_sha256,
            user=binding.user,
            telegram_binding=binding,
            processed_input=created_input,
            pending_confirmation=AiPendingConfirmation.objects.filter(telegram_binding=binding, is_active=True).order_by('-updated_at').first() if result.get('status') == 'needs_confirmation' else None,
        )
        return self._telegram_response(
            binding=binding,
            message=message,
            result=result,
            http_status=status.HTTP_200_OK if result['status'] != 'created' else status.HTTP_201_CREATED,
        )

# Регистры
class FlowOfFundsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра движения средств
    
    Только для чтения. Поддерживает фильтрацию по кошельку, статье, периоду.
    """
    queryset = FlowOfFunds.objects.all()
    serializer_class = FlowOfFundsSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Фильтрация по параметрам запроса"""
        queryset = self.queryset.select_related('wallet', 'cash_flow_item')
        
        # Фильтрация по кошельку
        wallet_id = self.request.query_params.get('wallet')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)
        
        # Фильтрация по статье
        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)
        
        # Фильтрация по периоду (с даты)
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)
        
        # Фильтрация по периоду (до даты)
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)
        
        return queryset.order_by('-period')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по движению средств"""
        queryset = self.get_queryset()
        
        # Сумма по кошелькам
        wallet_summary = queryset.values('wallet__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Сумма по статьям
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_amount': float(total_amount),
            'wallet_summary': list(wallet_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count()
        })


class BudgetIncomeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра доходов бюджета
    
    Только для чтения. Поддерживает фильтрацию по проекту, статье, периоду.
    """
    queryset = BudgetIncome.objects.all()
    serializer_class = BudgetIncomeSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Фильтрация по параметрам запроса"""
        queryset = self.queryset.select_related('project', 'cash_flow_item')
        
        # Фильтрация по проекту
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        # Фильтрация по статье
        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)
        
        # Фильтрация по периоду
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)
        
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)
        
        return queryset.order_by('-period')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по доходам бюджета"""
        queryset = self.get_queryset()
        
        # Сумма по проектам
        project_summary = queryset.values('project__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Сумма по статьям
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_income': float(total_amount),
            'project_summary': list(project_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count()
        })


class BudgetExpenseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра расходов бюджета
    
    Только для чтения. Поддерживает фильтрацию по проекту, статье, периоду.
    """
    queryset = BudgetExpense.objects.all()
    serializer_class = BudgetExpenseSerializer
    permission_classes = [permissions.IsAdminUser]
    
    def get_queryset(self):
        """Фильтрация по параметрам запроса"""
        queryset = self.queryset.select_related('project', 'cash_flow_item')
        
        # Фильтрация по проекту
        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        # Фильтрация по статье
        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)
        
        # Фильтрация по периоду
        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)
        
        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)
        
        return queryset.order_by('-period')
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по расходам бюджета"""
        queryset = self.get_queryset()
        
        # Сумма по проектам
        project_summary = queryset.values('project__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Сумма по статьям
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        
        # Общая сумма
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0
        
        return Response({
            'total_expense': float(total_amount),
            'project_summary': list(project_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count()
        })
    
