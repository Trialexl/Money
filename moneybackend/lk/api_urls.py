from django.urls import path, include
from .health import HealthCheckView
from users.views import CookieTokenObtainPairView, CookieTokenRefreshView

app_name = 'api'

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),

    # Аутентификация
    path('auth/token/', CookieTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    
    # Приложения
    path('', include('money.api_urls')),
    path('investment/', include('investments.api_urls')),
    path('', include('users.api_urls')),
]
