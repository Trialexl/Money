from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import OneCSyncOutbox
from .serializers import (
    OneCSyncOutboxAckRequestSerializer,
    OneCSyncOutboxAckResponseSerializer,
    OneCSyncOutboxListResponseSerializer,
    OneCSyncOutboxQuerySerializer,
    OneCSyncOutboxSerializer,
)
from .sync import get_outbox_payload_map


class OneCSyncOutboxViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAdminUser]

    def _validated_query(self, request):
        serializer = OneCSyncOutboxQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _build_queryset(self, validated_query):
        queryset = OneCSyncOutbox.objects.all().order_by('changed_at', 'id')
        entity_type = validated_query.get('entity_type')
        if entity_type:
            queryset = queryset.filter(entity_type=entity_type)
        return queryset

    @extend_schema(
        parameters=[OneCSyncOutboxQuerySerializer],
        responses={200: OneCSyncOutboxListResponseSerializer},
    )
    def list(self, request):
        validated_query = self._validated_query(request)
        queryset = self._build_queryset(validated_query)
        queue_items = list(queryset[:validated_query['limit']])
        serializer = OneCSyncOutboxSerializer(
            queue_items,
            many=True,
            context={'payload_map': get_outbox_payload_map(queue_items)},
        )
        return Response({
            'count': queryset.count(),
            'results': serializer.data,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        request=OneCSyncOutboxAckRequestSerializer,
        responses={200: OneCSyncOutboxAckResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='ack')
    def ack(self, request):
        serializer = OneCSyncOutboxAckRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        deleted_count, _ = OneCSyncOutbox.objects.filter(
            id__in=serializer.validated_data['ids'],
        ).delete()

        return Response({'deleted_count': deleted_count}, status=status.HTTP_200_OK)
