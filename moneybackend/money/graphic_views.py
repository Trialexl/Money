from rest_framework import serializers, viewsets

from .models import (
    AutoPaymentGraphic,
    BudgetGraphic,
    ExpenditureGraphic,
    TransferGraphic,
    sync_document_registers,
)
from .permissions import IsAdminOrReadOnly
from .serializers import (
    AutoPaymentGraphicSerializer,
    BudgetGraphicSerializer,
    ExpenditureGraphicSerializer,
    TransferGraphicSerializer,
)


class GraphicRegisterSyncMixin:
    """Пересобирает регистры родительского документа после изменения строк графика."""

    def sync_parent_documents(self, *documents):
        seen_documents = {}
        for document in documents:
            if document is None:
                continue
            seen_documents[document.pk] = document

        for document in seen_documents.values():
            sync_document_registers(document)

    def perform_create(self, serializer):
        instance = serializer.save()
        self.sync_parent_documents(instance.document)

    def perform_update(self, serializer):
        previous_document = serializer.instance.document
        instance = serializer.save()
        self.sync_parent_documents(previous_document, instance.document)

    def perform_destroy(self, instance):
        document = instance.document
        instance.delete()
        self.sync_parent_documents(document)


class ExpenditureGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """
    API для управления графиками планирования расходов.

    Изменение строки графика пересобирает бюджетные регистры родительского расхода,
    но не пересчитывает сумму в шапке документа. Для полной замены графика
    штатным способом считается `PUT /expenditures/{id}/replace-graphics/`.
    """

    queryset = ExpenditureGraphic.objects.all()
    serializer_class = ExpenditureGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация по документу."""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')

    def perform_destroy(self, instance):
        error = instance.document.get_distribution_validation_error(
            graphic_amounts=instance.document.items.exclude(pk=instance.pk).values_list('amount', flat=True)
        )
        if error:
            raise serializers.ValidationError(error)
        super().perform_destroy(instance)


class TransferGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """API для управления графиками планирования переводов."""

    queryset = TransferGraphic.objects.all()
    serializer_class = TransferGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация по документу."""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')


class BudgetGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """API для управления графиками планирования бюджетов."""

    queryset = BudgetGraphic.objects.all()
    serializer_class = BudgetGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация по документу."""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')


class AutoPaymentGraphicViewSet(GraphicRegisterSyncMixin, viewsets.ModelViewSet):
    """API для управления графиками планирования автоплатежей."""

    queryset = AutoPaymentGraphic.objects.all()
    serializer_class = AutoPaymentGraphicSerializer
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Фильтрация по документу."""
        queryset = self.queryset.all()
        document_id = self.request.query_params.get('document')
        if document_id:
            queryset = queryset.filter(document=document_id)
        return queryset.order_by('date_start')
