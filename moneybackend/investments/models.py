import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from money.utils import generate_document_number


ZERO_AMOUNT = Decimal('0')


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
        self.provider_symbol = (self.provider_symbol or self.ticker).strip()
        self.quote_currency = (self.quote_currency or 'USD').strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.ticker} ({self.get_type_display()})'


class InvestmentPortfolio(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='investment_portfolios',
    )
    name = models.CharField(max_length=100)
    base_currency = models.CharField(max_length=10, default='RUB')
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
        self.base_currency = 'RUB'
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


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
    currency = models.CharField(max_length=10, default='RUB')
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
        self.currency = (self.currency or 'RUB').strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class InvestmentOperation(models.Model):
    TYPE_BUY = 'buy'
    TYPE_SELL = 'sell'
    TYPE_TRANSFER = 'transfer_instrument'
    TYPE_CORRECTION = 'correction'
    TYPES = [
        (TYPE_BUY, 'Покупка'),
        (TYPE_SELL, 'Продажа'),
        (TYPE_TRANSFER, 'Перевод инструмента'),
        (TYPE_CORRECTION, 'Корректировка'),
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
    quantity = models.DecimalField(max_digits=24, decimal_places=10)
    price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    price_currency = models.CharField(max_length=10, default='RUB')
    amount = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    amount_currency = models.CharField(max_length=10, default='RUB')
    amount_rub = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    fx_rate_to_rub = models.DecimalField(max_digits=18, decimal_places=8, default=Decimal('1'))
    fee_amount = models.DecimalField(max_digits=24, decimal_places=8, default=ZERO_AMOUNT)
    fee_currency = models.CharField(max_length=10, default='RUB')
    fee_rub = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO_AMOUNT)
    comment = models.CharField(max_length=200, blank=True, default='')
    deleted = models.BooleanField(default=False)
    posted = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Инвестиционная операция'
        verbose_name_plural = 'Инвестиционные операции'
        ordering = ['-date', '-created_at']

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

        if self.quantity == ZERO_AMOUNT:
            errors['quantity'] = 'Количество не может быть нулевым.'
        if self.operation_type in (self.TYPE_BUY, self.TYPE_SELL, self.TYPE_TRANSFER) and self.quantity < ZERO_AMOUNT:
            errors['quantity'] = 'Количество должно быть положительным.'
        if self.operation_type in (self.TYPE_BUY, self.TYPE_SELL):
            if self.price is None or self.price <= ZERO_AMOUNT:
                errors['price'] = 'Укажите положительную цену.'
            if self.amount_rub <= ZERO_AMOUNT:
                errors['amount_rub'] = 'Укажите положительную сумму в RUB.'
        if self.operation_type == self.TYPE_CORRECTION and self.account_to is not None:
            errors['account_to'] = 'Корректировка выполняется по одному счету.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('INV', InvestmentOperation)
        self.price_currency = (self.price_currency or 'RUB').strip().upper()
        self.amount_currency = (self.amount_currency or 'RUB').strip().upper()
        self.fee_currency = (self.fee_currency or 'RUB').strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} {self.get_operation_type_display()} {self.instrument}'
