from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from .data_health import generate_data_health_report


class TechnicalHealthViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def list(self, request):
        try:
            detail_limit = int(request.query_params.get('limit', '50'))
        except (TypeError, ValueError):
            return Response({'limit': 'Укажите целое число.'}, status=status.HTTP_400_BAD_REQUEST)
        if detail_limit < 0 or detail_limit > 200:
            return Response({'limit': 'Значение должно быть от 0 до 200.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(generate_data_health_report(detail_limit=detail_limit))
