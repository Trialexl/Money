from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (
    FxRateSnapshot,
    Instrument,
    InstrumentPriceSnapshot,
    InvestmentAccount,
    InvestmentOperation,
    InvestmentPortfolio,
)
from .services import calculate_instrument_quantity, calculate_portfolio_totals, calculate_positions


def _serialize_decimal(value):
    return f'{value:.2f}' if value is not None else None


def get_default_portfolio(user):
    portfolio = InvestmentPortfolio.objects.filter(user=user, is_default=True).first()
    if portfolio is not None:
        return portfolio
    return InvestmentPortfolio.objects.filter(user=user).order_by('name').first()


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = [
            'id',
            'type',
            'ticker',
            'name',
            'provider_symbol',
            'quote_currency',
            'precision',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_ticker(self, value):
        return (value or '').strip().upper()

    def validate_provider_symbol(self, value):
        return (value or '').strip()

    def validate_quote_currency(self, value):
        return (value or 'USD').strip().upper()


class InstrumentPriceSnapshotSerializer(serializers.ModelSerializer):
    instrument_ticker = serializers.CharField(source='instrument.ticker', read_only=True)
    instrument_name = serializers.CharField(source='instrument.name', read_only=True)

    class Meta:
        model = InstrumentPriceSnapshot
        fields = [
            'id',
            'instrument',
            'instrument_ticker',
            'instrument_name',
            'captured_at',
            'price',
            'price_currency',
            'fx_rate_to_rub',
            'price_rub',
            'source',
            'created_at',
        ]
        read_only_fields = ['id', 'instrument_ticker', 'instrument_name', 'created_at']
        extra_kwargs = {
            'price_rub': {'required': False},
            'source': {'required': False},
        }

    def validate_price_currency(self, value):
        return (value or 'USD').strip().upper()

    def validate_source(self, value):
        return (value or InstrumentPriceSnapshot.SOURCE_MANUAL).strip()

    def validate(self, attrs):
        price = attrs.get('price') if 'price' in attrs else getattr(self.instance, 'price', None)
        fx_rate_to_rub = attrs.get('fx_rate_to_rub') if 'fx_rate_to_rub' in attrs else getattr(self.instance, 'fx_rate_to_rub', Decimal('1'))
        price_rub = attrs.get('price_rub') if 'price_rub' in attrs else getattr(self.instance, 'price_rub', None)

        if price is None or price <= 0:
            raise serializers.ValidationError({'price': 'Укажите положительную цену.'})
        if fx_rate_to_rub is None or fx_rate_to_rub <= 0:
            raise serializers.ValidationError({'fx_rate_to_rub': 'Укажите положительный курс к RUB.'})

        should_recalculate_price_rub = (
            price_rub is None or price_rub <= 0 or 'price' in attrs or 'fx_rate_to_rub' in attrs
        )
        if should_recalculate_price_rub:
            attrs['price_rub'] = (price * fx_rate_to_rub).quantize(Decimal('0.01'))
        elif price_rub <= 0:
            raise serializers.ValidationError({'price_rub': 'Укажите положительную цену в RUB.'})

        return attrs


class FxRateSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = FxRateSnapshot
        fields = [
            'id',
            'captured_at',
            'base_currency',
            'quote_currency',
            'rate',
            'source',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']
        extra_kwargs = {
            'source': {'required': False},
            'quote_currency': {'required': False},
        }

    def validate_base_currency(self, value):
        return (value or '').strip().upper()

    def validate_quote_currency(self, value):
        return (value or 'RUB').strip().upper()

    def validate_source(self, value):
        return (value or FxRateSnapshot.SOURCE_MANUAL).strip()

    def validate(self, attrs):
        rate = attrs.get('rate') if 'rate' in attrs else getattr(self.instance, 'rate', None)
        if not attrs.get('base_currency') and self.instance is None:
            raise serializers.ValidationError({'base_currency': 'Укажите базовую валюту.'})
        if rate is None or rate <= 0:
            raise serializers.ValidationError({'rate': 'Укажите положительный курс.'})
        return attrs


class InvestmentPortfolioSerializer(serializers.ModelSerializer):
    user = serializers.UUIDField(source='user_id', read_only=True)

    class Meta:
        model = InvestmentPortfolio
        fields = [
            'id',
            'user',
            'name',
            'base_currency',
            'project',
            'is_default',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'base_currency', 'created_at', 'updated_at']


class InvestmentAccountSerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)

    class Meta:
        model = InvestmentAccount
        fields = [
            'id',
            'portfolio',
            'portfolio_name',
            'name',
            'type',
            'currency',
            'hidden',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'portfolio_name', 'created_at', 'updated_at']

    def validate_portfolio(self, portfolio):
        request = self.context.get('request')
        if request and not request.user.is_staff and portfolio.user_id != request.user.id:
            raise serializers.ValidationError('Портфель недоступен.')
        return portfolio


class InvestmentOperationSerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    account_to_name = serializers.CharField(source='account_to.name', read_only=True)
    instrument_ticker = serializers.CharField(source='instrument.ticker', read_only=True)
    instrument_name = serializers.CharField(source='instrument.name', read_only=True)

    class Meta:
        model = InvestmentOperation
        fields = [
            'id',
            'number',
            'date',
            'portfolio',
            'portfolio_name',
            'account',
            'account_name',
            'account_to',
            'account_to_name',
            'instrument',
            'instrument_ticker',
            'instrument_name',
            'operation_type',
            'quantity',
            'price',
            'price_currency',
            'amount',
            'amount_currency',
            'amount_rub',
            'fx_rate_to_rub',
            'fee_amount',
            'fee_currency',
            'fee_rub',
            'comment',
            'deleted',
            'posted',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'number',
            'portfolio_name',
            'account_name',
            'account_to_name',
            'instrument_ticker',
            'instrument_name',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'portfolio': {'required': False},
        }

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        portfolio = attrs.get('portfolio') or getattr(self.instance, 'portfolio', None)
        account = attrs.get('account') or getattr(self.instance, 'account', None)
        account_to = attrs.get('account_to') if 'account_to' in attrs else getattr(self.instance, 'account_to', None)

        if portfolio is None:
            if account is not None:
                portfolio = account.portfolio
                attrs['portfolio'] = portfolio
            elif user and user.is_authenticated:
                portfolio = get_default_portfolio(user)
                if portfolio is not None:
                    attrs['portfolio'] = portfolio

        if portfolio is None:
            raise serializers.ValidationError({'portfolio': 'Укажите портфель.'})

        if user and user.is_authenticated and not user.is_staff and portfolio.user_id != user.id:
            raise serializers.ValidationError({'portfolio': 'Портфель недоступен.'})
        if account is not None and account.portfolio_id != portfolio.id:
            raise serializers.ValidationError({'account': 'Счет должен принадлежать портфелю операции.'})
        if account_to is not None and account_to.portfolio_id != portfolio.id:
            raise serializers.ValidationError({'account_to': 'Счет-получатель должен принадлежать портфелю операции.'})

        probe = InvestmentOperation(
            **{
                field.name: getattr(self.instance, field.name)
                for field in InvestmentOperation._meta.fields
                if self.instance is not None and field.name != 'id'
            }
        ) if self.instance is not None else InvestmentOperation()

        for key, value in {**attrs, 'portfolio': portfolio}.items():
            setattr(probe, key, value)

        try:
            probe.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)

        operation_type = attrs.get('operation_type') or getattr(self.instance, 'operation_type', None)
        instrument = attrs.get('instrument') or getattr(self.instance, 'instrument', None)
        quantity = attrs.get('quantity') if 'quantity' in attrs else getattr(self.instance, 'quantity', None)
        if operation_type == InvestmentOperation.TYPE_SELL and instrument is not None and quantity is not None:
            available_quantity = calculate_instrument_quantity(
                portfolio,
                instrument,
                exclude_operation=self.instance,
            )
            if quantity > available_quantity:
                raise serializers.ValidationError({
                    'quantity': f'Продажа превышает текущий остаток: доступно {available_quantity}.'
                })

        return attrs


class InvestmentPositionSerializer(serializers.Serializer):
    instrument_id = serializers.UUIDField()
    instrument_ticker = serializers.CharField()
    instrument_name = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=24, decimal_places=10)
    cost_basis_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    average_buy_price_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    latest_price_rub = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    latest_price_at = serializers.DateTimeField(allow_null=True)
    current_value_rub = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    realized_pl_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    unrealized_pl_rub = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True)
    total_pl_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    return_percent = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    bought_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    sold_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    allocation_percent = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    target_allocation_percent = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    allocation_deviation_percent = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)


class InvestmentPortfolioOverviewSerializer(serializers.Serializer):
    portfolio = InvestmentPortfolioSerializer()
    cost_basis_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    current_value_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    realized_pl_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    unrealized_pl_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    total_pl_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    return_percent = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    valuation_complete = serializers.BooleanField()
    bought_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    sold_rub = serializers.DecimalField(max_digits=18, decimal_places=2)
    largest_asset = InvestmentPositionSerializer(allow_null=True)
    latest_price_at = serializers.DateTimeField(allow_null=True)
    positions = InvestmentPositionSerializer(many=True)


def serialize_portfolio_overview(portfolio):
    totals = calculate_portfolio_totals(portfolio)
    return {
        'portfolio': InvestmentPortfolioSerializer(portfolio).data,
        **totals,
    }
