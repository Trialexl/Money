"""lk URL Configuration

Центральная конфигурация маршрутов проекта.
Разделены HTML и API маршруты для лучшей организации.
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from django.shortcuts import redirect


def home_redirect(request):
    """Перенаправление с главной страницы на админку"""
    return redirect('admin:index')


urlpatterns = [
    # Главная страница
    path('', home_redirect, name='home'),
    
    # Административная панель
    path('admin/', admin.site.urls),
    
    # Web интерфейс (HTML views)
    path('web/', include('money.web_urls')),
    
    # API endpoints (версия 1)
    path('api/v1/', include(('lk.api_urls', 'api'), namespace='api_v1')),

    # OpenAPI schema and docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
