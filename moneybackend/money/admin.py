from django import forms
from django.contrib import admin
from django.forms.models import BaseInlineFormSet
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from . import models


# === СПРАВОЧНИКИ ===

class CashFlowItemAliasInline(admin.TabularInline):
    model = models.CashFlowItemAlias
    extra = 0
    fields = ['alias']


class WalletAliasInline(admin.TabularInline):
    model = models.WalletAlias
    extra = 0
    fields = ['alias']

@admin.register(models.CashFlowItem)
class CashFlowItemAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'parent', 'include_in_budget', 'deleted']
    search_fields = ['code', 'name', 'aliases__alias']
    list_filter = ['include_in_budget', 'deleted', 'parent']
    list_editable = ['include_in_budget']
    ordering = ['code', 'name']
    inlines = [CashFlowItemAliasInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('code', 'name', 'parent')
        }),
        ('Настройки', {
            'fields': ('include_in_budget', 'deleted')
        }),
    )


@admin.register(models.Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'hidden', 'deleted']
    search_fields = ['code', 'name', 'aliases__alias']
    list_filter = ['hidden', 'deleted']
    list_editable = ['hidden']
    ordering = ['code', 'name']
    inlines = [WalletAliasInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('code', 'name')
        }),
        ('Настройки', {
            'fields': ('hidden', 'deleted')
        }),
    )


@admin.register(models.Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'deleted']
    search_fields = ['code', 'name']
    list_filter = ['deleted']
    ordering = ['code', 'name']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('code', 'name')
        }),
        ('Настройки', {
            'fields': ('deleted',)
        }),
    )


# === INLINE КЛАССЫ ДЛЯ ГРАФИКОВ ===

def _raise_expenditure_distribution_admin_error(amount, include_in_budget, graphic_amounts):
    error = models.get_expenditure_distribution_error(
        amount=amount,
        include_in_budget=include_in_budget,
        graphic_amounts=graphic_amounts,
    )
    if error:
        raise forms.ValidationError(error)


class ExpenditureGraphicInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        graphic_amounts = []
        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            amount = form.cleaned_data.get('amount')
            if amount is not None:
                graphic_amounts.append(amount)

        _raise_expenditure_distribution_admin_error(
            amount=self.instance.amount,
            include_in_budget=self.instance.include_in_budget,
            graphic_amounts=graphic_amounts,
        )


class ExpenditureGraphicAdminForm(forms.ModelForm):
    class Meta:
        model = models.ExpenditureGraphic
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        current_document = getattr(self.instance, 'document', None)
        next_document = cleaned_data.get('document') or current_document
        next_amount = cleaned_data.get('amount', getattr(self.instance, 'amount', None))
        current_pk = getattr(self.instance, 'pk', None)

        if current_document and next_document and current_document != next_document:
            _raise_expenditure_distribution_admin_error(
                amount=current_document.amount,
                include_in_budget=current_document.include_in_budget,
                graphic_amounts=current_document.items.exclude(pk=current_pk).values_list('amount', flat=True),
            )

        if next_document is not None:
            sibling_amounts = list(next_document.items.exclude(pk=current_pk).values_list('amount', flat=True))
            if next_amount is not None:
                sibling_amounts.append(next_amount)
            _raise_expenditure_distribution_admin_error(
                amount=next_document.amount,
                include_in_budget=next_document.include_in_budget,
                graphic_amounts=sibling_amounts,
            )

        return cleaned_data

class ExpenditureGraphicInline(admin.TabularInline):
    model = models.ExpenditureGraphic
    formset = ExpenditureGraphicInlineFormSet
    extra = 0
    fields = ['date_start', 'amount']


class TransferGraphicInline(admin.TabularInline):
    model = models.TransferGraphic
    extra = 0
    fields = ['date_start', 'amount']


class BudgetGraphicInline(admin.TabularInline):
    model = models.BudgetGraphic
    extra = 0
    fields = ['date_start', 'amount']


class AutoPaymentGraphicInline(admin.TabularInline):
    model = models.AutoPaymentGraphic
    extra = 0
    fields = ['date_start', 'amount']


class InlineRegisterSyncAdminMixin:
    """После сохранения inline-строк пересобирает регистры документа."""

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        models.sync_document_registers(form.instance)


class GraphicRegisterSyncAdminMixin(admin.ModelAdmin):
    """Поддерживает синхронизацию регистров при прямом редактировании графиков."""

    def sync_related_documents(self, *documents):
        seen_documents = {}
        for document in documents:
            if document is None:
                continue
            seen_documents[document.pk] = document

        for document in seen_documents.values():
            models.sync_document_registers(document)

    def save_model(self, request, obj, form, change):
        previous_document = None
        if change and obj.pk:
            previous_document = obj.__class__.objects.select_related('document').get(pk=obj.pk).document
        super().save_model(request, obj, form, change)
        self.sync_related_documents(previous_document, obj.document)

    def delete_model(self, request, obj):
        document = obj.document
        super().delete_model(request, obj)
        self.sync_related_documents(document)

    def delete_queryset(self, request, queryset):
        documents = {
            obj.document_id: obj.document
            for obj in queryset.select_related('document')
        }
        super().delete_queryset(request, queryset)
        self.sync_related_documents(*documents.values())


class GraphicContractAdminMixin:
    def graphic_contract_display(self, obj):
        if obj is None:
            return '-'

        contract = obj.get_graphic_contract()
        lines = [
            contract['summary'],
            f"Роль шапки: {contract['header_role']}",
            f"Роль графика: {contract['graphics_role']}",
            f"Источник для регистров: {contract['register_source']}",
            f"Рекомендуемое действие API: {contract['recommended_graphic_action']}",
            "Ручное редактирование строк допустимо и не пересчитывает шапку.",
        ]
        return mark_safe('<br>'.join(lines))

    graphic_contract_display.short_description = 'Правило шапки и графика'


# === ДОКУМЕНТЫ ===

@admin.register(models.Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ['number', 'date', 'format_amount', 'wallet', 'cash_flow_item', 'deleted']
    search_fields = ['number', 'comment', 'wallet__name', 'cash_flow_item__name']
    list_filter = ['date', 'wallet', 'cash_flow_item', 'deleted']
    ordering = ['-date']
    readonly_fields = ['id']
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('number', 'date', 'amount', 'comment')
        }),
        ('Связи', {
            'fields': ('wallet', 'cash_flow_item')
        }),
        ('Служебные', {
            'fields': ('id', 'deleted'),
            'classes': ('collapse',)
        }),
    )
    
    def format_amount(self, obj):
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: green;">{} ₽</span>', amount_str)
    format_amount.short_description = 'Сумма'


@admin.register(models.Expenditure)
class ExpenditureAdmin(GraphicContractAdminMixin, InlineRegisterSyncAdminMixin, admin.ModelAdmin):
    list_display = ['number', 'date', 'format_amount', 'wallet', 'cash_flow_item', 'include_in_budget', 'deleted']
    search_fields = ['number', 'comment', 'wallet__name', 'cash_flow_item__name']
    list_filter = ['date', 'wallet', 'cash_flow_item', 'include_in_budget', 'deleted']
    list_editable = ['include_in_budget']
    ordering = ['-date']
    readonly_fields = ['id', 'graphic_contract_display']
    inlines = [ExpenditureGraphicInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('number', 'date', 'amount', 'comment')
        }),
        ('Связи', {
            'fields': ('wallet', 'cash_flow_item')
        }),
        ('Настройки', {
            'fields': ('include_in_budget',)
        }),
        ('Правило графика', {
            'fields': ('graphic_contract_display',)
        }),
        ('Служебные', {
            'fields': ('id', 'deleted'),
            'classes': ('collapse',)
        }),
    )
    
    def format_amount(self, obj):
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: red;">-{} ₽</span>', amount_str)
    format_amount.short_description = 'Сумма'


@admin.register(models.Transfer)
class TransferAdmin(GraphicContractAdminMixin, InlineRegisterSyncAdminMixin, admin.ModelAdmin):
    list_display = ['number', 'date', 'format_amount', 'wallet_out', 'wallet_in', 'cash_flow_item', 'include_in_budget', 'deleted']
    search_fields = ['number', 'comment', 'wallet_out__name', 'wallet_in__name', 'cash_flow_item__name']
    list_filter = ['date', 'wallet_out', 'wallet_in', 'cash_flow_item', 'include_in_budget', 'deleted']
    list_editable = ['include_in_budget']
    ordering = ['-date']
    readonly_fields = ['id', 'graphic_contract_display']
    inlines = [TransferGraphicInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('number', 'date', 'amount', 'comment')
        }),
        ('Кошельки', {
            'fields': ('wallet_out', 'wallet_in')
        }),
        ('Связи', {
            'fields': ('cash_flow_item',)
        }),
        ('Настройки', {
            'fields': ('include_in_budget',)
        }),
        ('Правило графика', {
            'fields': ('graphic_contract_display',)
        }),
        ('Служебные', {
            'fields': ('id', 'deleted'),
            'classes': ('collapse',)
        }),
    )
    
    def format_amount(self, obj):
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: blue;">{} ₽</span>', amount_str)
    format_amount.short_description = 'Сумма'


@admin.register(models.Budget)
class BudgetAdmin(GraphicContractAdminMixin, InlineRegisterSyncAdminMixin, admin.ModelAdmin):
    list_display = ['number', 'date', 'format_amount', 'project', 'cash_flow_item', 'type_of_budget', 'amount_month', 'deleted']
    search_fields = ['number', 'comment', 'project__name', 'cash_flow_item__name']
    list_filter = ['date', 'project', 'cash_flow_item', 'type_of_budget', 'deleted']
    ordering = ['-date']
    readonly_fields = ['id', 'graphic_contract_display']
    inlines = [BudgetGraphicInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('number', 'date', 'amount', 'comment')
        }),
        ('Связи', {
            'fields': ('project', 'cash_flow_item')
        }),
        ('Настройки бюджета', {
            'fields': ('type_of_budget', 'amount_month', 'date_start')
        }),
        ('Правило графика', {
            'fields': ('graphic_contract_display',)
        }),
        ('Служебные', {
            'fields': ('id', 'deleted'),
            'classes': ('collapse',)
        }),
    )
    
    def format_amount(self, obj):
        color = 'green' if obj.type_of_budget else 'red'
        sign = '' if obj.type_of_budget else '-'
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: {};">{}{} ₽</span>', color, sign, amount_str)
    format_amount.short_description = 'Сумма'


@admin.register(models.AutoPayment)
class AutoPaymentAdmin(GraphicContractAdminMixin, InlineRegisterSyncAdminMixin, admin.ModelAdmin):
    list_display = ['number', 'date', 'format_amount', 'is_transfer', 'cash_flow_item', 'amount_month', 'deleted']
    search_fields = ['number', 'comment', 'wallet_in__name', 'wallet_out__name', 'cash_flow_item__name']
    list_filter = ['date', 'is_transfer', 'cash_flow_item', 'deleted']
    list_editable = ['is_transfer']
    ordering = ['-date']
    readonly_fields = ['id', 'graphic_contract_display']
    inlines = [AutoPaymentGraphicInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('number', 'date', 'amount', 'comment', 'date_start')
        }),
        ('Кошельки', {
            'fields': ('wallet_in', 'wallet_out')
        }),
        ('Связи', {
            'fields': ('cash_flow_item',)
        }),
        ('Настройки автоплатежа', {
            'fields': ('amount_month', 'is_transfer')
        }),
        ('Правило графика', {
            'fields': ('graphic_contract_display',)
        }),
        ('Служебные', {
            'fields': ('id', 'deleted'),
            'classes': ('collapse',)
        }),
    )
    
    def format_amount(self, obj):
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: purple;">{} ₽</span>', amount_str)
    format_amount.short_description = 'Сумма'


# === РЕГИСТРЫ ===

@admin.register(models.FlowOfFunds)
class FlowOfFundsAdmin(admin.ModelAdmin):
    list_display = ['period', 'format_amount', 'wallet', 'cash_flow_item', 'type_of_document', 'document_id']
    search_fields = ['wallet__name', 'cash_flow_item__name', 'document_id']
    list_filter = ['period', 'wallet', 'cash_flow_item', 'type_of_document']
    ordering = ['-period']
    readonly_fields = ['id', 'document_id', 'period', 'type_of_document', 'wallet', 'cash_flow_item', 'amount']
    
    def has_add_permission(self, request):
        return False  # Регистры создаются автоматически
    
    def has_change_permission(self, request, obj=None):
        return False  # Регистры не редактируются вручную
    
    def format_amount(self, obj):
        color = 'green' if obj.amount > 0 else 'red'
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: {};">{} ₽</span>', color, amount_str)
    format_amount.short_description = 'Сумма'


@admin.register(models.BudgetIncome)
class BudgetIncomeAdmin(admin.ModelAdmin):
    list_display = ['period', 'format_amount', 'project', 'cash_flow_item', 'type_of_document', 'document_id']
    search_fields = ['project__name', 'cash_flow_item__name', 'document_id']
    list_filter = ['period', 'project', 'cash_flow_item', 'type_of_document']
    ordering = ['-period']
    readonly_fields = ['id', 'document_id', 'period', 'type_of_document', 'project', 'cash_flow_item', 'amount']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def format_amount(self, obj):
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: green;">{} ₽</span>', amount_str)
    format_amount.short_description = 'Сумма'


@admin.register(models.BudgetExpense)
class BudgetExpenseAdmin(admin.ModelAdmin):
    list_display = ['period', 'format_amount', 'project', 'cash_flow_item', 'type_of_document', 'document_id']
    search_fields = ['project__name', 'cash_flow_item__name', 'document_id']
    list_filter = ['period', 'project', 'cash_flow_item', 'type_of_document']
    ordering = ['-period']
    readonly_fields = ['id', 'document_id', 'period', 'type_of_document', 'project', 'cash_flow_item', 'amount']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def format_amount(self, obj):
        amount_str = f"{float(obj.amount):,.2f}"
        return format_html('<span style="color: red;">{} ₽</span>', amount_str)
    format_amount.short_description = 'Сумма'


# === ОТДЕЛЬНАЯ РЕГИСТРАЦИЯ GRAPHIC МОДЕЛЕЙ ===
# (для случаев когда нужен доступ без parent документа)

@admin.register(models.ExpenditureGraphic)
class ExpenditureGraphicAdmin(GraphicRegisterSyncAdminMixin):
    form = ExpenditureGraphicAdminForm
    list_display = ['document', 'date_start', 'amount']
    search_fields = ['document__number', 'document__comment']
    list_filter = ['date_start', 'document__wallet']
    ordering = ['-date_start']

    def delete_model(self, request, obj):
        _raise_expenditure_distribution_admin_error(
            amount=obj.document.amount,
            include_in_budget=obj.document.include_in_budget,
            graphic_amounts=obj.document.items.exclude(pk=obj.pk).values_list('amount', flat=True),
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        documents = {}
        for obj in queryset.select_related('document'):
            document_data = documents.setdefault(
                obj.document_id,
                {'document': obj.document, 'graphic_ids': []},
            )
            document_data['graphic_ids'].append(obj.pk)

        for document_data in documents.values():
            document = document_data['document']
            remaining_amounts = document.items.exclude(
                pk__in=document_data['graphic_ids']
            ).values_list('amount', flat=True)
            _raise_expenditure_distribution_admin_error(
                amount=document.amount,
                include_in_budget=document.include_in_budget,
                graphic_amounts=remaining_amounts,
            )

        super().delete_queryset(request, queryset)


@admin.register(models.TransferGraphic)
class TransferGraphicAdmin(GraphicRegisterSyncAdminMixin):
    list_display = ['document', 'date_start', 'amount']
    search_fields = ['document__number', 'document__comment']
    list_filter = ['date_start']
    ordering = ['-date_start']


@admin.register(models.BudgetGraphic)
class BudgetGraphicAdmin(GraphicRegisterSyncAdminMixin):
    list_display = ['document', 'date_start', 'amount']
    search_fields = ['document__number', 'document__comment']
    list_filter = ['date_start', 'document__project']
    ordering = ['-date_start']


@admin.register(models.AutoPaymentGraphic)
class AutoPaymentGraphicAdmin(GraphicRegisterSyncAdminMixin):
    list_display = ['document', 'date_start', 'amount']
    search_fields = ['document__number', 'document__comment']
    list_filter = ['date_start', 'document__is_transfer']
    ordering = ['-date_start']


@admin.register(models.TelegramUserBinding)
class TelegramUserBindingAdmin(admin.ModelAdmin):
    list_display = ['telegram_username', 'telegram_user_id', 'telegram_chat_id', 'user', 'linked_at']
    search_fields = ['telegram_username', 'telegram_user_id', 'user__username', 'user__full_name']
    autocomplete_fields = ['user']
    ordering = ['telegram_username', 'telegram_user_id']


@admin.register(models.AiPendingConfirmation)
class AiPendingConfirmationAdmin(admin.ModelAdmin):
    list_display = ['source', 'intent', 'user', 'telegram_binding', 'is_active', 'updated_at']
    search_fields = ['intent', 'user__username', 'telegram_binding__telegram_username']
    list_filter = ['source', 'intent', 'is_active']
    autocomplete_fields = ['user', 'telegram_binding']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-updated_at']


@admin.register(models.AiProcessedInput)
class AiProcessedInputAdmin(admin.ModelAdmin):
    list_display = ['source', 'user', 'telegram_binding', 'status', 'telegram_update_id', 'created_at']
    search_fields = ['normalized_text', 'telegram_binding__telegram_username', 'user__username', 'fingerprint']
    list_filter = ['source', 'status']
    autocomplete_fields = ['user', 'telegram_binding']
    readonly_fields = ['created_at', 'fingerprint', 'normalized_text', 'image_sha256', 'response_payload']
    ordering = ['-created_at']


@admin.register(models.TelegramLinkToken)
class TelegramLinkTokenAdmin(admin.ModelAdmin):
    list_display = ['code', 'user', 'is_used', 'expires_at', 'created_at']
    search_fields = ['code', 'user__username']
    list_filter = ['is_used']
    autocomplete_fields = ['user', 'used_by_binding']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(models.AiAuditLog)
class AiAuditLogAdmin(admin.ModelAdmin):
    list_display = ['source', 'provider', 'user', 'telegram_binding', 'created_at']
    search_fields = ['input_text', 'provider', 'user__username', 'telegram_binding__telegram_username']
    list_filter = ['source', 'provider']
    autocomplete_fields = ['user', 'telegram_binding', 'processed_input', 'pending_confirmation']
    readonly_fields = [
        'created_at',
        'input_text',
        'image_sha256',
        'raw_provider_payload',
        'normalized_payload',
        'final_response_payload',
        'confirmed_fields',
    ]
    ordering = ['-created_at']


@admin.register(models.OneCSyncOutbox)
class OneCSyncOutboxAdmin(admin.ModelAdmin):
    list_display = ['entity_type', 'route', 'operation', 'object_id', 'changed_at']
    search_fields = ['entity_type', 'route', 'operation', 'object_id']
    list_filter = ['entity_type', 'route', 'operation', 'changed_at']
    ordering = ['-changed_at', '-id']
    readonly_fields = [
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

    fieldsets = (
        ('Queue', {
            'fields': ('id', 'entity_type', 'object_id', 'operation')
        }),
        ('Routes', {
            'fields': ('route', 'clear_type', 'graphics_route')
        }),
        ('Payload', {
            'fields': ('payload',)
        }),
        ('Status', {
            'fields': ('changed_at',)
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
