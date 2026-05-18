from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .common_views import (
    CatalogPageNumberPagination,
    FinancialOperationListFilteringMixin,
    OneCSyncSoftDeleteCompatibilityMixin,
)
from .models import (
    AutoPayment,
    AutoPaymentGraphic,
    Budget,
    BudgetGraphic,
    Expenditure,
    ExpenditureGraphic,
    Receipt,
    Transfer,
    TransferGraphic,
    sync_document_registers,
)
from .serializers import (
    AutoPaymentGraphicSerializer,
    AutoPaymentListQuerySerializer,
    AutoPaymentSerializer,
    BudgetGraphicSerializer,
    BudgetListQuerySerializer,
    BudgetSerializer,
    ExpenditureGraphicSerializer,
    ExpenditureListQuerySerializer,
    ExpenditureSerializer,
    GraphicReplaceSerializer,
    PlanningGraphicGenerationSerializer,
    ReceiptListQuerySerializer,
    ReceiptSerializer,
    TransferGraphicSerializer,
    TransferListQuerySerializer,
    TransferSerializer,
)


class ReceiptViewSet(OneCSyncSoftDeleteCompatibilityMixin, FinancialOperationListFilteringMixin, viewsets.ModelViewSet):
    """
    API для управления приходами денежных средств.

    При создании/обновлении автоматически обновляются регистры.
    """

    queryset = Receipt.objects.all()
    serializer_class = ReceiptSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = CatalogPageNumberPagination
    list_query_serializer_class = ReceiptListQuerySerializer
    search_fields = ('comment', 'number', 'wallet__name', 'cash_flow_item__name')

    def get_queryset(self):
        """Фильтрация неудаленных записей."""
        queryset = self.filter_soft_deleted(
            self.queryset.all().select_related('wallet', 'cash_flow_item')
        ).order_by('-date', '-id')

        if getattr(self, 'action', None) != 'list':
            return queryset

        filters = self.get_list_filters()
        queryset = self.apply_search_filter(queryset, filters.get('search'))

        if filters.get('wallet'):
            queryset = queryset.filter(wallet_id=filters['wallet'])
        if filters.get('cash_flow_item'):
            queryset = queryset.filter(cash_flow_item_id=filters['cash_flow_item'])
        if filters.get('date_from'):
            queryset = queryset.filter(date__date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(date__date__lte=filters['date_to'])
        if filters.get('amount_min') is not None:
            queryset = queryset.filter(amount__gte=filters['amount_min'])
        if filters.get('amount_max') is not None:
            queryset = queryset.filter(amount__lte=filters['amount_max'])

        return queryset

    @extend_schema(
        parameters=[ReceiptListQuerySerializer],
        responses={200: ReceiptSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров."""
        instance.deleted = True
        instance.save()


class DocumentGraphicReplacementMixin:
    """Атомарно заменяет все строки графика документа без пересчета шапки."""

    graphic_model = None
    graphic_serializer_class = None

    def get_graphic_replace_serializer(self, *args, **kwargs):
        kwargs.setdefault('context', self.get_serializer_context())
        return GraphicReplaceSerializer(*args, **kwargs)

    def validate_graphic_replacement(self, document, rows):
        return None

    @action(detail=True, methods=['put'], url_path='replace-graphics')
    def replace_graphics(self, request, pk=None):
        """Атомарно заменяет все строки графика документа без пересчета шапки."""
        document = self.get_object()
        payload = self.get_graphic_replace_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        rows = payload.validated_data['rows']
        self.validate_graphic_replacement(document, rows)

        with transaction.atomic():
            document.items.all().delete()
            self.graphic_model.objects.bulk_create([
                self.graphic_model(
                    document=document,
                    date_start=row['date_start'],
                    amount=row['amount'],
                )
                for row in rows
            ])
            sync_document_registers(document)

        return Response(
            self.graphic_serializer_class(
                document.items.order_by('date_start'),
                many=True,
                context=self.get_serializer_context(),
            ).data,
            status=status.HTTP_200_OK,
        )


class ExpenditureViewSet(OneCSyncSoftDeleteCompatibilityMixin, FinancialOperationListFilteringMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления расходами денежных средств.

    Поддерживает фильтрацию по включению в бюджет.
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """

    queryset = Expenditure.objects.all()
    serializer_class = ExpenditureSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = ExpenditureGraphic
    graphic_serializer_class = ExpenditureGraphicSerializer
    pagination_class = CatalogPageNumberPagination
    list_query_serializer_class = ExpenditureListQuerySerializer
    search_fields = ('comment', 'number', 'wallet__name', 'cash_flow_item__name')

    def get_queryset(self):
        """Фильтрация с возможностью фильтра по бюджету."""
        queryset = self.filter_soft_deleted(
            self.queryset.all().select_related('wallet', 'cash_flow_item')
        ).order_by('-date', '-id')

        if getattr(self, 'action', None) != 'list':
            return queryset

        filters = self.get_list_filters()
        queryset = self.apply_search_filter(queryset, filters.get('search'))

        if filters.get('wallet'):
            queryset = queryset.filter(wallet_id=filters['wallet'])
        if filters.get('cash_flow_item'):
            queryset = queryset.filter(cash_flow_item_id=filters['cash_flow_item'])
        if filters.get('date_from'):
            queryset = queryset.filter(date__date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(date__date__lte=filters['date_to'])
        if filters.get('amount_min') is not None:
            queryset = queryset.filter(amount__gte=filters['amount_min'])
        if filters.get('amount_max') is not None:
            queryset = queryset.filter(amount__lte=filters['amount_max'])

        if 'include_in_budget' in self.request.query_params:
            include_in_budget = filters.get('include_in_budget')
            if include_in_budget is not None:
                queryset = queryset.filter(include_in_budget=include_in_budget)

        return queryset

    @extend_schema(
        parameters=[ExpenditureListQuerySerializer],
        responses={200: ExpenditureSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров."""
        instance.deleted = True
        instance.save()

    def validate_graphic_replacement(self, document, rows):
        """Атомарно заменяет весь график бюджетного распределения расхода."""
        error = document.get_distribution_validation_error(
            graphic_amounts=[row['amount'] for row in rows]
        )
        if error:
            raise serializers.ValidationError(error)


class TransferViewSet(OneCSyncSoftDeleteCompatibilityMixin, FinancialOperationListFilteringMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления переводами между кошельками.

    Поддерживает валидацию кошельков и автообновление регистров.
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """

    queryset = Transfer.objects.all()
    serializer_class = TransferSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = TransferGraphic
    graphic_serializer_class = TransferGraphicSerializer
    pagination_class = CatalogPageNumberPagination
    list_query_serializer_class = TransferListQuerySerializer
    search_fields = ('comment', 'number', 'wallet_out__name', 'wallet_in__name')

    def get_queryset(self):
        """Фильтрация неудаленных переводов."""
        queryset = self.filter_soft_deleted(
            self.queryset.all().select_related('wallet_out', 'wallet_in')
        ).order_by('-date', '-id')

        if getattr(self, 'action', None) != 'list':
            return queryset

        filters = self.get_list_filters()
        queryset = self.apply_search_filter(queryset, filters.get('search'))

        if filters.get('wallet_from'):
            queryset = queryset.filter(wallet_out_id=filters['wallet_from'])
        if filters.get('wallet_to'):
            queryset = queryset.filter(wallet_in_id=filters['wallet_to'])
        if filters.get('date_from'):
            queryset = queryset.filter(date__date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(date__date__lte=filters['date_to'])
        if filters.get('amount_min') is not None:
            queryset = queryset.filter(amount__gte=filters['amount_min'])
        if filters.get('amount_max') is not None:
            queryset = queryset.filter(amount__lte=filters['amount_max'])

        return queryset

    @extend_schema(
        parameters=[TransferListQuerySerializer],
        responses={200: TransferSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Валидация при создании перевода."""
        wallet_in = serializer.validated_data.get('wallet_in')
        wallet_out = serializer.validated_data.get('wallet_out')

        if wallet_in == wallet_out:
            raise serializers.ValidationError(
                'Входящий и исходящий кошелек не могут быть одинаковыми'
            )

        serializer.save()

    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров."""
        instance.deleted = True
        instance.save()


class PlanningGraphicGenerationMixin:
    """Штатная синхронизация шапки и графика для плановых документов."""

    graphic_model = None
    graphic_serializer_class = None

    def get_graphic_generation_serializer(self, *args, **kwargs):
        kwargs.setdefault('context', self.get_serializer_context())
        return PlanningGraphicGenerationSerializer(*args, **kwargs)

    @action(detail=True, methods=['post'], url_path='generate-graphics')
    def generate_graphics(self, request, pk=None):
        document = self.get_object()
        payload = self.get_graphic_generation_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        updated_fields = []
        for field_name in ('amount', 'amount_month', 'date_start'):
            if field_name in payload.validated_data:
                setattr(document, field_name, payload.validated_data[field_name])
                updated_fields.append(field_name)

        try:
            rows, updated_amount = document.build_generated_graphic_rows(
                monthly_amount=payload.validated_data.get('monthly_amount'),
                without_rounding=payload.validated_data.get('without_rounding', False),
            )
            document.amount = updated_amount
            if 'amount' not in updated_fields:
                updated_fields.append('amount')
            document.clean()
        except DjangoValidationError as exc:
            if hasattr(exc, 'message_dict'):
                raise serializers.ValidationError(exc.message_dict)
            raise serializers.ValidationError(exc.messages)

        with transaction.atomic():
            document.__class__.objects.filter(pk=document.pk).update(
                **{field_name: getattr(document, field_name) for field_name in updated_fields}
            )
            document.items.all().delete()
            self.graphic_model.objects.bulk_create([
                self.graphic_model(
                    document=document,
                    date_start=period,
                    amount=amount,
                )
                for period, amount in rows
            ])
            sync_document_registers(document)

        return Response(
            {
                'document': self.get_serializer(document).data,
                'rows': self.graphic_serializer_class(
                    document.items.order_by('date_start'),
                    many=True,
                    context=self.get_serializer_context(),
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class BudgetViewSet(OneCSyncSoftDeleteCompatibilityMixin, PlanningGraphicGenerationMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления бюджетами.

    Поддерживает фильтрацию по типу бюджета (доход/расход).
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """

    queryset = Budget.objects.all()
    serializer_class = BudgetSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = BudgetGraphic
    graphic_serializer_class = BudgetGraphicSerializer

    def get_queryset(self):
        """Фильтрация с возможностью фильтра по типу."""
        queryset = self.filter_soft_deleted(self.queryset.all()).order_by('-date', '-id')

        budget_type = self.request.query_params.get('type')
        if budget_type == 'income':
            queryset = queryset.filter(type_of_budget=True)
        elif budget_type == 'expense':
            queryset = queryset.filter(type_of_budget=False)

        return queryset

    @extend_schema(
        parameters=[BudgetListQuerySerializer],
        responses={200: BudgetSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров."""
        instance.deleted = True
        instance.save()


class AutoPaymentViewSet(OneCSyncSoftDeleteCompatibilityMixin, PlanningGraphicGenerationMixin, DocumentGraphicReplacementMixin, viewsets.ModelViewSet):
    """
    API для управления автоматическими платежами.

    Поддерживает фильтрацию по типу (transfer/payment).
    В ответе `graphic_contract` явно фиксирует роль шапки и строк графика.
    """

    queryset = AutoPayment.objects.all()
    serializer_class = AutoPaymentSerializer
    permission_classes = [permissions.IsAdminUser]
    graphic_model = AutoPaymentGraphic
    graphic_serializer_class = AutoPaymentGraphicSerializer

    def get_queryset(self):
        """Фильтрация с возможностью фильтра по типу."""
        queryset = self.filter_soft_deleted(self.queryset.all()).order_by('-date', '-id')

        is_transfer = self.request.query_params.get('is_transfer')
        if is_transfer is not None:
            queryset = queryset.filter(is_transfer=is_transfer.lower() == 'true')

        return queryset

    @extend_schema(
        parameters=[AutoPaymentListQuerySerializer],
        responses={200: AutoPaymentSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Мягкое удаление с очисткой регистров."""
        instance.deleted = True
        instance.save()
