from django.contrib import admin, messages

from .models import ScheduledJobRun, ScheduledJobState
from .scheduler import execute_job


@admin.action(description='Запустить выбранные задания сейчас')
def run_selected_jobs(modeladmin, request, queryset):
    for job in queryset:
        try:
            run = execute_job(job.job_key, triggered_by=ScheduledJobRun.TRIGGER_MANUAL, force=True)
            messages.info(request, f'{job.job_key}: {run.status}; {_result_summary(run.result)}')
        except Exception as exc:
            messages.error(request, f'{job.job_key}: {exc}')


def _result_summary(result):
    if not isinstance(result, dict) or not result:
        return 'result=-'
    keys = ('created', 'updated', 'failed')
    parts = [f'{key}={result[key]}' for key in keys if key in result]
    if parts:
        return ', '.join(parts)
    if 'status' in result:
        return f'status={result["status"]}'
    if 'error' in result:
        return f'error={result["error"]}'
    return 'result=ok'


@admin.register(ScheduledJobState)
class ScheduledJobStateAdmin(admin.ModelAdmin):
    list_display = [
        'job_key',
        'title',
        'enabled',
        'next_run_at',
        'last_status',
        'last_started_at',
        'last_finished_at',
        'last_duration_ms',
        'last_result_summary',
    ]
    list_filter = ['enabled', 'last_status']
    search_fields = ['job_key', 'title', 'description']
    readonly_fields = [
        'job_key',
        'title',
        'description',
        'last_status',
        'last_started_at',
        'last_finished_at',
        'last_success_at',
        'last_duration_ms',
        'last_error',
        'last_result',
        'lock_until',
        'created_at',
        'updated_at',
    ]
    fieldsets = (
        ('Задание', {
            'fields': ('job_key', 'title', 'description', 'enabled')
        }),
        ('Расписание', {
            'fields': ('interval_minutes', 'run_at_time', 'next_run_at')
        }),
        ('Надежность', {
            'fields': ('timeout_seconds', 'max_retries', 'retry_delay_seconds', 'lock_until')
        }),
        ('Последний запуск', {
            'fields': (
                'last_status',
                'last_started_at',
                'last_finished_at',
                'last_success_at',
                'last_duration_ms',
                'last_error',
                'last_result',
            )
        }),
        ('Служебное', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    actions = [run_selected_jobs]

    @admin.display(description='Результат')
    def last_result_summary(self, obj):
        return _result_summary(obj.last_result)


@admin.register(ScheduledJobRun)
class ScheduledJobRunAdmin(admin.ModelAdmin):
    list_display = ['job_key', 'status', 'triggered_by', 'started_at', 'finished_at', 'duration_ms', 'attempts']
    list_filter = ['status', 'triggered_by', 'job_key']
    search_fields = ['job_key', 'error']
    readonly_fields = [
        'job',
        'job_key',
        'status',
        'triggered_by',
        'started_at',
        'finished_at',
        'duration_ms',
        'attempts',
        'error',
        'result',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
