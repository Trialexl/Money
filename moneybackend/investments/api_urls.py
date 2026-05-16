from django.urls import include, path
from rest_framework import routers

from . import views


router = routers.DefaultRouter()
router.register(r'instruments', views.InstrumentViewSet, basename='investment-instruments')
router.register(r'prices', views.InstrumentPriceSnapshotViewSet, basename='investment-prices')
router.register(r'fx-rates', views.FxRateSnapshotViewSet, basename='investment-fx-rates')
router.register(r'portfolios', views.InvestmentPortfolioViewSet, basename='investment-portfolios')
router.register(r'target-allocations', views.InvestmentTargetAllocationViewSet, basename='investment-target-allocations')
router.register(r'accounts', views.InvestmentAccountViewSet, basename='investment-accounts')
router.register(r'operations', views.InvestmentOperationViewSet, basename='investment-operations')
router.register(r'portfolio-overview', views.InvestmentOverviewViewSet, basename='investment-portfolio-overview')
router.register(r'market-health', views.InvestmentMarketDataHealthViewSet, basename='investment-market-health')

app_name = 'investments_api'

urlpatterns = [
    path('', include(router.urls)),
]
