from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0023_wallet_and_cash_flow_aliases'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramUserBinding',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('telegram_user_id', models.BigIntegerField(unique=True)),
                ('telegram_chat_id', models.BigIntegerField()),
                ('telegram_username', models.CharField(blank=True, default='', max_length=150)),
                ('first_name', models.CharField(blank=True, default='', max_length=150)),
                ('last_name', models.CharField(blank=True, default='', max_length=150)),
                ('linked_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'user',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='telegram_bindings',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Привязка Telegram пользователя',
                'verbose_name_plural': 'Привязки Telegram пользователей',
                'ordering': ['telegram_username', 'telegram_user_id'],
            },
        ),
        migrations.CreateModel(
            name='AiPendingConfirmation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source', models.CharField(choices=[('web', 'Web'), ('telegram', 'Telegram')], default='telegram', max_length=20)),
                ('intent', models.CharField(max_length=50)),
                ('provider', models.CharField(blank=True, default='', max_length=50)),
                ('normalized_payload', models.JSONField(default=dict)),
                ('missing_fields', models.JSONField(default=list)),
                ('prompt_text', models.CharField(blank=True, default='', max_length=255)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'telegram_binding',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='pending_confirmations',
                        to='money.telegramuserbinding',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='ai_pending_confirmations',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Ожидающее AI-уточнение',
                'verbose_name_plural': 'Ожидающие AI-уточнения',
                'ordering': ['-updated_at'],
            },
        ),
    ]
