from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0025_ai_processed_input'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='aipendingconfirmation',
            name='confirmation_history',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='aipendingconfirmation',
            name='options_payload',
            field=models.JSONField(default=dict),
        ),
        migrations.CreateModel(
            name='TelegramLinkToken',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code', models.CharField(max_length=12, unique=True)),
                ('is_used', models.BooleanField(default=False)),
                ('expires_at', models.DateTimeField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='telegram_link_tokens',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    'used_by_binding',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='used_link_tokens',
                        to='money.telegramuserbinding',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Токен привязки Telegram',
                'verbose_name_plural': 'Токены привязки Telegram',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='AiAuditLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source', models.CharField(default='web', max_length=20)),
                ('provider', models.CharField(blank=True, default='', max_length=50)),
                ('input_text', models.TextField(blank=True, default='')),
                ('image_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('raw_provider_payload', models.JSONField(default=dict)),
                ('normalized_payload', models.JSONField(default=dict)),
                ('final_response_payload', models.JSONField(default=dict)),
                ('confirmed_fields', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'pending_confirmation',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='audit_logs',
                        to='money.aipendingconfirmation',
                    ),
                ),
                (
                    'processed_input',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='audit_logs',
                        to='money.aiprocessedinput',
                    ),
                ),
                (
                    'telegram_binding',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='audit_logs',
                        to='money.telegramuserbinding',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='ai_audit_logs',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'AI аудит',
                'verbose_name_plural': 'AI аудит',
                'ordering': ['-created_at'],
            },
        ),
    ]
