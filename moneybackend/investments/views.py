from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Instrument, InvestmentAccount, InvestmentOperation, InvestmentPortfolio
from .serializers import (
    InstrumentSerializer,
    InvestmentAccountSerializer,
    InvestmentOperationSerializer,
    InvestmentPortfolioSerializer,
    get_default_portfolio,
    serialize_portfolio_overview,
)
from .services import calculate_positions


class InstrumentViewSet(viewsets.ModelViewSet):
    serializer_class = InstrumentSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Instrument.objects.all().order_by('type', 'ticker')
    filterset_fields = ['type', 'is_active']
    search_fields = ['ticker', 'name', 'provider_symbol']


class InvestmentPortfolioViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentPortfolioSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = InvestmentPortfolio.objects.select_related('user', 'project').order_by('-is_default', 'name')
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['get'])
    def overview(self, request, pk=None):
        return Response(serialize_portfolio_overview(self.get_object()))

    @action(detail=True, methods=['get'])
    def positions(self, request, pk=None):
        include_zero = request.query_params.get('include_zero') in ('1', 'true', 'True')
        return Response(calculate_positions(self.get_object(), include_zero=include_zero))


class InvestmentAccountViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = InvestmentAccount.objects.select_related('portfolio', 'portfolio__user').order_by('name')
        portfolio_id = self.request.query_params.get('portfolio')
        if portfolio_id:
            queryset = queryset.filter(portfolio_id=portfolio_id)
        if self.request.query_params.get('hidden') in ('true', 'false'):
            queryset = queryset.filter(hidden=self.request.query_params.get('hidden') == 'true')
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(portfolio__user=self.request.user)


class InvestmentOperationViewSet(viewsets.ModelViewSet):
    serializer_class = InvestmentOperationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = (
            InvestmentOperation.objects
            .select_related('portfolio', 'portfolio__user', 'account', 'account_to', 'instrument')
            .order_by('-date', '-created_at')
        )
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
                'realized_pl_rub': '0.00',
                'bought_rub': '0.00',
                'sold_rub': '0.00',
                'positions': [],
            })
        return Response(serialize_portfolio_overview(portfolio))
