from django.db.models import Sum
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import BudgetExpense, BudgetIncome, FlowOfFunds
from .serializers import (
    BudgetExpenseSerializer,
    BudgetIncomeSerializer,
    FlowOfFundsSerializer,
)


TRANSFER_DOCUMENT_TYPE = 2


class FlowOfFundsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра движения средств.

    Только для чтения. Поддерживает фильтрацию по кошельку, статье, периоду.
    """

    queryset = FlowOfFunds.objects.all()
    serializer_class = FlowOfFundsSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        """Фильтрация по параметрам запроса."""
        queryset = self.queryset.select_related('wallet', 'cash_flow_item')

        wallet_id = self.request.query_params.get('wallet')
        if wallet_id:
            queryset = queryset.filter(wallet_id=wallet_id)

        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)

        return queryset.order_by('-period')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по движению средств."""
        queryset = self.get_queryset().filter(cash_flow_item__isnull=False).exclude(
            type_of_document=TRANSFER_DOCUMENT_TYPE
        )

        wallet_summary = queryset.values('wallet__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'total_amount': float(total_amount),
            'wallet_summary': list(wallet_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count(),
        })


class BudgetIncomeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра доходов бюджета.

    Только для чтения. Поддерживает фильтрацию по проекту, статье, периоду.
    """

    queryset = BudgetIncome.objects.all()
    serializer_class = BudgetIncomeSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        """Фильтрация по параметрам запроса."""
        queryset = self.queryset.select_related('project', 'cash_flow_item')

        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)

        return queryset.order_by('-period')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по доходам бюджета."""
        queryset = self.get_queryset()

        project_summary = queryset.values('project__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'total_income': float(total_amount),
            'project_summary': list(project_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count(),
        })


class BudgetExpenseViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API для чтения регистра расходов бюджета.

    Только для чтения. Поддерживает фильтрацию по проекту, статье, периоду.
    """

    queryset = BudgetExpense.objects.all()
    serializer_class = BudgetExpenseSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        """Фильтрация по параметрам запроса."""
        queryset = self.queryset.select_related('project', 'cash_flow_item')

        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        cash_flow_item_id = self.request.query_params.get('cash_flow_item')
        if cash_flow_item_id:
            queryset = queryset.filter(cash_flow_item_id=cash_flow_item_id)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(period__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(period__lte=date_to)

        return queryset.order_by('-period')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Получить агрегированную сводку по расходам бюджета."""
        queryset = self.get_queryset()

        project_summary = queryset.values('project__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        item_summary = queryset.values('cash_flow_item__name').annotate(
            total_amount=Sum('amount')
        ).order_by('-total_amount')
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'total_expense': float(total_amount),
            'project_summary': list(project_summary),
            'item_summary': list(item_summary),
            'record_count': queryset.count(),
        })
