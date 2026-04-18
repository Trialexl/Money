from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0024_telegram_binding_and_pending_confirmation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AiProcessedInput',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source', models.CharField(default='web', max_length=20)),
                ('telegram_update_id', models.BigIntegerField(blank=True, null=True)),
                ('fingerprint', models.CharField(db_index=True, max_length=64)),
                ('normalized_text', models.TextField(blank=True, default='')),
                ('image_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('wallet_id_hint', models.UUIDField(blank=True, null=True)),
                ('status', models.CharField(choices=[('created', 'Created'), ('duplicate', 'Duplicate')], default='created', max_length=20)),
                ('response_payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'telegram_binding',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='processed_inputs',
                        to='money.telegramuserbinding',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='ai_processed_inputs',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': 'Обработанный AI-ввод',
                'verbose_name_plural': 'Обработанные AI-вводы',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='aiprocessedinput',
            index=models.Index(fields=['source', 'fingerprint', 'created_at'], name='m_ai_proc_fp_idx'),
        ),
    ]
