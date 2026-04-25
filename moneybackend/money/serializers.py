from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework.authentication import TokenAuthentication
from rest_framework import serializers
from . import models 
 

def _build_validation_candidate(serializer, attrs):
    model_class = serializer.Meta.model
    if not serializer.instance:
        return model_class(**attrs)

    candidate = model_class()
    for field in model_class._meta.fields:
        setattr(candidate, field.attname, getattr(serializer.instance, field.attname))
    for attr_name, value in attrs.items():
        setattr(candidate, attr_name, value)
    return candidate


def _run_model_clean(serializer, attrs):
    candidate = _build_validation_candidate(serializer, attrs)
    try:
        candidate.clean()
    except DjangoValidationError as exc:
        if hasattr(exc, 'message_dict'):
            raise serializers.ValidationError(exc.message_dict)
        raise serializers.ValidationError(exc.messages)


def _raise_expenditure_distribution_error(amount, include_in_budget, graphic_amounts):
    error = models.get_expenditure_distribution_error(
        amount=amount,
        include_in_budget=include_in_budget,
        graphic_amounts=graphic_amounts,
    )
    if error:
        raise serializers.ValidationError(error)


class GraphicContractModelSerializer(serializers.ModelSerializer):
    graphic_contract = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DictField())
    def get_graphic_contract(self, obj):
        return obj.get_graphic_contract()

    def get_field_names(self, declared_fields, info):
        field_names = list(super().get_field_names(declared_fields, info))
        if 'graphic_contract' not in field_names:
            field_names.append('graphic_contract')
        return field_names


class BackendManagedIdentityMixin:
    sync_writable_fields = ()

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        authenticator = getattr(request, 'successful_authenticator', None)
        if isinstance(authenticator, TokenAuthentication):
            for field_name in self.sync_writable_fields:
                field = fields.get(field_name)
                if field is None:
                    continue
                field.read_only = False
                field.required = False
                if isinstance(field, serializers.CharField):
                    field.allow_blank = True
        return fields


# CashFlowItem,Wallet,Project
class CashFlowItemSerializer(BackendManagedIdentityMixin, serializers.ModelSerializer):
    sync_writable_fields = ('id', 'code')
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.CashFlowItem
        fields = '__all__'
        
class WalletSerializer(BackendManagedIdentityMixin, serializers.ModelSerializer):
    sync_writable_fields = ('id', 'code')
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.Wallet
        fields = '__all__'
        
class ProjectSerializer(BackendManagedIdentityMixin, serializers.ModelSerializer):
    sync_writable_fields = ('id', 'code')
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.Project
        fields = '__all__'
        
        
# Receipt,Expenditure,Transfer,Budget,BudgetGraphic 
class ReceiptSerializer(BackendManagedIdentityMixin, serializers.ModelSerializer):
    sync_writable_fields = ('id', 'number')
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.Receipt
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _run_model_clean(self, attrs)
        return attrs
        
class ExpenditureSerializer(BackendManagedIdentityMixin, GraphicContractModelSerializer):
    sync_writable_fields = ('id', 'number')
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.Expenditure
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _run_model_clean(self, attrs)

        _raise_expenditure_distribution_error(
            amount=attrs.get('amount', getattr(self.instance, 'amount', None)),
            include_in_budget=attrs.get('include_in_budget', getattr(self.instance, 'include_in_budget', False)),
            graphic_amounts=self.instance.items.values_list('amount', flat=True) if self.instance else [],
        )
        return attrs


class ExpenditureGraphicSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ExpenditureGraphic
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)

        current_document = getattr(self.instance, 'document', None)
        next_document = attrs.get('document', current_document)
        next_amount = attrs.get('amount', getattr(self.instance, 'amount', None))
        current_pk = getattr(self.instance, 'pk', None)

        if current_document and next_document and current_document != next_document:
            _raise_expenditure_distribution_error(
                amount=current_document.amount,
                include_in_budget=current_document.include_in_budget,
                graphic_amounts=current_document.items.exclude(pk=current_pk).values_list('amount', flat=True),
            )

        if next_document is not None:
            sibling_amounts = list(next_document.items.exclude(pk=current_pk).values_list('amount', flat=True))
            if next_amount is not None:
                sibling_amounts.append(next_amount)
            _raise_expenditure_distribution_error(
                amount=next_document.amount,
                include_in_budget=next_document.include_in_budget,
                graphic_amounts=sibling_amounts,
            )

        return attrs


class GraphicReplaceRowSerializer(serializers.Serializer):
    date_start = serializers.DateTimeField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class GraphicReplaceSerializer(serializers.Serializer):
    rows = GraphicReplaceRowSerializer(many=True)


class PlanningGraphicGenerationSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    amount_month = serializers.IntegerField(required=False, min_value=1)
    date_start = serializers.DateTimeField(required=False)
    monthly_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    without_rounding = serializers.BooleanField(required=False, default=False)


class DashboardOverviewQuerySerializer(serializers.Serializer):
    date = serializers.DateTimeField(required=False)
    hide_hidden_wallets = serializers.BooleanField(required=False, default=True)


class WalletBalanceResponseSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    wallet_name = serializers.CharField()
    balance = serializers.FloatField()
    currency = serializers.CharField()
    last_updated = serializers.DateTimeField(required=False)


class WalletBalancesResponseSerializer(serializers.Serializer):
    balances = WalletBalanceResponseSerializer(many=True)
    total_wallets = serializers.IntegerField()
    total_balance = serializers.FloatField()


class ExpenditureListQuerySerializer(serializers.Serializer):
    include_in_budget = serializers.BooleanField(required=False)


class BudgetListQuerySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=['income', 'expense'], required=False)


class AutoPaymentListQuerySerializer(serializers.Serializer):
    is_transfer = serializers.BooleanField(required=False)


class DashboardWalletSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    wallet_name = serializers.CharField()
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)


class DashboardBudgetExpenseItemSerializer(serializers.Serializer):
    cash_flow_item_id = serializers.UUIDField()
    cash_flow_item_name = serializers.CharField()
    remaining = serializers.DecimalField(max_digits=12, decimal_places=2)
    overrun = serializers.DecimalField(max_digits=12, decimal_places=2)


class DashboardBudgetExpenseSerializer(serializers.Serializer):
    items = DashboardBudgetExpenseItemSerializer(many=True)
    remaining_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    overrun_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class DashboardBudgetIncomeSerializer(serializers.Serializer):
    planned_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    actual_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining_total = serializers.DecimalField(max_digits=12, decimal_places=2)


class DashboardMonthTotalsSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    expense = serializers.DecimalField(max_digits=12, decimal_places=2)
    income = serializers.DecimalField(max_digits=12, decimal_places=2)


class DashboardMonthDifferenceSerializer(serializers.Serializer):
    expense = serializers.DecimalField(max_digits=12, decimal_places=2)
    income = serializers.DecimalField(max_digits=12, decimal_places=2)


class DashboardMonthComparisonSerializer(serializers.Serializer):
    previous_month = DashboardMonthTotalsSerializer()
    current_month = DashboardMonthTotalsSerializer()
    difference_percent = DashboardMonthDifferenceSerializer()


class DashboardOverviewResponseSerializer(serializers.Serializer):
    date = serializers.DateTimeField()
    hide_hidden_wallets = serializers.BooleanField()
    wallets = DashboardWalletSerializer(many=True)
    wallet_total = serializers.DecimalField(max_digits=12, decimal_places=2)
    budget_expense = DashboardBudgetExpenseSerializer()
    budget_income = DashboardBudgetIncomeSerializer()
    cash_with_budget = serializers.DecimalField(max_digits=12, decimal_places=2)
    month_comparison = DashboardMonthComparisonSerializer()


class CashFlowReportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    wallet = serializers.UUIDField(required=False)
    cash_flow_item = serializers.UUIDField(required=False)
    limit_by_today = serializers.BooleanField(required=False, default=False)


class BudgetReportQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    project = serializers.UUIDField(required=False)
    cash_flow_item = serializers.UUIDField(required=False)
    limit_by_today = serializers.BooleanField(required=False, default=False)


class CashFlowReportTotalsSerializer(serializers.Serializer):
    income = serializers.DecimalField(max_digits=12, decimal_places=2)
    expense = serializers.DecimalField(max_digits=12, decimal_places=2)


class CashFlowReportMonthSerializer(serializers.Serializer):
    period = serializers.DateTimeField()
    income = serializers.DecimalField(max_digits=12, decimal_places=2)
    expense = serializers.DecimalField(max_digits=12, decimal_places=2)


class CashFlowReportDetailSerializer(serializers.Serializer):
    period = serializers.DateTimeField()
    document_id = serializers.UUIDField(allow_null=True)
    document_type = serializers.CharField(allow_blank=True, allow_null=True)
    wallet_id = serializers.UUIDField(allow_null=True)
    wallet_name = serializers.CharField(allow_blank=True, allow_null=True)
    cash_flow_item_id = serializers.UUIDField(allow_null=True)
    cash_flow_item_name = serializers.CharField(allow_blank=True, allow_null=True)
    income = serializers.DecimalField(max_digits=12, decimal_places=2)
    expense = serializers.DecimalField(max_digits=12, decimal_places=2)


class CashFlowReportResponseSerializer(serializers.Serializer):
    filters = serializers.DictField()
    totals = CashFlowReportTotalsSerializer()
    months = CashFlowReportMonthSerializer(many=True)
    details = CashFlowReportDetailSerializer(many=True)


class BudgetReportTotalsSerializer(serializers.Serializer):
    actual = serializers.DecimalField(max_digits=12, decimal_places=2)
    budget = serializers.DecimalField(max_digits=12, decimal_places=2)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)


class BudgetReportSummarySerializer(serializers.Serializer):
    period = serializers.DateTimeField()
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(allow_blank=True, allow_null=True)
    cash_flow_item_id = serializers.UUIDField(allow_null=True)
    cash_flow_item_name = serializers.CharField(allow_blank=True, allow_null=True)
    actual = serializers.DecimalField(max_digits=12, decimal_places=2)
    budget = serializers.DecimalField(max_digits=12, decimal_places=2)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)


class BudgetReportDetailSerializer(serializers.Serializer):
    period = serializers.DateTimeField()
    document_id = serializers.UUIDField(allow_null=True)
    document_type = serializers.CharField(allow_blank=True, allow_null=True)
    entry_type = serializers.ChoiceField(choices=['budget', 'actual'])
    project_id = serializers.UUIDField(allow_null=True)
    project_name = serializers.CharField(allow_blank=True, allow_null=True)
    cash_flow_item_id = serializers.UUIDField(allow_null=True)
    cash_flow_item_name = serializers.CharField(allow_blank=True, allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class BudgetReportResponseSerializer(serializers.Serializer):
    filters = serializers.DictField()
    totals = BudgetReportTotalsSerializer()
    summary = BudgetReportSummarySerializer(many=True)
    details = BudgetReportDetailSerializer(many=True)
        
class TransferSerializer(BackendManagedIdentityMixin, GraphicContractModelSerializer):
    sync_writable_fields = ('id', 'number')
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.Transfer
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _run_model_clean(self, attrs)
        return attrs


class TransferGraphicSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TransferGraphic
        fields = '__all__'

class BudgetSerializer(BackendManagedIdentityMixin, GraphicContractModelSerializer):
    sync_writable_fields = ('id', 'number')
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.Budget
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _run_model_clean(self, attrs)
        return attrs


class BudgetGraphicSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = models.BudgetGraphic
        fields = '__all__'
        
class AutoPaymentSerializer(BackendManagedIdentityMixin, GraphicContractModelSerializer):
    sync_writable_fields = ('id', 'number')
    id = serializers.UUIDField(read_only=True)
    number = serializers.CharField(read_only=True)  # Автогенерация
    
    class Meta:
        model = models.AutoPayment
        fields = '__all__'
        extra_kwargs = {
            'date_start': {
                'help_text': 'Каноническое поле даты первого автоплатежа. Alias next_date не поддерживается.',
            },
            'amount_month': {
                'help_text': 'Каноническое поле количества месяцев графика. Alias period_days не поддерживается.',
            },
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _run_model_clean(self, attrs)
        return attrs


class AutoPaymentGraphicSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = models.AutoPaymentGraphic
        fields = '__all__'

# Регистры
class FlowOfFundsSerializer(serializers.ModelSerializer):
    """Сериализатор для регистра движения средств"""
    wallet_name = serializers.CharField(source='wallet.name', read_only=True)
    cash_flow_item_name = serializers.CharField(source='cash_flow_item.name', read_only=True)
    type_of_document_display = serializers.CharField(source='get_type_of_document_display', read_only=True)
    
    class Meta:
        model = models.FlowOfFunds
        fields = [
            'id', 'document_id', 'period', 'type_of_document', 'type_of_document_display',
            'wallet', 'wallet_name', 'cash_flow_item', 'cash_flow_item_name', 'amount'
        ]
        read_only_fields = ['id', 'document_id', 'period', 'type_of_document', 'amount']


class BudgetIncomeSerializer(serializers.ModelSerializer):
    """Сериализатор для регистра доходов бюджета"""
    project_name = serializers.CharField(source='project.name', read_only=True)
    cash_flow_item_name = serializers.CharField(source='cash_flow_item.name', read_only=True)
    type_of_document_display = serializers.CharField(source='get_type_of_document_display', read_only=True)
    
    class Meta:
        model = models.BudgetIncome
        fields = [
            'id', 'document_id', 'period', 'type_of_document', 'type_of_document_display',
            'project', 'project_name', 'cash_flow_item', 'cash_flow_item_name', 'amount'
        ]
        read_only_fields = ['id', 'document_id', 'period', 'type_of_document', 'amount']


class BudgetExpenseSerializer(serializers.ModelSerializer):
    """Сериализатор для регистра расходов бюджета"""
    project_name = serializers.CharField(source='project.name', read_only=True)
    cash_flow_item_name = serializers.CharField(source='cash_flow_item.name', read_only=True)
    type_of_document_display = serializers.CharField(source='get_type_of_document_display', read_only=True)
    
    class Meta:
        model = models.BudgetExpense
        fields = [
            'id', 'document_id', 'period', 'type_of_document', 'type_of_document_display',
            'project', 'project_name', 'cash_flow_item', 'cash_flow_item_name', 'amount'
        ]
        read_only_fields = ['id', 'document_id', 'period', 'type_of_document', 'amount']


class OneCSyncOutboxQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=5000, default=100)
    entity_type = serializers.CharField(required=False)


class OneCSyncOutboxSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.OneCSyncOutbox
        fields = [
            'id',
            'entity_type',
            'object_id',
            'route',
            'clear_type',
            'graphics_route',
            'operation',
            'payload',
            'changed_at',
        ]
        read_only_fields = fields


class OneCSyncOutboxListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = OneCSyncOutboxSerializer(many=True)


class OneCSyncOutboxAckRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)


class OneCSyncOutboxAckResponseSerializer(serializers.Serializer):
    deleted_count = serializers.IntegerField()


class AiAssistantExecuteSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, allow_blank=True)
    image = serializers.FileField(required=False)
    wallet = serializers.UUIDField(required=False)
    dry_run = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs.get('text') and not attrs.get('image'):
            raise serializers.ValidationError('Передайте текст, изображение или оба поля.')
        return attrs


class AiAssistantTelegramWebhookSerializer(serializers.Serializer):
    update_id = serializers.IntegerField(required=False)
    message = serializers.DictField(required=False)
    edited_message = serializers.DictField(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        message = attrs.get('message') or attrs.get('edited_message')
        if not message:
            raise serializers.ValidationError('В Telegram update отсутствует message.')
        if not message.get('text') and not message.get('caption') and not message.get('photo'):
            raise serializers.ValidationError('Поддерживаются текст, caption или photo.')
        return attrs


class AiAssistantCreatedObjectSerializer(serializers.Serializer):
    model = serializers.CharField()
    id = serializers.UUIDField()
    number = serializers.CharField()


class AiAssistantBalanceRowSerializer(serializers.Serializer):
    wallet_id = serializers.UUIDField()
    wallet_name = serializers.CharField()
    balance = serializers.DecimalField(max_digits=12, decimal_places=2)


class AiAssistantOptionSerializer(serializers.Serializer):
    index = serializers.IntegerField()
    kind = serializers.CharField()
    id = serializers.UUIDField()
    label = serializers.CharField()


class TelegramLinkTokenResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    expires_at = serializers.DateTimeField()


class AiAssistantResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['created', 'preview', 'needs_confirmation', 'balance', 'duplicate', 'info'])
    intent = serializers.CharField()
    provider = serializers.CharField()
    confidence = serializers.FloatField()
    reply_text = serializers.CharField()
    missing_fields = serializers.ListField(child=serializers.CharField(), required=False)
    created_object = AiAssistantCreatedObjectSerializer(required=False)
    preview = serializers.DictField(required=False)
    balances = AiAssistantBalanceRowSerializer(many=True, required=False)
    options = serializers.DictField(required=False)
    parsed = serializers.DictField(required=False)
