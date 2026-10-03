from django.db import migrations, models


def create_scheduler_state(apps, schema_editor):
    SchedulerState = apps.get_model('ops', 'SchedulerState')
    SchedulerState.objects.get_or_create(singleton_key='default')


class Migration(migrations.Migration):

    dependencies = [
        ('ops', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SchedulerState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_key', models.CharField(default='default', max_length=32, unique=True)),
                ('owner_id', models.CharField(blank=True, max_length=200)),
                ('hostname', models.CharField(blank=True, max_length=255)),
                ('pid', models.PositiveIntegerField(blank=True, null=True)),
                ('status', models.CharField(choices=[('running', 'Работает'), ('stopped', 'Остановлен'), ('error', 'Ошибка')], default='stopped', max_length=20)),
                ('interval_seconds', models.PositiveIntegerField(default=60)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('lock_until', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('stopped_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Состояние планировщика',
                'verbose_name_plural': 'Состояние планировщика',
            },
        ),
        migrations.RunPython(create_scheduler_state, migrations.RunPython.noop),
    ]
