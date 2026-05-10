from django.contrib import admin

from .models import Instrument, InvestmentAccount, InvestmentOperation, InvestmentPortfolio


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'name', 'type', 'quote_currency', 'is_active')
    list_filter = ('type', 'quote_currency', 'is_active')
    search_fields = ('ticker', 'name', 'provider_symbol')


@admin.register(InvestmentPortfolio)
class InvestmentPortfolioAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'base_currency', 'is_default', 'project')
    list_filter = ('is_default', 'base_currency')
    search_fields = ('name', 'user__username', 'user__full_name')


@admin.register(InvestmentAccount)
class InvestmentAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'portfolio', 'type', 'currency', 'hidden')
    list_filter = ('type', 'currency', 'hidden')
    search_fields = ('name', 'portfolio__name')


@admin.register(InvestmentOperation)
class InvestmentOperationAdmin(admin.ModelAdmin):
    list_display = ('number', 'date', 'operation_type', 'instrument', 'quantity', 'amount_rub', 'portfolio', 'account')
    list_filter = ('operation_type', 'instrument', 'posted', 'deleted')
    search_fields = ('number', 'instrument__ticker', 'instrument__name', 'comment')
    autocomplete_fields = ('portfolio', 'account', 'account_to', 'instrument')
