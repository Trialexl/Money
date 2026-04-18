from django.urls import path, include
from . import views
from rest_framework import routers


# API Router для всех ViewSets
router = routers.DefaultRouter()

# Справочники
router.register(r'cash-flow-items', views.CashFlowItemViewSet, basename='cash-flow-items')
router.register(r'wallets', views.WalletViewSet, basename='wallets')
router.register(r'projects', views.ProjectViewSet, basename='projects')
router.register(r'dashboard', views.DashboardViewSet, basename='dashboard')
router.register(r'reports', views.ReportViewSet, basename='reports')

# Финансовые операции
router.register(r'receipts', views.ReceiptViewSet, basename='receipts')
router.register(r'expenditures', views.ExpenditureViewSet, basename='expenditures')
router.register(r'transfers', views.TransferViewSet, basename='transfers')
router.register(r'budgets', views.BudgetViewSet, basename='budgets')
router.register(r'auto-payments', views.AutoPaymentViewSet, basename='auto-payments')

# Регистры (только для чтения)
router.register(r'flow-of-funds', views.FlowOfFundsViewSet, basename='flow-of-funds')
router.register(r'budget-income', views.BudgetIncomeViewSet, basename='budget-income')
router.register(r'budget-expense', views.BudgetExpenseViewSet, basename='budget-expense')

# Графики планирования
router.register(r'expenditure-graphics', views.ExpenditureGraphicViewSet, basename='expenditure-graphics')
router.register(r'transfer-graphics', views.TransferGraphicViewSet, basename='transfer-graphics')
router.register(r'budget-graphics', views.BudgetGraphicViewSet, basename='budget-graphics')
router.register(r'auto-payment-graphics', views.AutoPaymentGraphicViewSet, basename='auto-payment-graphics')

app_name = 'money_api'

urlpatterns = [
    path('', include(router.urls)),
    path(
        'ai/execute/',
        views.AiAssistantViewSet.as_view({'post': 'execute'}),
        name='ai-execute',
    ),
    path(
        'ai/telegram-webhook/',
        views.AiAssistantViewSet.as_view({'post': 'telegram_webhook'}),
        name='ai-telegram-webhook',
    ),
    path(
        'ai/telegram-link-token/',
        views.AiAssistantViewSet.as_view({'post': 'telegram_link_token'}),
        name='ai-telegram-link-token',
    ),
    path(
        'onec-sync/outbox/',
        views.OneCSyncOutboxViewSet.as_view({'get': 'list'}),
        name='onec-sync-outbox',
    ),
    path(
        'onec-sync/outbox/ack/',
        views.OneCSyncOutboxViewSet.as_view({'post': 'ack'}),
        name='onec-sync-outbox-ack',
    ),
]
