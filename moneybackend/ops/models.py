from django.db import models


class ScheduledJobState(models.Model):
    STATUS_NEVER = 'never'
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_WARNING = 'warning'
    STATUS_ERROR = 'error'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_NEVER, 'Никогда не запускалось'),
        (STATUS_RUNNING, 'Выполняется'),
        (STATUS_SUCCESS, 'Успешно'),
        (STATUS_WARNING, 'Предупреждение'),
        (STATUS_ERROR, 'Ошибка'),
        (STATUS_SKIPPED, 'Пропущено'),
    ]

    job_key = models.CharField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    interval_minutes = models.PositiveIntegerField(default=1440)
    run_at_time = models.TimeField(null=True, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=300)
    max_retries = models.PositiveIntegerField(default=1)
    retry_delay_seconds = models.PositiveIntegerField(default=10)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lock_until = models.DateTimeField(null=True, blank=True, db_index=True)
    last_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEVER)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    last_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['job_key']
        verbose_name = 'Регламентное задание'
        verbose_name_plural = 'Регламентные задания'

    def __str__(self):
        return f'{self.job_key}: {self.title}'


class ScheduledJobRun(models.Model):
    TRIGGER_SCHEDULER = 'scheduler'
    TRIGGER_MANUAL = 'manual'
    TRIGGER_CHOICES = [
        (TRIGGER_SCHEDULER, 'Планировщик'),
        (TRIGGER_MANUAL, 'Ручной запуск'),
    ]

    job = models.ForeignKey(ScheduledJobState, related_name='runs', on_delete=models.CASCADE)
    job_key = models.CharField(max_length=120, db_index=True)
    status = models.CharField(max_length=20, choices=ScheduledJobState.STATUS_CHOICES)
    triggered_by = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default=TRIGGER_SCHEDULER)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=1)
    error = models.TextField(blank=True)
    result = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Запуск регламентного задания'
        verbose_name_plural = 'Запуски регламентных заданий'

    def __str__(self):
        return f'{self.job_key}: {self.status} at {self.started_at}'
