# Generated manually for the FrontMoney MCP OAuth gateway.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='McpOAuthClient',
            fields=[
                ('client_id', models.CharField(max_length=255, primary_key=True, serialize=False)),
                ('metadata', models.JSONField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='McpOAuthAuthorizationRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('redirect_uri', models.TextField()),
                ('redirect_uri_provided_explicitly', models.BooleanField(default=True)),
                ('state', models.TextField(blank=True, null=True)),
                ('scopes', models.JSONField(default=list)),
                ('code_challenge', models.CharField(max_length=128)),
                ('resource', models.TextField()),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='mcp_gateway.mcpoauthclient')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='McpOAuthAuthorizationCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code_hash', models.CharField(max_length=64, unique=True)),
                ('redirect_uri', models.TextField()),
                ('redirect_uri_provided_explicitly', models.BooleanField(default=True)),
                ('scopes', models.JSONField(default=list)),
                ('code_challenge', models.CharField(max_length=128)),
                ('resource', models.TextField()),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('consumed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='mcp_gateway.mcpoauthclient')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='McpOAuthToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('access_token_hash', models.CharField(max_length=64, unique=True)),
                ('refresh_token_hash', models.CharField(max_length=64, unique=True)),
                ('scopes', models.JSONField(default=list)),
                ('resource', models.TextField()),
                ('access_expires_at', models.DateTimeField(db_index=True)),
                ('refresh_expires_at', models.DateTimeField(db_index=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='mcp_gateway.mcpoauthclient')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
