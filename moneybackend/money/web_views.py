from django.views.generic import ListView
from rest_framework import permissions
from .models import Wallet, Expenditure


class WalletListView(ListView):
    """HTML представление списка кошельков"""
    queryset = Wallet.objects.all()
    context_object_name = 'wallets'
    paginate_by = 10
    template_name = 'money/post/list.html'
    

class ExpenditureListView(ListView):
    """HTML представление списка расходов"""
    permission_classes = [permissions.IsAdminUser]
    queryset = Expenditure.objects.all()
    context_object_name = 'Expenditures'
    paginate_by = 200
    template_name = 'money/post/list.html' 