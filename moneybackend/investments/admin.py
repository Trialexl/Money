from django.contrib import admin

from .models import (
    FxRateSnapshot,
    Instrument,
    InstrumentPriceSnapshot,
    InvestmentAccount,
    InvestmentOperation,
    InvestmentPortfolio,
    InvestmentTargetAllocation,
)


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'name', 'type', 'quote_currency', 'is_active')
    list_filter = ('type', 'quote_currency', 'is_active')
    search_fields = ('ticker', 'name', 'provider_symbol')


@admin.register(InstrumentPriceSnapshot)
class InstrumentPriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ('instrument', 'captured_at', 'price', 'price_currency', 'fx_rate_to_rub', 'price_rub', 'source')
    list_filter = ('price_currency', 'source', 'captured_at')
    search_fields = ('instrument__ticker', 'instrument__name', 'source')
    autocomplete_fields = ('instrument',)


@admin.register(FxRateSnapshot)
class FxRateSnapshotAdmin(admin.ModelAdmin):
    list_display = ('base_currency', 'quote_currency', 'captured_at', 'rate', 'source')
    list_filter = ('base_currency', 'quote_currency', 'source', 'captured_at')
    search_fields = ('base_currency', 'quote_currency', 'source')


@admin.register(InvestmentPortfolio)
class InvestmentPortfolioAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'base_currency', 'is_default', 'project')
    list_filter = ('is_default', 'base_currency')
    search_fields = ('name', 'user__username', 'user__full_name')


@admin.register(InvestmentTargetAllocation)
class InvestmentTargetAllocationAdmin(admin.ModelAdmin):
    list_display = ('portfolio', 'instrument', 'target_percent', 'tolerance_percent')
    list_filter = ('portfolio', 'instrument')
    search_fields = ('portfolio__name', 'instrument__ticker', 'instrument__name')
    autocomplete_fields = ('portfolio', 'instrument')


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
