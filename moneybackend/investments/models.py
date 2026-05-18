import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from money.utils import generate_document_number


ZERO_AMOUNT = Decimal('0')
SUPPORTED_CURRENCIES = ('USD', 'EUR', 'RUB')
CURRENCY_CHOICES = [(currency, currency) for currency in SUPPORTED_CURRENCIES]
COMMON_CRYPTO_PROVIDER_SYMBOLS = {
    'ADA': 'cardano',
    'BNB': 'binancecoin',
    'BTC': 'bitcoin',
    'DOGE': 'dogecoin',
    'DOT': 'polkadot',
    'ETH': 'ethereum',
    'MATIC': 'matic-network',
    'POL': 'polygon-ecosystem-token',
    'SOL': 'solana',
    'TON': 'the-open-network',
    'USDC': 'usd-coin',
    'USDT': 'tether',
    'XRP': 'ripple',
}


class Instrument(models.Model):
    TYPE_CRYPTO = 'crypto'
    TYPE_STOCK = 'stock'
    TYPES = [
        (TYPE_CRYPTO, 'Криптовалюта'),
        (TYPE_STOCK, 'Акция'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=TYPES, default=TYPE_CRYPTO)
    ticker = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    provider_symbol = models.CharField(max_length=50, blank=True, default='')
    quote_currency = models.CharField(max_length=10, default='USD')
    precision = models.PositiveSmallIntegerField(default=8)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Финансовый инструмент'
        verbose_name_plural = 'Финансовые инструменты'
        ordering = ['type', 'ticker']
        constraints = [
            models.UniqueConstraint(fields=['type', 'ticker'], name='uniq_instrument_type_ticker'),
        ]

    def save(self, *args, **kwargs):
        self.ticker = (self.ticker or '').strip().upper()
        self.provider_symbol = self.normalize_provider_symbol(self.type, self.provider_symbol, self.ticker)
        self.quote_currency = (self.quote_currency or 'USD').strip().upper()
        super().save(*args, **kwargs)

    @classmethod
    def normalize_provider_symbol(cls, instrument_type, provider_symbol, ticker):
        symbol = (provider_symbol or ticker or '').strip()
        if instrument_type == cls.TYPE_CRYPTO:
            return COMMON_CRYPTO_PROVIDER_SYMBOLS.get(symbol.upper(), symbol)
        return symbol

    def __str__(self):
        return f'{self.ticker} ({self.get_type_display()})'


class InstrumentPriceSnapshot(models.Model):
    SOURCE_MANUAL = 'manual'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name='price_snapshots')
    captured_at = models.DateTimeField(default=timezone.now)
    price = models.DecimalField(max_digits=24, decimal_places=8)
    price_currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='USD')
    fx_rate_to_usd = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal('1'))
    price_usd = models.DecimalField(max_digits=18, decimal_places=2)
    source = models.CharField(max_length=50, default=SOURCE_MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        verbose_name = 'Снимок цены инструмента'
        verbose_name_plural = 'Снимки цен инструментов'
        ordering = ['-captured_at', '-created_at']
        indexes = [
            models.Index(fields=['instrument', '-captured_at']),
        ]

    def save(self, *args, **kwargs):
        self.price_currency = (self.price_currency or 'USD').strip().upper()
        self.source = (self.source or self.SOURCE_MANUAL).strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.instrument.ticker}: {self.price_usd} USD'


class FxRateSnapshot(models.Model):
    SOURCE_MANUAL = 'manual'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    captured_at = models.DateTimeField(default=timezone.now)
    base_currency = models.CharField(max_length=10)
    quote_currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='USD')
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    source = models.CharField(max_length=50, default=SOURCE_MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Снимок валютного курса'
        verbose_name_plural = 'Снимки валютных курсов'
        ordering = ['-captured_at', '-created_at']
        indexes = [
            models.Index(fields=['base_currency', 'quote_currency', '-captured_at']),
        ]

    def save(self, *args, **kwargs):
        self.base_currency = (self.base_currency or '').strip().upper()
        self.quote_currency = (self.quote_currency or 'USD').strip().upper()
        self.source = (self.source or self.SOURCE_MANUAL).strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.base_currency}/{self.quote_currency}: {self.rate}'


class InvestmentPortfolio(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='investment_portfolios',
    )
    name = models.CharField(max_length=100)
    base_currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='USD')
    project = models.ForeignKey('money.Project', on_delete=models.PROTECT, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Инвестиционный портфель'
        verbose_name_plural = 'Инвестиционные портфели'
        ordering = ['user', '-is_default', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(is_default=True),
                name='uniq_default_investment_portfolio_per_user',
            ),
        ]

    def save(self, *args, **kwargs):
        self.base_currency = 'USD'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class InvestmentPortfolioSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(InvestmentPortfolio, on_delete=models.CASCADE, related_name='snapshots')
    snapshot_date = models.DateField()
    cost_basis_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    current_value_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    realized_pl_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    unrealized_pl_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    total_pl_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    return_percent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valuation_complete = models.BooleanField(default=False)
    bought_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    sold_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    latest_price_at = models.DateTimeField(null=True, blank=True)
    positions_payload = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Снимок инвестиционного портфеля'
        verbose_name_plural = 'Снимки инвестиционных портфелей'
        ordering = ['portfolio', '-snapshot_date']
        constraints = [
            models.UniqueConstraint(fields=['portfolio', 'snapshot_date'], name='uniq_portfolio_snapshot_date'),
        ]
        indexes = [
            models.Index(fields=['portfolio', '-snapshot_date']),
        ]

    def __str__(self):
        return f'{self.portfolio}: {self.snapshot_date}'


class InvestmentTargetAllocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(InvestmentPortfolio, on_delete=models.CASCADE, related_name='target_allocations')
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name='target_allocations')
    target_percent = models.DecimalField(max_digits=5, decimal_places=2)
    tolerance_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('5.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Целевая доля инструмента'
        verbose_name_plural = 'Целевые доли инструментов'
        ordering = ['portfolio', 'instrument__ticker']
        constraints = [
            models.UniqueConstraint(fields=['portfolio', 'instrument'], name='uniq_target_allocation_portfolio_instrument'),
        ]

    def clean(self):
        errors = {}
        if self.target_percent <= ZERO_AMOUNT or self.target_percent > Decimal('100'):
            errors['target_percent'] = 'Целевая доля должна быть больше 0 и не больше 100.'
        if self.tolerance_percent < ZERO_AMOUNT or self.tolerance_percent > Decimal('100'):
            errors['tolerance_percent'] = 'Допуск должен быть от 0 до 100.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.portfolio}: {self.instrument.ticker} {self.target_percent}%'


class InvestmentAccount(models.Model):
    TYPE_EXCHANGE = 'exchange'
    TYPE_BROKER = 'broker'
    TYPE_COLD_WALLET = 'cold_wallet'
    TYPE_MANUAL = 'manual'
    TYPES = [
        (TYPE_EXCHANGE, 'Биржа'),
        (TYPE_BROKER, 'Брокер'),
        (TYPE_COLD_WALLET, 'Холодный кошелек'),
        (TYPE_MANUAL, 'Ручной счет'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(InvestmentPortfolio, on_delete=models.PROTECT, related_name='accounts')
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=TYPES, default=TYPE_MANUAL)
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='USD')
    hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Инвестиционный счет'
        verbose_name_plural = 'Инвестиционные счета'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['portfolio', 'name'], name='uniq_investment_account_portfolio_name'),
        ]

    def save(self, *args, **kwargs):
        self.currency = (self.currency or 'USD').strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class InvestmentOperation(models.Model):
    TYPE_BUY = 'buy'
    TYPE_SELL = 'sell'
    TYPE_TRANSFER = 'transfer_instrument'
    TYPE_CORRECTION = 'correction'
    TYPE_DIVIDEND = 'dividend'
    TYPE_SPLIT = 'split'
    TYPES = [
        (TYPE_BUY, 'Покупка'),
        (TYPE_SELL, 'Продажа'),
        (TYPE_TRANSFER, 'Перевод инструмента'),
        (TYPE_CORRECTION, 'Корректировка'),
        (TYPE_DIVIDEND, 'Дивиденд'),
        (TYPE_SPLIT, 'Split'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=12, blank=True, default='')
    date = models.DateTimeField(default=timezone.now)
    portfolio = models.ForeignKey(InvestmentPortfolio, on_delete=models.PROTECT, related_name='operations')
    account = models.ForeignKey(InvestmentAccount, on_delete=models.PROTECT, related_name='operations')
    account_to = models.ForeignKey(
        InvestmentAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='incoming_transfers',
    )
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name='operations')
    operation_type = models.CharField(max_length=30, choices=TYPES)
    quantity = models.DecimalField(max_digits=24, decimal_places=10, default=ZERO_AMOUNT)
    price_usd = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    amount_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    fee_usd = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    comment = models.CharField(max_length=200, blank=True, default='')
    deleted = models.BooleanField(default=False)
    posted = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Инвестиционная операция'
        verbose_name_plural = 'Инвестиционные операции'
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['portfolio', '-date'], name='inv_op_portfolio_date_idx'),
            models.Index(fields=['account', '-date'], name='inv_op_account_date_idx'),
            models.Index(fields=['instrument', '-date'], name='inv_op_instr_date_idx'),
            models.Index(fields=['deleted', 'posted', '-date'], name='inv_op_state_date_idx'),
            models.Index(fields=['operation_type', '-date'], name='inv_op_type_date_idx'),
        ]

    def clean(self):
        errors = {}

        if self.account and self.portfolio and self.account.portfolio_id != self.portfolio_id:
            errors['account'] = 'Счет должен принадлежать портфелю операции.'
        if self.account_to and self.portfolio and self.account_to.portfolio_id != self.portfolio_id:
            errors['account_to'] = 'Счет-получатель должен принадлежать портфелю операции.'
        if self.operation_type == self.TYPE_TRANSFER:
            if self.account_to is None:
                errors['account_to'] = 'Укажите счет-получатель для перевода инструмента.'
            elif self.account_id == self.account_to_id:
                errors['account_to'] = 'Счета перевода должны отличаться.'
        elif self.account_to is not None:
            errors['account_to'] = 'Счет-получатель используется только для перевода инструмента.'

        if self.operation_type != self.TYPE_DIVIDEND and self.quantity == ZERO_AMOUNT:
            errors['quantity'] = 'Количество не может быть нулевым.'
        if self.operation_type in (self.TYPE_BUY, self.TYPE_SELL, self.TYPE_TRANSFER) and self.quantity < ZERO_AMOUNT:
            errors['quantity'] = 'Количество должно быть положительным.'
        if self.operation_type == self.TYPE_SPLIT and self.quantity <= ZERO_AMOUNT:
            errors['quantity'] = 'Коэффициент split должен быть положительным.'
        if self.operation_type in (self.TYPE_BUY, self.TYPE_SELL):
            if self.price_usd is None or self.price_usd <= ZERO_AMOUNT:
                errors['price_usd'] = 'Укажите положительную цену в USD.'
            if self.amount_usd <= ZERO_AMOUNT:
                errors['amount_usd'] = 'Укажите положительную сумму в USD.'
        if self.operation_type == self.TYPE_DIVIDEND and self.amount_usd <= ZERO_AMOUNT:
            errors['amount_usd'] = 'Укажите положительную сумму дивиденда в USD.'
        if self.operation_type == self.TYPE_SPLIT:
            if self.price_usd is not None:
                errors['price_usd'] = 'Split не должен содержать цену.'
            if self.amount_usd != ZERO_AMOUNT:
                errors['amount_usd'] = 'Split не должен менять сумму операции.'
            if self.fee_usd != ZERO_AMOUNT:
                errors['fee_usd'] = 'Split не должен содержать комиссию.'
        if self.operation_type == self.TYPE_CORRECTION and self.account_to is not None:
            errors['account_to'] = 'Корректировка выполняется по одному счету.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('INV', InvestmentOperation)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} {self.get_operation_type_display()} {self.instrument}'
