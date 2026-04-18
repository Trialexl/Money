from django.urls import path
from . import web_views

app_name = 'money_web'
 
urlpatterns = [
    path('', web_views.ExpenditureListView.as_view(), name='expenditures_list'),
    path('wallets/', web_views.WalletListView.as_view(), name='wallets_list'),
] 