from django.shortcuts import render
from rest_framework import viewsets, permissions,exceptions,status
from .serializers import (
    CustomUserSerializer,
    ProfileCustomUserSerializer,
    LogoutRequestSerializer,
    LogoutResponseSerializer,
    LogoutErrorSerializer,
)
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema



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
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=LogoutRequestSerializer,
        responses={
            200: LogoutResponseSerializer,
            400: LogoutErrorSerializer,
        },
    )
    def post(self, request):
        """Выход из системы с добавлением токена в blacklist"""
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response({
                    'error': 'Refresh token is required',
                    'detail': 'Please provide refresh token in request body'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            return Response({
                'message': 'Successfully logged out',
                'detail': 'Refresh token has been blacklisted'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': 'Invalid refresh token',
                'detail': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

