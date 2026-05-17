from django.conf import settings
from django.http import QueryDict
from rest_framework import viewsets, permissions, status
from .serializers import (
    CustomUserSerializer,
    ProfileCustomUserSerializer,
    LogoutRequestSerializer,
    LogoutResponseSerializer,
    LogoutErrorSerializer,
)
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema


def _cookie_max_age(lifetime):
    return int(lifetime.total_seconds())


def _set_auth_cookie(response, name, value, max_age, *, http_only=True):
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=settings.AUTH_COOKIE_PATH,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=http_only,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


def set_auth_cookies(response):
    access = response.data.get('access') if isinstance(response.data, dict) else None
    refresh = response.data.get('refresh') if isinstance(response.data, dict) else None

    if access:
        _set_auth_cookie(
            response,
            settings.AUTH_ACCESS_COOKIE_NAME,
            access,
            _cookie_max_age(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME']),
        )
        _set_auth_cookie(
            response,
            settings.AUTH_SESSION_COOKIE_NAME,
            '1',
            _cookie_max_age(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']),
            http_only=False,
        )

    if refresh:
        _set_auth_cookie(
            response,
            settings.AUTH_REFRESH_COOKIE_NAME,
            refresh,
            _cookie_max_age(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']),
        )


def clear_auth_cookies(response):
    for cookie_name in [
        settings.AUTH_ACCESS_COOKIE_NAME,
        settings.AUTH_REFRESH_COOKIE_NAME,
        settings.AUTH_SESSION_COOKIE_NAME,
    ]:
        response.delete_cookie(
            cookie_name,
            path=settings.AUTH_COOKIE_PATH,
            samesite=settings.AUTH_COOKIE_SAMESITE,
        )


class CookieTokenObtainPairView(TokenObtainPairView):
    """JWT login that also writes browser tokens to HttpOnly cookies."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        set_auth_cookies(response)
        return response


class CookieTokenRefreshView(TokenRefreshView):
    """Refresh JWT using request body for API clients or refresh cookie for web."""

    def post(self, request, *args, **kwargs):
        if not request.data.get('refresh'):
            data = request.data.copy() if isinstance(request.data, QueryDict) else dict(request.data)
            data['refresh'] = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME, '')
            request._full_data = data
        response = super().post(request, *args, **kwargs)
        set_auth_cookies(response)
        return response


class CustomUserViewSet(viewsets.ModelViewSet):
    queryset = get_user_model().objects.all()
    serializer_class = CustomUserSerializer
    permission_classes = [permissions.IsAdminUser]


class ProfileCustomUserViewSet(viewsets.ModelViewSet):
    """
    ViewSet для работы с профилем текущего пользователя.
    Доступен только аутентифицированным пользователям.
    """
    serializer_class = ProfileCustomUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = get_user_model().objects.all()

    def get_queryset(self):
        """Возвращает только текущего пользователя"""
        return self.queryset.filter(pk=self.request.user.pk)

    def list(self, request, *args, **kwargs):
        """Возвращает профиль текущего пользователя"""
        try:
            profile = self.get_queryset().get(pk=request.user.pk)
            serializer = self.get_serializer(profile)
            return Response({'user': serializer.data}, status=status.HTTP_200_OK)
        except get_user_model().DoesNotExist:
            return Response({'error': 'User profile not found'}, status=status.HTTP_404_NOT_FOUND)


class LogoutView(APIView):
    """
    Endpoint для выхода из системы.
    Добавляет refresh токен в черный список.
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=LogoutRequestSerializer,
        responses={
            200: LogoutResponseSerializer,
            400: LogoutErrorSerializer,
        },
    )
    def post(self, request):
        """Выход из системы с добавлением токена в blacklist"""
        response = Response({
            'message': 'Successfully logged out',
            'detail': 'Authentication cookies have been cleared',
        }, status=status.HTTP_200_OK)
        clear_auth_cookies(response)

        try:
            refresh_token = request.data.get('refresh') or request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
            if not refresh_token:
                return response
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            response.data['detail'] = 'Refresh token has been blacklisted and cookies have been cleared'
            return response
            
        except Exception as e:
            response.data = {
                'error': 'Invalid refresh token',
                'detail': str(e)
            }
            response.status_code = status.HTTP_400_BAD_REQUEST
            return response
