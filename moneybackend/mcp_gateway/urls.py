from django.urls import path

from .views import oauth_consent


app_name = 'mcp_gateway'

urlpatterns = [
    path('consent/', oauth_consent, name='consent'),
]
