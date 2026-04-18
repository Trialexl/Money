from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('money', '0021_defaults_for_planning_documents'),
    ]

    operations = [
        migrations.CreateModel(
            name='OneCSyncOutbox',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('entity_type', models.CharField(max_length=50)),
                ('object_id', models.UUIDField()),
                ('route', models.CharField(max_length=100)),
                ('clear_type', models.CharField(blank=True, default='', max_length=100)),
                ('graphics_route', models.CharField(blank=True, default='', max_length=100)),
                ('operation', models.CharField(choices=[('upsert', 'Upsert'), ('delete', 'Delete')], default='upsert', max_length=20)),
                ('payload', models.JSONField(default=dict)),
                ('changed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('acknowledged_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Исходящая очередь синхронизации 1С',
                'verbose_name_plural': 'Исходящая очередь синхронизации 1С',
                'ordering': ['changed_at', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='onecsyncoutbox',
            constraint=models.UniqueConstraint(fields=('entity_type', 'object_id'), name='money_onec_sync_outbox_unique_object'),
        ),
    ]
