from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0026_ai_audit_and_telegram_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiprocessedinput',
            name='semantic_fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddIndex(
            model_name='aiprocessedinput',
            index=models.Index(fields=['source', 'semantic_fingerprint', 'created_at'], name='m_ai_proc_sem_idx'),
        ),
    ]
