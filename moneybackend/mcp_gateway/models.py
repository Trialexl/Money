import uuid

from django.conf import settings
from django.db import models


class McpOAuthClient(models.Model):
    client_id = models.CharField(max_length=255, primary_key=True)
    metadata = models.JSONField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class McpOAuthAuthorizationRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(McpOAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=True)
    state = models.TextField(null=True, blank=True)
    scopes = models.JSONField(default=list)
    code_challenge = models.CharField(max_length=128)
    resource = models.TextField()
    expires_at = models.DateTimeField(db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class McpOAuthAuthorizationCode(models.Model):
    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(McpOAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    redirect_uri = models.TextField()
    redirect_uri_provided_explicitly = models.BooleanField(default=True)
    scopes = models.JSONField(default=list)
    code_challenge = models.CharField(max_length=128)
    resource = models.TextField()
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class McpOAuthToken(models.Model):
    access_token_hash = models.CharField(max_length=64, unique=True)
    refresh_token_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(McpOAuthClient, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    scopes = models.JSONField(default=list)
    resource = models.TextField()
    access_expires_at = models.DateTimeField(db_index=True)
    refresh_expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
