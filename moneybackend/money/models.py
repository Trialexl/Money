import uuid
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from .utils import generate_document_number, generate_code


ZERO_AMOUNT = Decimal('0.00')
MONEY_QUANTIZER = Decimal('0.01')
ROUND_TO_THOUSANDS = Decimal('1000')
ROUND_TO_HUNDREDS = Decimal('100')
EXPENDITURE_DISTRIBUTION_ERROR = (
    'Сумма строк бюджетного распределения ({distribution_amount}) должна '
    'совпадать с суммой расхода ({document_amount}) или быть равна 0.00.'
)


def _ordered_graphic_rows(related_manager):
    return list(related_manager.order_by('date_start'))


def _sum_graphic_amounts(graphic_rows):
    return sum((row.amount for row in graphic_rows), ZERO_AMOUNT)


def _normalize_money(amount):
    if amount is None:
        return None
    if not isinstance(amount, Decimal):
        amount = Decimal(amount)
    return amount.quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)


def _round_to_step(amount, step):
    normalized_amount = _normalize_money(amount)
    return ((normalized_amount / step).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * step).quantize(
        MONEY_QUANTIZER,
        rounding=ROUND_HALF_UP,
    )


def _add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def build_periodic_graphic_rows(amount, date_start, amount_month, monthly_amount=None, without_rounding=False):
    if amount_month is None or amount_month < 1:
        raise ValidationError({'amount_month': 'Количество месяцев должно быть не меньше 1.'})
    if date_start is None:
        raise ValidationError({'date_start': 'Укажите дату начала.'})

    normalized_amount = _normalize_money(amount or ZERO_AMOUNT)

    if monthly_amount is not None:
        normalized_monthly_amount = _normalize_money(monthly_amount)
        if normalized_monthly_amount <= ZERO_AMOUNT:
            raise ValidationError({'monthly_amount': 'Ежемесячный платеж должен быть больше 0.'})
        return [
            (_add_months(date_start, month_number), normalized_monthly_amount)
            for month_number in range(amount_month)
        ], _normalize_money(normalized_monthly_amount * amount_month)

    if normalized_amount <= ZERO_AMOUNT:
        return [], normalized_amount

    if without_rounding:
        total_cents = int((normalized_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
        used_months = min(amount_month, total_cents)
        if used_months == 0:
            return [], normalized_amount

        base_cents, extra_cents = divmod(total_cents, used_months)
        rows = []
        for month_number in range(used_months):
            current_cents = base_cents
            if month_number >= used_months - extra_cents and extra_cents:
                current_cents += 1
            rows.append((
                _add_months(date_start, month_number),
                _normalize_money(Decimal(current_cents) / 100),
            ))
        return rows, normalized_amount
    else:
        month_amount = _round_to_step(normalized_amount / amount_month, ROUND_TO_THOUSANDS)
        if month_amount == ZERO_AMOUNT:
            month_amount = _round_to_step(normalized_amount / amount_month, ROUND_TO_HUNDREDS)
            if month_amount == ZERO_AMOUNT:
                raise ValidationError({'amount': 'Ежемесячный платеж меньше 100 руб.'})

    rows = []
    remainder = normalized_amount
    month_number = 0
    while remainder > ZERO_AMOUNT:
        current_amount = min(remainder, month_amount)
        current_amount = _normalize_money(current_amount)
        rows.append((_add_months(date_start, month_number), current_amount))
        remainder = _normalize_money(remainder - current_amount)
        month_number += 1

    return rows, normalized_amount


def get_expenditure_distribution_error(amount, include_in_budget, graphic_amounts):
    if not include_in_budget or amount is None:
        return None

    amounts = [graphic_amount for graphic_amount in graphic_amounts if graphic_amount is not None]
    if not amounts:
        return None

    distribution_amount = sum(amounts, ZERO_AMOUNT)
    if distribution_amount in (ZERO_AMOUNT, amount):
        return None

    return EXPENDITURE_DISTRIBUTION_ERROR.format(
        distribution_amount=distribution_amount,
        document_amount=amount,
    )


def build_graphic_contract(
    *,
    header_role,
    graphics_role,
    register_source,
    recommended_graphic_action,
    summary,
):
    return {
        'header_role': header_role,
        'graphics_role': graphics_role,
        'register_source': register_source,
        'direct_graphic_editing': True,
        'header_updates_from_graphics': False,
        'recommended_graphic_action': recommended_graphic_action,
        'summary': summary,
    }

# Базовый класс для операций с регистрами
class FinancialOperationMixin:
    """Миксин для управления регистрами"""

    def registers_enabled(self):
        return not getattr(self, 'deleted', False) and getattr(self, 'posted', True)

    def update_flow_of_funds(self):
        """Обновляет записи в регистре движения средств"""
        # Очищаем старые записи
        FlowOfFunds.objects.filter(document_id=self.id, type_of_document=self.get_document_type()).delete()

        # Создаем новые записи
        records = self.create_flow_records()
        if records:
            FlowOfFunds.objects.bulk_create(records)

    def update_budget_registers(self):
        """Обновляет записи в бюджетных регистрах"""
        # Очищаем старые записи
        BudgetExpense.objects.filter(document_id=self.id, type_of_document=self.get_document_type()).delete()
        BudgetIncome.objects.filter(document_id=self.id, type_of_document=self.get_document_type()).delete()

        # Создаем новые записи
        budget_records = self.create_budget_records()
        if budget_records:
            # Разделяем на доходы и расходы
            income_records = [r for r in budget_records if isinstance(r, BudgetIncome)]
            expense_records = [r for r in budget_records if isinstance(r, BudgetExpense)]

            if income_records:
                BudgetIncome.objects.bulk_create(income_records)
            if expense_records:
                BudgetExpense.objects.bulk_create(expense_records)

    def save(self, *args, **kwargs):
        """Переопределяем save для обновления регистров"""
        super().save(*args, **kwargs)
        self.update_registers()

    def delete(self, *args, **kwargs):
        """Переопределяем delete для очистки регистров"""
        self.clear_registers()
        super().delete(*args, **kwargs)

    def update_registers(self):
        """Обновляет все связанные регистры"""
        if self.registers_enabled():
            self.update_flow_of_funds()
            self.update_budget_registers()
        else:
            self.clear_registers()

    def clear_registers(self):
        """Очищает все записи в регистрах"""
        doc_type = self.get_document_type()
        FlowOfFunds.objects.filter(document_id=self.id, type_of_document=doc_type).delete()
        BudgetExpense.objects.filter(document_id=self.id, type_of_document=doc_type).delete()
        BudgetIncome.objects.filter(document_id=self.id, type_of_document=doc_type).delete()

    def get_document_type(self):
        """Возвращает тип документа для регистров"""
        raise NotImplementedError("Subclasses must implement get_document_type")

    def create_flow_records(self):
        """Создает записи для регистра движения средств"""
        return []

    def create_budget_records(self):
        """Создает записи для бюджетных регистров"""
        return []



# dictionary
class CashFlowItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, )
    code = models.CharField(max_length=9, unique=True, null=True, )
    name = models.CharField(max_length=25, unique=True, null=True, )
    deleted = models.BooleanField(default=False, )
    include_in_budget = models.BooleanField(default=False, null=True, )
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        verbose_name = 'Статья движения средств'
        verbose_name_plural = 'Статьи движения средств'
        ordering = ['code', 'name']

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_code('CFI', CashFlowItem)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CashFlowItemAlias(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=50)

    class Meta:
        verbose_name = 'Псевдоним статьи'
        verbose_name_plural = 'Псевдонимы статей'
        ordering = ['alias']
        constraints = [
            models.UniqueConstraint(fields=['cash_flow_item', 'alias'], name='uniq_cash_flow_item_alias'),
        ]

    def save(self, *args, **kwargs):
        self.alias = (self.alias or '').strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.cash_flow_item}: {self.alias}'


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=9, unique=True, null=True)
    name = models.CharField(max_length=25, unique=True, null=True)
    deleted = models.BooleanField(default=False)

    hidden = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Кошелек'
        verbose_name_plural = 'Кошельки'
        ordering = ['code', 'name']

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_code('WLT', Wallet)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class WalletAlias(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=50)

    class Meta:
        verbose_name = 'Псевдоним кошелька'
        verbose_name_plural = 'Псевдонимы кошельков'
        ordering = ['alias']
        constraints = [
            models.UniqueConstraint(fields=['wallet', 'alias'], name='uniq_wallet_alias'),
        ]

    def save(self, *args, **kwargs):
        self.alias = (self.alias or '').strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.wallet}: {self.alias}'


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=9, unique=True, null=True)
    name = models.CharField(max_length=25, unique=True, null=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Проект'
        verbose_name_plural = 'Проекты'
        ordering = ['code', 'name']

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_code('PRJ', Project)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# documents


# Приход
class Receipt(FinancialOperationMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, )
    number = models.CharField(max_length=9, null=False, )
    date = models.DateTimeField(default=timezone.now, )
    deleted = models.BooleanField(default=False, )
    posted = models.BooleanField(default=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2, )
    comment = models.CharField(max_length=200, blank=True, )
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, null=True)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)

    class Meta:
        verbose_name = 'Приход'
        verbose_name_plural = 'Приходы'
        ordering = ['-date']

    def clean(self):
        errors = {}
        if self.wallet is None:
            errors['wallet'] = 'Укажите кошелек.'
        if self.cash_flow_item is None:
            errors['cash_flow_item'] = 'Укажите статью.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('RCP', Receipt)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} от {self.date}'
    
    def get_document_type(self):
        return 3
    
    def create_flow_records(self):
        """Создает записи прихода в регистре движения средств"""
        return [FlowOfFunds(
            document_id=self.id,
            period=self.date,
            type_of_document=3,
            wallet=self.wallet,
            cash_flow_item=self.cash_flow_item,
            amount=self.amount
        )]
    
    def create_budget_records(self):
        """Создает записи в бюджетных регистрах"""
        records = []
        # Приходы попадают только в бюджет доходов
        records.append(BudgetIncome(
            document_id=self.id,
            period=self.date,
            type_of_document=3,
            project=None,  # У Receipt нет проекта
            cash_flow_item=self.cash_flow_item,
            amount=self.amount
        ))
        return records


# Расход
class Expenditure(FinancialOperationMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, )
    number = models.CharField(max_length=9, null=False, )
    date = models.DateTimeField(default=timezone.now, )
    deleted = models.BooleanField(default=False, )
    posted = models.BooleanField(default=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2, )
    comment = models.CharField(max_length=200, blank=True, )
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, null=True)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)
    include_in_budget = models.BooleanField(default=True, )

    class Meta:
        verbose_name = 'Расход'
        verbose_name_plural = 'Расходы'
        ordering = ['-date']

    def clean(self):
        errors = {}
        if self.wallet is None:
            errors['wallet'] = 'Укажите кошелек.'
        if self.cash_flow_item is None:
            errors['cash_flow_item'] = 'Укажите статью.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('EXP', Expenditure)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} от {self.date}'
    
    def get_document_type(self):
        return 4
    
    def create_flow_records(self):
        """Создает записи расхода в регистре движения средств"""
        return [FlowOfFunds(
            document_id=self.id,
            period=self.date,
            type_of_document=4,
            wallet=self.wallet,
            cash_flow_item=self.cash_flow_item,
            amount=self.amount * -1  # Расходы отрицательные
        )]

    def budget_graphics(self):
        return _ordered_graphic_rows(self.items)

    def get_graphic_contract(self):
        return build_graphic_contract(
            header_role='financial_fact',
            graphics_role='budget_distribution',
            register_source='graphics_if_exact_else_header',
            recommended_graphic_action='replace-graphics',
            summary=(
                'Шапка хранит сумму фактического расхода. '
                'Строки графика управляют только бюджетным распределением '
                'и используются для регистров только при точном совпадении суммы.'
            ),
        )

    def get_distribution_validation_error(self, graphic_amounts=None):
        if graphic_amounts is None:
            graphic_amounts = self.items.values_list('amount', flat=True)
        return get_expenditure_distribution_error(
            amount=self.amount,
            include_in_budget=self.include_in_budget,
            graphic_amounts=graphic_amounts,
        )
    
    def create_budget_records(self):
        """Создает записи в бюджетных регистрах если включен в бюджет"""
        if not self.include_in_budget:
            return []

        graphics = self.budget_graphics()
        total_graphics = _sum_graphic_amounts(graphics)

        # В 1С строки бюджета используются только когда они полностью покрывают сумму документа.
        # Во всех остальных случаях поведение остается предсказуемым: весь расход идет на дату документа.
        if not graphics or total_graphics == ZERO_AMOUNT or total_graphics != self.amount:
            return [BudgetExpense(
                document_id=self.id,
                period=self.date,
                type_of_document=4,
                project=None,
                cash_flow_item=self.cash_flow_item,
                amount=self.amount
            )]

        return [
            BudgetExpense(
                document_id=self.id,
                period=row.date_start,
                type_of_document=4,
                project=None,
                cash_flow_item=self.cash_flow_item,
                amount=row.amount
            )
            for row in graphics
        ]


class ExpenditureGraphic(models.Model):
    document = models.ForeignKey(Expenditure, models.CASCADE, related_name='items', )
    date_start = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'График расхода'
        verbose_name_plural = 'Графики расходов'
        ordering = ['date_start']

    def __str__(self):
        return f'Table_Expenditure{self.document} '


class Transfer(FinancialOperationMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=9, null=False, )
    date = models.DateTimeField(default=timezone.now, )
    deleted = models.BooleanField(default=False, )
    posted = models.BooleanField(default=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2, )
    comment = models.CharField(max_length=200, blank=True, )
    wallet_in = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='wallet_in', db_column='wallet_in',
                                 null=True)
    wallet_out = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='wallet_out', db_column='wallet_out',
                                  null=True)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)
    include_in_budget = models.BooleanField(default=False, )

    class Meta:
        verbose_name = 'Перевод'
        verbose_name_plural = 'Переводы'
        ordering = ['-date']

    def clean(self):
        errors = {}
        if self.wallet_out is None:
            errors['wallet_out'] = 'Укажите исходящий кошелек.'
        if self.wallet_in is None:
            errors['wallet_in'] = 'Укажите входящий кошелек.'
        if self.wallet_in is not None and self.wallet_out is not None and self.wallet_in == self.wallet_out:
            errors['wallet_in'] = 'Входящий и исходящий кошелек не могут быть одинаковыми.'
        if self.include_in_budget and self.cash_flow_item is None:
            errors['cash_flow_item'] = 'Укажите статью для бюджетного перевода.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('TRF', Transfer)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} от {self.date}'
    
    def get_document_type(self):
        return 2
    
    def create_flow_records(self):
        """Создает записи перевода в регистре движения средств"""
        records = []
        # Списание с исходящего кошелька
        if self.wallet_out:
            records.append(FlowOfFunds(
                document_id=self.id,
                period=self.date,
                type_of_document=2,
                wallet=self.wallet_out,
                cash_flow_item=self.cash_flow_item,
                amount=self.amount * -1
            ))
        # Поступление на входящий кошелек
        if self.wallet_in:
            records.append(FlowOfFunds(
                document_id=self.id,
                period=self.date,
                type_of_document=2,
                wallet=self.wallet_in,
                cash_flow_item=self.cash_flow_item,
                amount=self.amount
            ))
        return records

    def budget_graphics(self):
        return _ordered_graphic_rows(self.items)

    def get_graphic_contract(self):
        return build_graphic_contract(
            header_role='financial_fact',
            graphics_role='budget_distribution',
            register_source='graphics_with_header_remainder',
            recommended_graphic_action='replace-graphics',
            summary=(
                'Шапка хранит сумму фактического перевода. '
                'Строки графика управляют бюджетным распределением; '
                'для полной замены графика предпочтителен document-level replace-graphics, '
                'остаток, не покрытый графиком, остается на дате документа.'
            ),
        )
    
    def create_budget_records(self):
        """Создает записи в бюджетных регистрах если включен в бюджет"""
        records = []
        if self.include_in_budget:
            graphics = self.budget_graphics()
            total_graphics = _sum_graphic_amounts(graphics)

            for row in graphics:
                records.append(BudgetExpense(
                    document_id=self.id,
                    period=row.date_start,
                    type_of_document=2,
                    project=None,
                    cash_flow_item=self.cash_flow_item,
                    amount=row.amount
                ))

            remainder = self.amount - total_graphics
            if not graphics or remainder != ZERO_AMOUNT:
                records.append(BudgetExpense(
                    document_id=self.id,
                    period=self.date,
                    type_of_document=2,
                    project=None,
                    cash_flow_item=self.cash_flow_item,
                    amount=remainder if graphics else self.amount
                ))
        return records


class TransferGraphic(models.Model):
    document = models.ForeignKey(Transfer, models.CASCADE, related_name='items', )
    date_start = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'График перевода'
        verbose_name_plural = 'Графики переводов'
        ordering = ['date_start']

    def __str__(self):
        return f'Table_Transfer{self.document} '


class Budget(FinancialOperationMixin, models.Model):
    TYPE_OF_BUDGET = [
        (True, 'Приход'),
        (False, 'Расход')
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=9, null=False, )
    date = models.DateTimeField(default=timezone.now)
    deleted = models.BooleanField(default=False)
    posted = models.BooleanField(default=True)

    date_start = models.DateTimeField(default=timezone.now)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_month = models.IntegerField(default=12)
    comment = models.CharField(max_length=200, blank=True, )
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True)
    type_of_budget = models.BooleanField(choices=TYPE_OF_BUDGET, default=False)

    class Meta:
        verbose_name = 'Бюджет'
        verbose_name_plural = 'Бюджеты'
        ordering = ['-date']

    def clean(self):
        errors = {}
        if self.amount_month is None or self.amount_month < 1:
            errors['amount_month'] = 'Количество месяцев должно быть не меньше 1.'
        if self.date_start is None:
            errors['date_start'] = 'Укажите дату начала.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('BGT', Budget)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} от {self.date}'
    
    def get_document_type(self):
        return 5
    
    def create_flow_records(self):
        """Бюджеты не создают записи в движении средств"""
        return []

    def graphic_rows(self):
        return _ordered_graphic_rows(self.items)

    def get_graphic_contract(self):
        return build_graphic_contract(
            header_role='graphic_generation_template',
            graphics_role='register_schedule',
            register_source='graphics_or_header_fallback',
            recommended_graphic_action='generate-graphics',
            summary=(
                'Поля шапки задают шаблон генерации графика. '
                'Если строки графика существуют, именно они становятся расписанием '
                'для бюджетных регистров; ручная правка строк не пересчитывает шапку.'
            ),
        )

    def build_generated_graphic_rows(self, monthly_amount=None, without_rounding=False):
        return build_periodic_graphic_rows(
            amount=self.amount,
            date_start=self.date_start,
            amount_month=self.amount_month,
            monthly_amount=monthly_amount,
            without_rounding=without_rounding,
        )

    def _build_budget_record(self, period, amount):
        record_class = BudgetIncome if self.type_of_budget else BudgetExpense
        return record_class(
            document_id=self.id,
            period=period,
            type_of_document=5,
            project=self.project,
            cash_flow_item=self.cash_flow_item,
            amount=amount
        )
    
    def create_budget_records(self):
        """Создает записи в бюджетных регистрах"""
        graphics = self.graphic_rows()
        if graphics:
            return [self._build_budget_record(row.date_start, row.amount) for row in graphics]
        return [self._build_budget_record(self.date_start, self.amount)]


class BudgetGraphic(models.Model):
    document = models.ForeignKey(Budget, models.CASCADE, related_name='items', )
    date_start = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'График бюджета'
        verbose_name_plural = 'Графики бюджетов'
        ordering = ['date_start']

    def __str__(self):
        return f'Table_budget {self.document}'


class AutoPayment(FinancialOperationMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=9, null=False, )
    date = models.DateTimeField(default=timezone.now, )
    deleted = models.BooleanField(default=False, )
    posted = models.BooleanField(default=True)

    wallet_in = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='ap_wallet_in', db_column='wallet_in',
                                null=True,blank=True, )
    wallet_out = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='ap_wallet_out', db_column='wallet_out',
                                null=True,blank=True, )
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, 
                                null=True, blank=True, )
    is_transfer = models.BooleanField(default=False, )
    amount_month = models.IntegerField(default=12)
    amount = models.DecimalField(max_digits=12, decimal_places=2, )
    comment = models.CharField(max_length=200, blank=True, )
    date_start = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Автоплатеж'
        verbose_name_plural = 'Автоплатежи'
        ordering = ['-date']

    def clean(self):
        errors = {}
        if self.wallet_out is None:
            errors['wallet_out'] = 'Укажите исходящий кошелек.'
        if self.amount_month is None or self.amount_month < 1:
            errors['amount_month'] = 'Количество месяцев должно быть не меньше 1.'
        if self.date_start is None:
            errors['date_start'] = 'Укажите дату начала.'
        if self.is_transfer:
            if self.wallet_in is None:
                errors['wallet_in'] = 'Укажите входящий кошелек для автоперевода.'
            if self.wallet_in is not None and self.wallet_out is not None and self.wallet_in == self.wallet_out:
                errors['wallet_in'] = 'Входящий и исходящий кошелек не могут быть одинаковыми.'
        elif self.cash_flow_item is None:
            errors['cash_flow_item'] = 'Укажите статью для автоплатежа.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = generate_document_number('AUT', AutoPayment)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.number} от {self.date}'
    
    def get_document_type(self):
        return 1

    def graphic_rows(self):
        return _ordered_graphic_rows(self.items)

    def get_graphic_contract(self):
        return build_graphic_contract(
            header_role='graphic_generation_template',
            graphics_role='register_schedule',
            register_source='graphics_or_header_fallback',
            recommended_graphic_action='generate-graphics',
            summary=(
                'Поля шапки задают шаблон генерации графика автоплатежа. '
                'Если строки графика существуют, именно они управляют расписанием '
                'движений и бюджета; ручная правка строк не пересчитывает шапку.'
            ),
        )

    def build_generated_graphic_rows(self, monthly_amount=None, without_rounding=False):
        return build_periodic_graphic_rows(
            amount=self.amount,
            date_start=self.date_start,
            amount_month=self.amount_month,
            monthly_amount=monthly_amount,
            without_rounding=without_rounding,
        )

    def scheduled_rows(self):
        graphics = self.graphic_rows()
        if graphics:
            return [(row.date_start, row.amount) for row in graphics]
        return [(self.date_start, self.amount)]
    
    def create_flow_records(self):
        """Создает записи автоплатежа в регистре движения средств"""
        records = []
        for period, amount in self.scheduled_rows():
            if self.is_transfer:
                if self.wallet_out:
                    records.append(FlowOfFunds(
                        document_id=self.id,
                        period=period,
                        type_of_document=1,
                        wallet=self.wallet_out,
                        cash_flow_item=self.cash_flow_item,
                        amount=amount * -1
                    ))
                if self.wallet_in:
                    records.append(FlowOfFunds(
                        document_id=self.id,
                        period=period,
                        type_of_document=1,
                        wallet=self.wallet_in,
                        cash_flow_item=self.cash_flow_item,
                        amount=amount
                    ))
            else:
                wallet = self.wallet_out or self.wallet_in
                if wallet:
                    records.append(FlowOfFunds(
                        document_id=self.id,
                        period=period,
                        type_of_document=1,
                        wallet=wallet,
                        cash_flow_item=self.cash_flow_item,
                        amount=amount * -1
                    ))
        return records
    
    def create_budget_records(self):
        """Создает записи в бюджетных регистрах"""
        if self.is_transfer:
            return []

        return [
            BudgetExpense(
                document_id=self.id,
                period=period,
                type_of_document=1,
                project=None,
                cash_flow_item=self.cash_flow_item,
                amount=amount
            )
            for period, amount in self.scheduled_rows()
        ]


class AutoPaymentGraphic(models.Model):
    document = models.ForeignKey(AutoPayment, models.CASCADE, related_name='items', )
    date_start = models.DateTimeField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'График автоплатежа'
        verbose_name_plural = 'Графики автоплатежей'
        ordering = ['date_start']

    def __str__(self):
        return f'Table_autopayment {self.document} '


def sync_document_registers(document):
    """Обновляет регистры документа после внешних изменений, например строк графика."""
    if document.deleted:
        document.clear_registers()
        return
    document.update_registers()


# registers
class FlowOfFunds(models.Model):
    TYPE_OF_DOCUMENT = [
        (1, 'AutoPayment'),
        (2, 'Transfer'),
        (3, 'Receipt'),
        (4, 'Expenditure'),
        # (5, 'Budget'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_id = models.UUIDField(null=True, blank=True)  # Связь с документом
    period = models.DateTimeField()
    type_of_document = models.IntegerField(choices=TYPE_OF_DOCUMENT, )
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, null=True)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Движение средств'
        verbose_name_plural = 'Движения средств'
        ordering = ['-period']


class BudgetExpense(models.Model):
    TYPE_OF_DOCUMENT = [
        (1, 'AutoPayment'),
        (2, 'Transfer'),
        # (3, 'Receipt'),
        (4, 'Expenditure'),
        (5, 'Budget'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_id = models.UUIDField(null=True, blank=True)  # Связь с документом
    period = models.DateTimeField()
    type_of_document = models.IntegerField(choices=TYPE_OF_DOCUMENT, )
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Расход бюджета'
        verbose_name_plural = 'Расходы бюджета'
        ordering = ['-period']


class BudgetIncome(models.Model):
    TYPE_OF_DOCUMENT = [
        # (1, 'AutoPayment'),
        # (2, 'Transfer'),
        (3, 'Receipt'),
        # (4, 'Expenditure'),
        (5, 'Budget'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_id = models.UUIDField(null=True, blank=True)  # Связь с документом
    period = models.DateTimeField()
    type_of_document = models.IntegerField(choices=TYPE_OF_DOCUMENT, )
    project = models.ForeignKey(Project, on_delete=models.PROTECT, null=True)
    cash_flow_item = models.ForeignKey(CashFlowItem, on_delete=models.PROTECT, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'Доход бюджета'
        verbose_name_plural = 'Доходы бюджета'
        ordering = ['-period']


class OneCSyncOutbox(models.Model):
    UPSERT = 'upsert'
    DELETE = 'delete'
    OPERATIONS = [
        (UPSERT, 'Upsert'),
        (DELETE, 'Delete'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=50)
    object_id = models.UUIDField()
    route = models.CharField(max_length=100)
    clear_type = models.CharField(max_length=100, blank=True, default='')
    graphics_route = models.CharField(max_length=100, blank=True, default='')
    operation = models.CharField(max_length=20, choices=OPERATIONS, default=UPSERT)
    payload = models.JSONField(default=dict)
    changed_at = models.DateTimeField(default=timezone.now)
    class Meta:
        verbose_name = 'Исходящая очередь синхронизации 1С'
        verbose_name_plural = 'Исходящая очередь синхронизации 1С'
        ordering = ['changed_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['entity_type', 'object_id'], name='money_onec_sync_outbox_unique_object')
        ]

    def __str__(self):
        return f'{self.entity_type}:{self.object_id}'


class TelegramUserBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='telegram_bindings',
    )
    telegram_user_id = models.BigIntegerField(unique=True)
    telegram_chat_id = models.BigIntegerField()
    telegram_username = models.CharField(max_length=150, blank=True, default='')
    first_name = models.CharField(max_length=150, blank=True, default='')
    last_name = models.CharField(max_length=150, blank=True, default='')
    linked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Привязка Telegram пользователя'
        verbose_name_plural = 'Привязки Telegram пользователей'
        ordering = ['telegram_username', 'telegram_user_id']

    def __str__(self):
        username = self.telegram_username or self.telegram_user_id
        if self.user_id:
            return f'{username} -> {self.user}'
        return str(username)


class AiPendingConfirmation(models.Model):
    SOURCE_WEB = 'web'
    SOURCE_TELEGRAM = 'telegram'
    SOURCES = [
        (SOURCE_WEB, 'Web'),
        (SOURCE_TELEGRAM, 'Telegram'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, choices=SOURCES, default=SOURCE_TELEGRAM)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ai_pending_confirmations',
    )
    telegram_binding = models.ForeignKey(
        TelegramUserBinding,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='pending_confirmations',
    )
    intent = models.CharField(max_length=50)
    provider = models.CharField(max_length=50, blank=True, default='')
    normalized_payload = models.JSONField(default=dict)
    missing_fields = models.JSONField(default=list)
    options_payload = models.JSONField(default=dict)
    confirmation_history = models.JSONField(default=list)
    prompt_text = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ожидающее AI-уточнение'
        verbose_name_plural = 'Ожидающие AI-уточнения'
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.source}:{self.intent}:{self.id}'


class AiProcessedInput(models.Model):
    STATUS_CREATED = 'created'
    STATUS_DUPLICATE = 'duplicate'
    STATUSES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_DUPLICATE, 'Duplicate'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, default='web')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ai_processed_inputs',
    )
    telegram_binding = models.ForeignKey(
        TelegramUserBinding,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='processed_inputs',
    )
    telegram_update_id = models.BigIntegerField(null=True, blank=True)
    fingerprint = models.CharField(max_length=64, db_index=True)
    semantic_fingerprint = models.CharField(max_length=64, blank=True, default='', db_index=True)
    normalized_text = models.TextField(blank=True, default='')
    image_sha256 = models.CharField(max_length=64, blank=True, default='')
    wallet_id_hint = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=STATUS_CREATED)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Обработанный AI-ввод'
        verbose_name_plural = 'Обработанные AI-вводы'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['source', 'fingerprint', 'created_at'], name='m_ai_proc_fp_idx'),
            models.Index(fields=['source', 'semantic_fingerprint', 'created_at'], name='m_ai_proc_sem_idx'),
        ]

    def __str__(self):
        return f'{self.source}:{self.fingerprint[:10]}'


class TelegramLinkToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='telegram_link_tokens',
    )
    code = models.CharField(max_length=12, unique=True)
    is_used = models.BooleanField(default=False)
    used_by_binding = models.ForeignKey(
        TelegramUserBinding,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='used_link_tokens',
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Токен привязки Telegram'
        verbose_name_plural = 'Токены привязки Telegram'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = secrets.token_hex(3).upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} -> {self.user}'


class AiAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, default='web')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ai_audit_logs',
    )
    telegram_binding = models.ForeignKey(
        TelegramUserBinding,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    processed_input = models.ForeignKey(
        AiProcessedInput,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    pending_confirmation = models.ForeignKey(
        AiPendingConfirmation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    provider = models.CharField(max_length=50, blank=True, default='')
    input_text = models.TextField(blank=True, default='')
    image_sha256 = models.CharField(max_length=64, blank=True, default='')
    raw_provider_payload = models.JSONField(default=dict)
    normalized_payload = models.JSONField(default=dict)
    final_response_payload = models.JSONField(default=dict)
    confirmed_fields = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'AI аудит'
        verbose_name_plural = 'AI аудит'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.source}:{self.provider}:{self.created_at.isoformat()}'
