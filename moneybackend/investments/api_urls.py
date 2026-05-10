from django.urls import include, path
from rest_framework import routers

from . import views


router = routers.DefaultRouter()
router.register(r'instruments', views.InstrumentViewSet, basename='investment-instruments')
router.register(r'prices', views.InstrumentPriceSnapshotViewSet, basename='investment-prices')
router.register(r'portfolios', views.InvestmentPortfolioViewSet, basename='investment-portfolios')
router.register(r'accounts', views.InvestmentAccountViewSet, basename='investment-accounts')
router.register(r'operations', views.InvestmentOperationViewSet, basename='investment-operations')
router.register(r'portfolio-overview', views.InvestmentOverviewViewSet, basename='investment-portfolio-overview')

app_name = 'investments_api'

urlpatterns = [
    path('', include(router.urls)),
]
