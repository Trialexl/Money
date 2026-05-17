from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ScheduledJobState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_key', models.CharField(max_length=120, unique=True)),
                ('title', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('enabled', models.BooleanField(default=True)),
                ('interval_minutes', models.PositiveIntegerField(default=1440)),
                ('run_at_time', models.TimeField(blank=True, null=True)),
                ('timeout_seconds', models.PositiveIntegerField(default=300)),
                ('max_retries', models.PositiveIntegerField(default=1)),
                ('retry_delay_seconds', models.PositiveIntegerField(default=10)),
                ('next_run_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('lock_until', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('last_status', models.CharField(choices=[('never', 'Никогда не запускалось'), ('running', 'Выполняется'), ('success', 'Успешно'), ('warning', 'Предупреждение'), ('error', 'Ошибка'), ('skipped', 'Пропущено')], default='never', max_length=20)),
                ('last_started_at', models.DateTimeField(blank=True, null=True)),
                ('last_finished_at', models.DateTimeField(blank=True, null=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('last_duration_ms', models.PositiveIntegerField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('last_result', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Регламентное задание',
                'verbose_name_plural': 'Регламентные задания',
                'ordering': ['job_key'],
            },
        ),
        migrations.CreateModel(
            name='ScheduledJobRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_key', models.CharField(db_index=True, max_length=120)),
                ('status', models.CharField(choices=[('never', 'Никогда не запускалось'), ('running', 'Выполняется'), ('success', 'Успешно'), ('warning', 'Предупреждение'), ('error', 'Ошибка'), ('skipped', 'Пропущено')], max_length=20)),
                ('triggered_by', models.CharField(choices=[('scheduler', 'Планировщик'), ('manual', 'Ручной запуск')], default='scheduler', max_length=20)),
                ('started_at', models.DateTimeField(db_index=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('duration_ms', models.PositiveIntegerField(blank=True, null=True)),
                ('attempts', models.PositiveIntegerField(default=1)),
                ('error', models.TextField(blank=True)),
                ('result', models.JSONField(blank=True, default=dict)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='runs', to='ops.scheduledjobstate')),
            ],
            options={
                'verbose_name': 'Запуск регламентного задания',
                'verbose_name_plural': 'Запуски регламентных заданий',
                'ordering': ['-started_at'],
            },
        ),
    ]
