from datetime import datetime, time
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .common_views import OneCSyncSoftDeleteCompatibilityMixin
from .models import (
    CashFlowItem,
    Expenditure,
    FlowOfFunds,
    MONEY_QUANTIZER,
    Project,
    Receipt,
    Wallet,
    ZERO_AMOUNT,
)
from .permissions import IsAdminOrReadOnly
from .serializers import (
    CashFlowItemSerializer,
    ProjectSerializer,
    WalletBalanceResponseSerializer,
    WalletBalancesResponseSerializer,
    WalletSerializer,
    WalletSummaryResponseSerializer,
)


TRANSFER_DOCUMENT_TYPE = 2
WALLET_BALANCE_DATE_PARAMETER = OpenApiParameter(
    'date',
    OpenApiTypes.DATETIME,
    OpenApiParameter.QUERY,
    description='Остаток на конец дня YYYY-MM-DD или на указанный ISO datetime. По умолчанию текущий момент.',
)


def _money(value):
    if value is None:
        value = ZERO_AMOUNT
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(MONEY_QUANTIZER)


def _money_str(value):
    return f'{_money(value):.2f}'


def _parse_wallet_balance_as_of(raw_value):
    if not raw_value:
        return None

    raw_text = str(raw_value)
    parsed = parse_datetime(raw_text)
    if parsed is not None:
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    parsed_day = parse_date(raw_text)
    if parsed_day is None:
        return None

    return timezone.make_aware(
        datetime.combine(parsed_day, time.max),
        timezone.get_current_timezone(),
    )


def _serialize_uuid(value):
    return str(value) if value is not None else None


class CashFlowItemViewSet(OneCSyncSoftDeleteCompatibilityMixin, viewsets.ModelViewSet):
    """
    API для управления статьями движения денежных средств.

    Поддерживает иерархическую структуру через поле parent.
    Админы имеют полный доступ, пользователи - только чтение.
    """

    queryset = CashFlowItem.objects.all()
    serializer_class = CashFlowItemSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация неудаленных записей."""
        return self.filter_soft_deleted(self.queryset).annotate(
            usage_count=Count(
                'flowoffunds',
                filter=~Q(flowoffunds__type_of_document=TRANSFER_DOCUMENT_TYPE),
            )
        )

    @action(detail=False, methods=['get'])
    def hierarchy(self, request):
        """Получить иерархическую структуру статей."""
        root_items = self.get_queryset().filter(parent=None)
        serializer = self.get_serializer(root_items, many=True)
        return Response({'hierarchy': serializer.data})

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по статьям движения средств."""
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        flow_queryset = FlowOfFunds.objects.filter(cash_flow_item__isnull=False).exclude(
            type_of_document=TRANSFER_DOCUMENT_TYPE
        )
        if date_from:
            flow_queryset = flow_queryset.filter(period__gte=date_from)
        if date_to:
            flow_queryset = flow_queryset.filter(period__lte=date_to)

        item_summary = flow_queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount'),
            record_count=Count('id'),
        ).order_by('-total_amount')
        total_amount = flow_queryset.aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'total_amount': float(total_amount),
            'item_summary': list(item_summary),
            'period_filter': {
                'date_from': date_from,
                'date_to': date_to,
            },
        })


class WalletViewSet(OneCSyncSoftDeleteCompatibilityMixin, viewsets.ModelViewSet):
    """
    API для управления кошельками.

    Включает фильтрацию скрытых кошельков и статистику.
    """

    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация неудаленных и скрытых кошельков."""
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
                'amount': _money_str(receipt.amount),
                'description': receipt.comment or None,
                '_sort_date': receipt.date,
            })

        for expenditure in expenditure_queryset[:limit]:
            items.append({
                'id': _serialize_uuid(expenditure.id),
                'kind': 'expenditure',
                'date': expenditure.date.isoformat(),
                'amount': _money_str(expenditure.amount),
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
        parameters=[WALLET_BALANCE_DATE_PARAMETER],
        responses={200: WalletBalanceResponseSerializer},
    )
    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        """Получить баланс кошелька на основе регистра движения средств."""
        wallet = self.get_object()

        balance_date = request.query_params.get('date')
        if balance_date:
            as_of = _parse_wallet_balance_as_of(balance_date)
            if as_of is None:
                return Response(
                    {'date': 'Передай дату в формате YYYY-MM-DD или ISO datetime.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            as_of = timezone.now()

        flows = FlowOfFunds.objects.filter(wallet=wallet, period__lte=as_of)
        balance = flows.aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'wallet_id': str(wallet.id),
            'wallet_name': wallet.name,
            'balance': float(balance),
            'currency': 'RUB',
            'as_of': as_of,
            'last_updated': timezone.now(),
        })

    @extend_schema(
        responses={200: WalletSummaryResponseSerializer},
    )
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Компактная сводка по кошельку для быстрой загрузки detail page."""
        wallet = self.get_object()

        balance = _money(
            FlowOfFunds.objects.filter(wallet=wallet).aggregate(total=Sum('amount'))['total']
        )
        income_total = _money(
            Receipt.objects.filter(wallet=wallet, deleted=False).aggregate(total=Sum('amount'))['total']
        )
        expense_total = _money(
            Expenditure.objects.filter(wallet=wallet, deleted=False).aggregate(total=Sum('amount'))['total']
        )

        return Response({
            'wallet_id': str(wallet.id),
            'wallet_name': wallet.name,
            'balance': _money_str(balance),
            'income_total': _money_str(income_total),
            'expense_total': _money_str(expense_total),
            'recent_operations': self._build_wallet_recent_operations(wallet),
        })

    @extend_schema(
        parameters=[WALLET_BALANCE_DATE_PARAMETER],
        responses={200: WalletBalancesResponseSerializer},
    )
    @action(detail=False, methods=['get'])
    def balances(self, request):
        """Получить балансы всех кошельков."""
        wallets = self.get_queryset()
        balance_date = request.query_params.get('date')
        if balance_date:
            as_of = _parse_wallet_balance_as_of(balance_date)
            if as_of is None:
                return Response(
                    {'date': 'Передай дату в формате YYYY-MM-DD или ISO datetime.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            as_of = timezone.now()
        balances = []

        for wallet in wallets:
            balance = (
                FlowOfFunds.objects.filter(wallet=wallet, period__lte=as_of).aggregate(total=Sum('amount'))['total']
                or ZERO_AMOUNT
            )
            balance = _money(balance)
            if balance == ZERO_AMOUNT:
                continue

            balances.append({
                'wallet_id': str(wallet.id),
                'wallet_name': wallet.name,
                'balance': float(balance),
                'currency': 'RUB',
                'as_of': as_of,
            })

        balances.sort(key=lambda x: x['balance'], reverse=True)

        return Response({
            'balances': balances,
            'total_wallets': len(balances),
            'total_balance': sum(b['balance'] for b in balances),
            'as_of': as_of,
        })


class ProjectViewSet(OneCSyncSoftDeleteCompatibilityMixin, viewsets.ModelViewSet):
    """API для управления проектами."""

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация неудаленных проектов."""
        return self.filter_soft_deleted(self.queryset)
