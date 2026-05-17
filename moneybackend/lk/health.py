from django.db import connection
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(auth=[], responses={200: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT})
    def get(self, request):
        checks = {
            'database': 'unknown',
        }
        http_status = status.HTTP_200_OK

        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            checks['database'] = 'ok'
        except Exception:
            checks['database'] = 'error'
            http_status = status.HTTP_503_SERVICE_UNAVAILABLE

        return Response({
            'status': 'ok' if http_status == status.HTTP_200_OK else 'error',
            'checks': checks,
        }, status=http_status)
