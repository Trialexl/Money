import logging
from datetime import date

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view

from .models import (
    FxRateSnapshot,
    Instrument,
    InstrumentPriceSnapshot,
    InvestmentAccount,
    InvestmentOperation,
    InvestmentPortfolio,
    InvestmentTargetAllocation,
    SUPPORTED_CURRENCIES,
)
from .serializers import (
    FxRateSnapshotSerializer,
    InstrumentSerializer,
    InstrumentPriceSnapshotSerializer,
    InvestmentAccountSerializer,
    InvestmentOperationSerializer,
    InvestmentPerformanceSerializer,
    InvestmentPositionSerializer,
    InvestmentPortfolioOverviewSerializer,
    InvestmentPortfolioSerializer,
    InvestmentRebalanceStatusSerializer,
    InvestmentTargetAllocationSerializer,
    get_default_portfolio,
    serialize_portfolio_overview,
)
from .services import (
    calculate_portfolio_performance,
    calculate_positions,
    calculate_rebalance_status,
    backfill_fx_rate_snapshots,
    backfill_price_snapshots,
    rebuild_portfolio_snapshots_for_change,
    refresh_fx_rate_snapshots,
    refresh_price_snapshots,
)

logger = logging.getLogger(__name__)


instrument_list_parameters = [
    OpenApiParameter('type', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Тип инструмента: crypto или stock.'),
    OpenApiParameter('is_active', OpenApiTypes.BOOL, OpenApiParameter.QUERY, description='Фильтр активности инструмента.'),
    OpenApiParameter('search', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Поиск по тикеру, названию или символу provider.'),
]

price_list_parameters = [
    OpenApiParameter('instrument', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инструмента.'),
    OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата снимка цены с YYYY-MM-DD.'),
    OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата снимка цены по YYYY-MM-DD включительно.'),
    OpenApiParameter('source', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Источник цены, например manual.'),
]

fx_rate_list_parameters = [
    OpenApiParameter('base_currency', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Базовая валюта, например USD.'),
    OpenApiParameter('quote_currency', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Валюта котировки, по умолчанию USD.'),
    OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата снимка курса с YYYY-MM-DD.'),
    OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата снимка курса по YYYY-MM-DD включительно.'),
    OpenApiParameter('source', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Источник курса, например manual или cbr.'),
]

account_list_parameters = [
    OpenApiParameter('portfolio', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инвестиционного портфеля.'),
    OpenApiParameter('hidden', OpenApiTypes.BOOL, OpenApiParameter.QUERY, description='Показать скрытые или видимые счета.'),
]

target_allocation_list_parameters = [
    OpenApiParameter('portfolio', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инвестиционного портфеля.'),
    OpenApiParameter('instrument', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инструмента.'),
]

operation_list_parameters = [
    OpenApiParameter('portfolio', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инвестиционного портфеля.'),
    OpenApiParameter('account', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инвестиционного счета.'),
    OpenApiParameter('instrument', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инструмента.'),
    OpenApiParameter('operation_type', OpenApiTypes.STR, OpenApiParameter.QUERY, description='buy, sell, transfer_instrument или correction.'),
    OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата операции с YYYY-MM-DD.'),
    OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата операции по YYYY-MM-DD включительно.'),
    OpenApiParameter('deleted', OpenApiTypes.BOOL, OpenApiParameter.QUERY, description='Если не передан, по умолчанию скрывает удаленные операции.'),
]

overview_parameters = [
    OpenApiParameter('portfolio', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID портфеля. Если не передан, берется портфель по умолчанию.'),
]

performance_parameters = [
    OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата начала периода YYYY-MM-DD. По умолчанию 1 января текущего года.'),
    OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата окончания периода YYYY-MM-DD. По умолчанию 31 декабря текущего года.'),
    OpenApiParameter('group_by', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Группировка: day или month. По умолчанию month.'),
    OpenApiParameter('display_currency', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Валюта отображения USD/EUR/RUB. По умолчанию USD.'),
    OpenApiParameter('scope', OpenApiTypes.STR, OpenApiParameter.QUERY, description='portfolio, instrument или all. По умолчанию portfolio.'),
    OpenApiParameter('instrument', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инструмента для scope=instrument.'),
]


def _parse_performance_period(request):
    today = date.today()
    date_from_value = request.query_params.get('date_from')
    date_to_value = request.query_params.get('date_to')
    date_from = parse_date(date_from_value) if date_from_value else date(today.year, 1, 1)
    date_to = parse_date(date_to_value) if date_to_value else date(today.year, 12, 31)
    group_by = request.query_params.get('group_by') or 'month'
    display_currency = (request.query_params.get('display_currency') or 'USD').strip().upper()
    scope = (request.query_params.get('scope') or 'portfolio').strip().lower()
    instrument_id = request.query_params.get('instrument') or None
    if date_from is None:
        return None, None, group_by, display_currency, scope, instrument_id, {'date_from': 'Некорректная дата. Используйте YYYY-MM-DD.'}
    if date_to is None:
        return None, None, group_by, display_currency, scope, instrument_id, {'date_to': 'Некорректная дата. Используйте YYYY-MM-DD.'}
    if date_from > date_to:
        return None, None, group_by, display_currency, scope, instrument_id, {'date_to': 'Дата окончания должна быть не раньше даты начала.'}
    if group_by not in {'day', 'month'}:
        return None, None, group_by, display_currency, scope, instrument_id, {'group_by': 'Поддерживаются значения day или month.'}
    if display_currency not in SUPPORTED_CURRENCIES:
        return None, None, group_by, display_currency, scope, instrument_id, {'display_currency': 'Поддерживаются значения USD, EUR или RUB.'}
    if scope not in {'portfolio', 'instrument', 'all'}:
        return None, None, group_by, display_currency, scope, instrument_id, {'scope': 'Поддерживаются значения portfolio, instrument или all.'}
    if scope == 'instrument' and not instrument_id:
        return None, None, group_by, display_currency, scope, instrument_id, {'instrument': 'Для scope=instrument нужен UUID инструмента.'}
    return date_from, date_to, group_by, display_currency, scope, instrument_id, None


def _date_part(value):
    if value is None:
        return None
    return value.date() if hasattr(value, 'date') else value


def _min_date(*values):
    dates = [_date_part(value) for value in values if _date_part(value) is not None]
    return min(dates) if dates else None


def _rebuild_snapshots_after_investment_change(**kwargs):
    try:
        rebuild_portfolio_snapshots_for_change(**kwargs)
    except Exception:
        logger.exception('Failed to rebuild investment portfolio snapshots after data change.')


@extend_schema_view(
    list=extend_schema(
        parameters=instrument_list_parameters,
        description='Список финансовых инструментов. Инвестиционный модуль не синхронизируется с 1С.',
    ),
    create=extend_schema(description='Создать финансовый инструмент.'),
    retrieve=extend_schema(description='Получить финансовый инструмент.'),
    update=extend_schema(description='Полностью обновить финансовый инструмент.'),
    partial_update=extend_schema(description='Частично обновить финансовый инструмент.'),
    destroy=extend_schema(description='Удалить финансовый инструмент, если он не используется операциями.'),
)
class InstrumentViewSet(viewsets.ModelViewSet):
    serializer_class = InstrumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Instrument.objects.all().order_by('type', 'ticker')
    filterset_fields = ['type', 'is_active']
    search_fields = ['ticker', 'name', 'provider_symbol']


@extend_schema_view(
    list=extend_schema(
        parameters=price_list_parameters,
        description='Снимки цен инструментов. Используются для текущей оценки, unrealized P/L и доходности.',
    ),
    create=extend_schema(description='Создать ручной снимок цены инструмента.'),
    retrieve=extend_schema(description='Получить снимок цены инструмента.'),
    update=extend_schema(description='Полностью обновить снимок цены.'),
    partial_update=extend_schema(description='Частично обновить снимок цены.'),
    destroy=extend_schema(description='Удалить снимок цены.'),
)
class InstrumentPriceSnapshotViewSet(viewsets.ModelViewSet):
    serializer_class = InstrumentPriceSnapshotSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            InstrumentPriceSnapshot.objects
            .select_related('instrument')
            .order_by('-captured_at', '-created_at')
        )
        instrument_id = self.request.query_params.get('instrument')
        if instrument_id:
            queryset = queryset.filter(instrument_id=instrument_id)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(captured_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(captured_at__date__lte=date_to)
        source = self.request.query_params.get('source')
        if source:
            queryset = queryset.filter(source=source)
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()
        _rebuild_snapshots_after_investment_change(
            instrument=instance.instrument_id,
            changed_at=instance.captured_at,
        )

    def perform_update(self, serializer):
        previous_instrument_id = serializer.instance.instrument_id
        previous_captured_at = serializer.instance.captured_at
        instance = serializer.save()
        if previous_instrument_id == instance.instrument_id:
            _rebuild_snapshots_after_investment_change(
                instrument=instance.instrument_id,
                date_from=_min_date(previous_captured_at, instance.captured_at),
            )
            return
        _rebuild_snapshots_after_investment_change(
            instrument=previous_instrument_id,
            changed_at=previous_captured_at,
        )
        _rebuild_snapshots_after_investment_change(
            instrument=instance.instrument_id,
            changed_at=instance.captured_at,
        )

    def perform_destroy(self, instance):
        instrument_id = instance.instrument_id
        changed_at = instance.captured_at
        instance.delete()
        _rebuild_snapshots_after_investment_change(
            instrument=instrument_id,
            changed_at=changed_at,
        )

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter('instrument', OpenApiTypes.UUID, OpenApiParameter.QUERY, required=True, description='UUID инструмента.'),
            OpenApiParameter('date', OpenApiTypes.DATE, OpenApiParameter.QUERY, required=True, description='Дата сделки YYYY-MM-DD.'),
        ],
        responses={200: OpenApiTypes.OBJECT},
        description='Подобрать цену инструмента на дату сделки: снимок за дату или ближайший предыдущий.',
    )
    @action(detail=False, methods=['get'])
    def lookup(self, request):
        instrument_id = request.query_params.get('instrument')
        lookup_date_value = request.query_params.get('date')
        lookup_date = parse_date(lookup_date_value) if lookup_date_value else None
        if not instrument_id:
            return Response({'instrument': 'Обязательный параметр.'}, status=status.HTTP_400_BAD_REQUEST)
        if lookup_date is None:
            return Response({'date': 'Некорректная дата. Используйте YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        instrument = Instrument.objects.filter(id=instrument_id).first()
        if instrument is None:
            return Response({'instrument': 'Инструмент не найден.'}, status=status.HTTP_404_NOT_FOUND)

        snapshot = (
            InstrumentPriceSnapshot.objects
            .filter(instrument=instrument, captured_at__date__lte=lookup_date)
            .order_by('-captured_at', '-created_at')
            .first()
        )
        if snapshot is None:
            return Response({
                'found': False,
                'instrument': str(instrument.id),
                'instrument_ticker': instrument.ticker,
                'date': lookup_date.isoformat(),
                'detail': 'Цена на эту дату или раньше не найдена.',
            })

        snapshot_date = snapshot.captured_at.date()
        return Response({
            'found': True,
            'instrument': str(instrument.id),
            'instrument_ticker': instrument.ticker,
            'date': lookup_date.isoformat(),
            'snapshot_id': str(snapshot.id),
            'snapshot_date': snapshot_date.isoformat(),
            'is_exact_date': snapshot_date == lookup_date,
            'stale_days': (lookup_date - snapshot_date).days,
            'price': f'{snapshot.price:.8f}',
            'price_currency': snapshot.price_currency,
            'fx_rate_to_usd': f'{snapshot.fx_rate_to_usd:.8f}',
            'price_usd': f'{snapshot.price_usd:.2f}',
            'source': snapshot.source,
        })

    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        description='Обновить цены активных инструментов через configured price/fx providers. Частичные ошибки возвращаются в results.',
    )
    @action(detail=False, methods=['post'])
    def refresh(self, request):
        return Response(refresh_price_snapshots())

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата начала backfill. По умолчанию 1 января текущего года.'),
            OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата окончания backfill. По умолчанию сегодня.'),
        ],
        responses={200: OpenApiTypes.OBJECT},
        description='Заполнить ежедневные цены активных инструментов за период через configured price provider.',
    )
    @action(detail=False, methods=['post'])
    def backfill(self, request):
        today = date.today()
        payload = request.data if isinstance(request.data, dict) else {}
        date_from_value = request.query_params.get('date_from') or payload.get('date_from')
        date_to_value = request.query_params.get('date_to') or payload.get('date_to')
        date_from = parse_date(date_from_value) if date_from_value else date(today.year, 1, 1)
        date_to = parse_date(date_to_value) if date_to_value else today
        if date_from is None:
            return Response({'date_from': 'Некорректная дата. Используйте YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if date_to is None:
            return Response({'date_to': 'Некорректная дата. Используйте YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if date_from > date_to:
            return Response({'date_to': 'Дата окончания должна быть не раньше даты начала.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(backfill_price_snapshots(date_from=date_from, date_to=date_to))


@extend_schema_view(
    list=extend_schema(
        parameters=fx_rate_list_parameters,
        description='Снимки валютных курсов. Используются для пересчета USD-учета в валюту отображения.',
    ),
    create=extend_schema(description='Создать ручной снимок валютного курса.'),
    retrieve=extend_schema(description='Получить снимок валютного курса.'),
    update=extend_schema(description='Полностью обновить снимок валютного курса.'),
    partial_update=extend_schema(description='Частично обновить снимок валютного курса.'),
    destroy=extend_schema(description='Удалить снимок валютного курса.'),
)
class FxRateSnapshotViewSet(viewsets.ModelViewSet):
    serializer_class = FxRateSnapshotSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = FxRateSnapshot.objects.order_by('-captured_at', '-created_at')
        base_currency = self.request.query_params.get('base_currency')
        if base_currency:
            queryset = queryset.filter(base_currency=base_currency.strip().upper())
        quote_currency = self.request.query_params.get('quote_currency')
        if quote_currency:
            queryset = queryset.filter(quote_currency=quote_currency.strip().upper())
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(captured_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(captured_at__date__lte=date_to)
        source = self.request.query_params.get('source')
        if source:
            queryset = queryset.filter(source=source)
        return queryset

    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        description='Обновить валютные курсы USD/EUR/RUB через configured FX provider.',
    )
    @action(detail=False, methods=['post'])
    def refresh(self, request):
        return Response(refresh_fx_rate_snapshots())

    @extend_schema(
        request=None,
        parameters=[
            OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата начала backfill. По умолчанию 1 января текущего года.'),
            OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата окончания backfill. По умолчанию сегодня.'),
        ],
        responses={200: OpenApiTypes.OBJECT},
        description='Заполнить ежедневные кросс-курсы USD/EUR/RUB за период через configured FX provider.',
    )
    @action(detail=False, methods=['post'])
    def backfill(self, request):
        today = date.today()
        payload = request.data if isinstance(request.data, dict) else {}
        date_from_value = request.query_params.get('date_from') or payload.get('date_from')
        date_to_value = request.query_params.get('date_to') or payload.get('date_to')
        date_from = parse_date(date_from_value) if date_from_value else date(today.year, 1, 1)
        date_to = parse_date(date_to_value) if date_to_value else today
        if date_from is None:
            return Response({'date_from': 'Некорректная дата. Используйте YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if date_to is None:
            return Response({'date_to': 'Некорректная дата. Используйте YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if date_from > date_to:
            return Response({'date_to': 'Дата окончания должна быть не раньше даты начала.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(backfill_fx_rate_snapshots(date_from=date_from, date_to=date_to))


@extend_schema_view(
    list=extend_schema(description='Список инвестиционных портфелей текущего пользователя.'),
    create=extend_schema(description='Создать инвестиционный портфель.'),
    retrieve=extend_schema(description='Получить инвестиционный портфель.'),
    update=extend_schema(description='Полностью обновить инвестиционный портфель.'),
    partial_update=extend_schema(description='Частично обновить инвестиционный портфель.'),
    destroy=extend_schema(description='Удалить инвестиционный портфель, если он не используется.'),
)
class InvestmentPortfolioViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentPortfolioSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = InvestmentPortfolio.objects.select_related('user', 'project').order_by('-is_default', 'name')
        if getattr(self, 'swagger_fake_view', False):
            return queryset.none()
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @extend_schema(
        responses={200: InvestmentPortfolioOverviewSerializer},
        description='Сводка по портфелю: текущая стоимость, себестоимость, realized/unrealized/total P/L, доходность и позиции.',
    )
    @action(detail=True, methods=['get'])
    def overview(self, request, pk=None):
        return Response(serialize_portfolio_overview(self.get_object()))

    @extend_schema(
        parameters=[
            OpenApiParameter('include_zero', OpenApiTypes.BOOL, OpenApiParameter.QUERY, description='Включить нулевые позиции.'),
        ],
        responses={200: InvestmentPositionSerializer(many=True)},
        description='Позиции портфеля по инструментам.',
    )
    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        include_zero = request.query_params.get('include_zero') in ('1', 'true', 'True')
        return Response(calculate_positions(self.get_object(), include_zero=include_zero))

    @extend_schema(
        responses={200: InvestmentRebalanceStatusSerializer},
        description='Текущие отклонения от целевых долей. Не является инвестиционной рекомендацией.',
    )
    @action(detail=True, methods=['get'])
    def rebalance(self, request, pk=None):
        return Response(calculate_rebalance_status(self.get_object()))

    @extend_schema(
        parameters=performance_parameters,
        responses={200: InvestmentPerformanceSerializer},
        description='Динамика стоимости портфеля и P/L. Opening учитывает операции до начала периода.',
    )
    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        date_from, date_to, group_by, display_currency, scope, instrument_id, error = _parse_performance_period(request)
        if error:
            return Response(error, status=400)
        return Response(calculate_portfolio_performance(
            self.get_object(),
            date_from=date_from,
            date_to=date_to,
            group_by=group_by,
            display_currency=display_currency,
            scope=scope,
            instrument_id=instrument_id,
        ))


@extend_schema_view(
    list=extend_schema(
        parameters=account_list_parameters,
        description='Список инвестиционных счетов. Hidden-счета остаются в данных, но могут скрываться в UI.',
    ),
    create=extend_schema(description='Создать инвестиционный счет.'),
    retrieve=extend_schema(description='Получить инвестиционный счет.'),
    update=extend_schema(description='Полностью обновить инвестиционный счет.'),
    partial_update=extend_schema(description='Частично обновить инвестиционный счет.'),
    destroy=extend_schema(description='Удалить инвестиционный счет, если он не используется.'),
)
class InvestmentAccountViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = InvestmentAccount.objects.select_related('portfolio', 'portfolio__user').order_by('name')
        if getattr(self, 'swagger_fake_view', False):
            return queryset.none()
        portfolio_id = self.request.query_params.get('portfolio')
        if portfolio_id:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        if self.request.query_params.get('hidden') in ('true', 'false'):
            queryset = queryset.filter(hidden=self.request.query_params.get('hidden') == 'true')
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(portfolio__user=self.request.user)


@extend_schema_view(
    list=extend_schema(
        parameters=target_allocation_list_parameters,
        description='Целевые доли инструментов для ребалансировки портфеля.',
    ),
    create=extend_schema(description='Создать целевую долю инструмента. Сумма долей портфеля не должна превышать 100%.'),
    retrieve=extend_schema(description='Получить целевую долю.'),
    update=extend_schema(description='Полностью обновить целевую долю.'),
    partial_update=extend_schema(description='Частично обновить целевую долю.'),
    destroy=extend_schema(description='Удалить целевую долю.'),
)
class InvestmentTargetAllocationViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentTargetAllocationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            InvestmentTargetAllocation.objects
            .select_related('portfolio', 'portfolio__user', 'instrument')
            .order_by('portfolio', 'instrument__ticker')
        )
        if getattr(self, 'swagger_fake_view', False):
            return queryset.none()
        portfolio_id = self.request.query_params.get('portfolio')
        if portfolio_id:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        instrument_id = self.request.query_params.get('instrument')
        if instrument_id:
            queryset = queryset.filter(instrument_id=instrument_id)
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(portfolio__user=self.request.user)


@extend_schema_view(
    list=extend_schema(
        parameters=operation_list_parameters,
        description='Список инвестиционных операций, отсортированный по дате убыванию. Операции не создают денежные движения и не попадают в 1С.',
    ),
    create=extend_schema(description='Создать инвестиционную операцию. Покупки/продажи не меняют денежные кошельки.'),
    retrieve=extend_schema(description='Получить инвестиционную операцию.'),
    update=extend_schema(description='Полностью обновить инвестиционную операцию.'),
    partial_update=extend_schema(description='Частично обновить инвестиционную операцию.'),
    destroy=extend_schema(description='Удалить инвестиционную операцию.'),
)
class InvestmentOperationViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentOperationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            InvestmentOperation.objects
            .select_related('portfolio', 'portfolio__user', 'account', 'account_to', 'instrument')
            .order_by('-date', '-created_at')
        )
        if getattr(self, 'swagger_fake_view', False):
            return queryset.none()
        filters = {
            'portfolio_id': self.request.query_params.get('portfolio'),
            'account_id': self.request.query_params.get('account'),
            'instrument_id': self.request.query_params.get('instrument'),
            'operation_type': self.request.query_params.get('operation_type'),
        }
        for field, value in filters.items():
            if value:
                queryset = queryset.filter(**{field: value})
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            queryset = queryset.filter(date__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__date__lte=date_to)
        if self.request.query_params.get('deleted') in ('true', 'false'):
            queryset = queryset.filter(deleted=self.request.query_params.get('deleted') == 'true')
        else:
            queryset = queryset.filter(deleted=False)
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(portfolio__user=self.request.user)

    def perform_create(self, serializer):
        instance = serializer.save()
        _rebuild_snapshots_after_investment_change(
            portfolio=instance.portfolio_id,
            changed_at=instance.date,
        )

    def perform_update(self, serializer):
        previous_portfolio_id = serializer.instance.portfolio_id
        previous_date = serializer.instance.date
        instance = serializer.save()
        if previous_portfolio_id == instance.portfolio_id:
            _rebuild_snapshots_after_investment_change(
                portfolio=instance.portfolio_id,
                date_from=_min_date(previous_date, instance.date),
            )
            return
        _rebuild_snapshots_after_investment_change(
            portfolio=previous_portfolio_id,
            changed_at=previous_date,
        )
        _rebuild_snapshots_after_investment_change(
            portfolio=instance.portfolio_id,
            changed_at=instance.date,
        )

    def perform_destroy(self, instance):
        portfolio_id = instance.portfolio_id
        changed_at = instance.date
        instance.delete()
        _rebuild_snapshots_after_investment_change(
            portfolio=portfolio_id,
            changed_at=changed_at,
        )


class InvestmentOverviewViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=overview_parameters,
        responses={200: InvestmentPortfolioOverviewSerializer},
        description='Overview портфеля по умолчанию или указанного portfolio. Используется главным экраном раздела Портфель.',
    )
    def list(self, request):
        portfolio_id = request.query_params.get('portfolio')
        queryset = InvestmentPortfolio.objects.select_related('user', 'project')
        if request.user.is_staff:
            portfolio = queryset.filter(pk=portfolio_id).first() if portfolio_id else queryset.order_by('-is_default', 'name').first()
        else:
            user_queryset = queryset.filter(user=request.user)
            portfolio = user_queryset.filter(pk=portfolio_id).first() if portfolio_id else get_default_portfolio(request.user)
        if portfolio is None:
            return Response({
                'portfolio': None,
                'cost_basis_usd': '0.00',
                'current_value_usd': '0.00',
                'realized_pl_usd': '0.00',
                'unrealized_pl_usd': '0.00',
                'total_pl_usd': '0.00',
                'return_percent': None,
                'valuation_complete': True,
                'bought_usd': '0.00',
                'sold_usd': '0.00',
                'positions': [],
            })
        return Response(serialize_portfolio_overview(portfolio))
