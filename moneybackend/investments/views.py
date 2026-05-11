from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view

from .models import FxRateSnapshot, Instrument, InstrumentPriceSnapshot, InvestmentAccount, InvestmentOperation, InvestmentPortfolio
from .serializers import (
    FxRateSnapshotSerializer,
    InstrumentSerializer,
    InstrumentPriceSnapshotSerializer,
    InvestmentAccountSerializer,
    InvestmentOperationSerializer,
    InvestmentPositionSerializer,
    InvestmentPortfolioOverviewSerializer,
    InvestmentPortfolioSerializer,
    get_default_portfolio,
    serialize_portfolio_overview,
)
from .services import calculate_positions, refresh_price_snapshots


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
    OpenApiParameter('quote_currency', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Валюта котировки, по умолчанию RUB.'),
    OpenApiParameter('date_from', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата снимка курса с YYYY-MM-DD.'),
    OpenApiParameter('date_to', OpenApiTypes.DATE, OpenApiParameter.QUERY, description='Дата снимка курса по YYYY-MM-DD включительно.'),
    OpenApiParameter('source', OpenApiTypes.STR, OpenApiParameter.QUERY, description='Источник курса, например manual или cbr.'),
]

account_list_parameters = [
    OpenApiParameter('portfolio', OpenApiTypes.UUID, OpenApiParameter.QUERY, description='UUID инвестиционного портфеля.'),
    OpenApiParameter('hidden', OpenApiTypes.BOOL, OpenApiParameter.QUERY, description='Показать скрытые или видимые счета.'),
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

    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        description='Обновить цены активных инструментов через configured price/fx providers. Частичные ошибки возвращаются в results.',
    )
    @action(detail=False, methods=['post'])
    def refresh(self, request):
        return Response(refresh_price_snapshots())


@extend_schema_view(
    list=extend_schema(
        parameters=fx_rate_list_parameters,
        description='Снимки валютных курсов. Используются для переоценки инструментов в RUB.',
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
                'cost_basis_rub': '0.00',
                'current_value_rub': '0.00',
                'realized_pl_rub': '0.00',
                'unrealized_pl_rub': '0.00',
                'total_pl_rub': '0.00',
                'return_percent': None,
                'valuation_complete': True,
                'bought_rub': '0.00',
                'sold_rub': '0.00',
                'positions': [],
            })
        return Response(serialize_portfolio_overview(portfolio))
