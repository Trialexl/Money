# Backwards compatibility - redirect to api_urls
from django.urls import path, include

urlpatterns = [
    path('', include('users.api_urls')),
]
