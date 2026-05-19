import json
import signal
import threading
import time as time_module
import urllib.request
from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import monotonic

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from investments.services import (
    get_market_data_health,
    rebuild_portfolio_snapshots,
    refresh_fx_rate_snapshots,
    refresh_price_snapshots,
)
from lk.admin_backup import create_database_backup, list_backup_files, restore_check_backup

from .models import ScheduledJobRun, ScheduledJobState


class JobTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class JobResult:
    payload: dict
    status: str = ScheduledJobState.STATUS_SUCCESS


@dataclass(frozen=True)
class ScheduledJobDefinition:
    key: str
    title: str
    description: str
    task: Callable
    interval_minutes: int = 1440
    run_at_time: time | None = None
    enabled: bool = True
    timeout_seconds: int = 300
    max_retries: int = 1
    retry_delay_seconds: int = 10


def _json_safe(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


@contextmanager
def _time_limit(seconds: int):
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def handler(_signum, _frame):
        raise JobTimeoutError(f'Job exceeded timeout: {seconds}s')

    try:
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(seconds)
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


def _next_run_after(job: ScheduledJobState, now=None):
    now = now or timezone.now()
    interval = timedelta(minutes=job.interval_minutes or 1440)
    if job.run_at_time is None:
        return now + interval

    candidate = timezone.make_aware(datetime.combine(now.date(), job.run_at_time), timezone.get_current_timezone())
    while candidate <= now:
        candidate += interval
    return candidate


def _initial_next_run(definition: ScheduledJobDefinition, now=None):
    now = now or timezone.now()
    return now


def ensure_scheduled_jobs(definitions=None):
    definitions = definitions or get_job_definitions()
    states = []
    for definition in definitions:
        state, created = ScheduledJobState.objects.get_or_create(
            job_key=definition.key,
            defaults={
                'title': definition.title,
                'description': definition.description,
                'enabled': definition.enabled,
                'interval_minutes': definition.interval_minutes,
                'run_at_time': definition.run_at_time,
                'timeout_seconds': definition.timeout_seconds,
                'max_retries': definition.max_retries,
                'retry_delay_seconds': definition.retry_delay_seconds,
                'next_run_at': _initial_next_run(definition),
            },
        )
        updates = []
        for field, value in {
            'title': definition.title,
            'description': definition.description,
            'timeout_seconds': definition.timeout_seconds,
            'max_retries': definition.max_retries,
            'retry_delay_seconds': definition.retry_delay_seconds,
        }.items():
            if getattr(state, field) != value:
                setattr(state, field, value)
                updates.append(field)
        if not created and state.next_run_at is None:
            state.next_run_at = _initial_next_run(definition)
            updates.append('next_run_at')
        if updates:
            state.save(update_fields=[*updates, 'updated_at'])
        states.append(state)
    return states


def due_scheduled_jobs(definitions=None, now=None):
    now = now or timezone.now()
    definitions_by_key = {definition.key: definition for definition in (definitions or get_job_definitions())}
    ensure_scheduled_jobs(definitions_by_key.values())
    states = (
        ScheduledJobState.objects
        .filter(job_key__in=definitions_by_key.keys(), enabled=True)
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        .order_by('next_run_at', 'job_key')
    )
    return [(state, definitions_by_key[state.job_key]) for state in states]


def run_due_jobs(*, force=False, job_key=None, dry_run=False, triggered_by=ScheduledJobRun.TRIGGER_SCHEDULER):
    definitions = get_job_definitions()
    definitions_by_key = {definition.key: definition for definition in definitions}
    ensure_scheduled_jobs(definitions)

    if job_key:
        definition = definitions_by_key.get(job_key)
        if definition is None:
            raise ValueError(f'Unknown scheduled job: {job_key}')
        state = ScheduledJobState.objects.get(job_key=job_key)
        selected = [(state, definition)]
    elif force:
        selected = [
            (ScheduledJobState.objects.get(job_key=definition.key), definition)
            for definition in definitions
            if ScheduledJobState.objects.get(job_key=definition.key).enabled
        ]
    else:
        selected = due_scheduled_jobs(definitions)

    if dry_run:
        return [{
            'job_key': state.job_key,
            'title': state.title,
            'next_run_at': state.next_run_at,
            'due': force or job_key or state.next_run_at is None or state.next_run_at <= timezone.now(),
        } for state, _definition in selected]

    return [
        execute_job(state.job_key, triggered_by=triggered_by, force=force or bool(job_key))
        for state, _definition in selected
    ]


def execute_job(job_key: str, *, triggered_by=ScheduledJobRun.TRIGGER_SCHEDULER, force=False):
    definitions_by_key = {definition.key: definition for definition in get_job_definitions()}
    definition = definitions_by_key.get(job_key)
    if definition is None:
        raise ValueError(f'Unknown scheduled job: {job_key}')

    now = timezone.now()
    with transaction.atomic():
        state = ScheduledJobState.objects.select_for_update().get(job_key=job_key)
        if not force and state.lock_until and state.lock_until > now:
            run = ScheduledJobRun.objects.create(
                job=state,
                job_key=state.job_key,
                status=ScheduledJobState.STATUS_SKIPPED,
                triggered_by=triggered_by,
                started_at=now,
                finished_at=now,
                duration_ms=0,
                result={'reason': 'locked', 'lock_until': state.lock_until.isoformat()},
            )
            return run

        state.lock_until = now + timedelta(seconds=state.timeout_seconds + 60)
        state.last_status = ScheduledJobState.STATUS_RUNNING
        state.last_started_at = now
        state.last_error = ''
        state.save(update_fields=['lock_until', 'last_status', 'last_started_at', 'last_error', 'updated_at'])
        run = ScheduledJobRun.objects.create(
            job=state,
            job_key=state.job_key,
            status=ScheduledJobState.STATUS_RUNNING,
            triggered_by=triggered_by,
            started_at=now,
        )

    attempts = 0
    started_monotonic = monotonic()
    result_payload = {}
    result_status = ScheduledJobState.STATUS_SUCCESS
    error_message = ''
    max_attempts = max(1, state.max_retries + 1)

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            with _time_limit(state.timeout_seconds):
                raw_result = definition.task()
            if isinstance(raw_result, JobResult):
                result_payload = raw_result.payload
                result_status = raw_result.status
            else:
                result_payload = raw_result if isinstance(raw_result, dict) else {'result': raw_result}
            error_message = ''
            break
        except Exception as exc:
            error_message = str(exc)
            result_status = ScheduledJobState.STATUS_ERROR
            result_payload = {'error': error_message}
            if attempt < max_attempts and state.retry_delay_seconds:
                time_module.sleep(state.retry_delay_seconds)

    finished_at = timezone.now()
    duration_ms = int((monotonic() - started_monotonic) * 1000)
    result_payload = _json_safe(result_payload)

    with transaction.atomic():
        state = ScheduledJobState.objects.select_for_update().get(pk=state.pk)
        state.lock_until = None
        state.last_status = result_status
        state.last_finished_at = finished_at
        state.last_duration_ms = duration_ms
        state.last_error = error_message
        state.last_result = result_payload
        if result_status in {ScheduledJobState.STATUS_SUCCESS, ScheduledJobState.STATUS_WARNING}:
            state.last_success_at = finished_at
            state.next_run_at = _next_run_after(state, finished_at)
        else:
            state.next_run_at = finished_at + timedelta(seconds=state.retry_delay_seconds or 60)
        state.save()

        run.status = result_status
        run.finished_at = finished_at
        run.duration_ms = duration_ms
        run.attempts = attempts
        run.error = error_message
        run.result = result_payload
        run.save(update_fields=['status', 'finished_at', 'duration_ms', 'attempts', 'error', 'result'])

    if result_status == ScheduledJobState.STATUS_ERROR:
        _notify_job_failure(job_key, error_message)

    return run


def _notify_job_failure(job_key: str, error_message: str) -> None:
    webhook_url = getattr(settings, 'SCHEDULED_JOBS_ALERT_WEBHOOK_URL', '')
    if not webhook_url:
        return

    payload = json.dumps({
        'text': f'Money scheduled job failed: {job_key}: {error_message}',
    }).encode('utf-8')
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(request, timeout=5).read()
    except Exception:
        pass


def job_refresh_fx_rates():
    return _market_refresh_job_result(refresh_fx_rate_snapshots())


def job_refresh_prices():
    return _market_refresh_job_result(refresh_price_snapshots())


def _market_refresh_job_result(result):
    failed = int(result.get('failed') or 0)
    changed = int(result.get('created') or 0) + int(result.get('updated') or 0)
    if failed and not changed:
        return JobResult(payload=result, status=ScheduledJobState.STATUS_ERROR)
    if failed:
        return JobResult(payload=result, status=ScheduledJobState.STATUS_WARNING)
    return JobResult(payload=result, status=ScheduledJobState.STATUS_SUCCESS)


def job_market_health():
    result = get_market_data_health(max_age_days=getattr(settings, 'SCHEDULED_JOBS_MARKET_MAX_AGE_DAYS', 2))
    status = ScheduledJobState.STATUS_SUCCESS if result['status'] == 'ok' else ScheduledJobState.STATUS_WARNING
    return JobResult(payload=result, status=status)


def job_rebuild_today_snapshots():
    today = timezone.localdate()
    return rebuild_portfolio_snapshots(date_from=today, date_to=today, price_max_age_days=0)


def job_create_backup():
    backup = create_database_backup()
    return {
        'name': backup.name,
        'path': str(backup.path),
        'size': backup.size,
        'created_at': backup.created_at,
    }


def job_restore_check_latest_backup():
    backups = list_backup_files()
    if not backups:
        raise RuntimeError('No backup files found.')
    latest = backups[0]
    restore_check_backup(latest.name)
    return {
        'name': latest.name,
        'path': str(latest.path),
        'size': latest.size,
    }


def job_cleanup_old_backups():
    backup_dir = Path(settings.BACKUP_DIR)
    retention_days = getattr(settings, 'BACKUP_RETENTION_DAYS', 30)
    cutoff = date.today() - timedelta(days=retention_days)
    deleted = []
    if not backup_dir.exists():
        return {'deleted': deleted, 'retention_days': retention_days}

    for file_path in backup_dir.glob('*.gz'):
        if file_path.suffixes[-2:] not in (['.dump', '.gz'], ['.sql', '.gz']):
            continue
        modified_date = datetime.fromtimestamp(file_path.stat().st_mtime).date()
        if modified_date < cutoff:
            deleted.append({'name': file_path.name, 'size': file_path.stat().st_size})
            file_path.unlink()
    return {'deleted': deleted, 'retention_days': retention_days}


def get_job_definitions():
    return [
        ScheduledJobDefinition(
            key='backup.create',
            title='Backup базы',
            description='Создать PostgreSQL backup и выгрузить во внешний storage, если target настроен.',
            task=job_create_backup,
            run_at_time=time(3, 30),
            timeout_seconds=900,
            max_retries=1,
            retry_delay_seconds=60,
        ),
        ScheduledJobDefinition(
            key='backup.restore_check',
            title='Проверка восстановления backup',
            description='Восстановить последний backup во временную БД и удалить ее после проверки.',
            task=job_restore_check_latest_backup,
            run_at_time=time(3, 40),
            timeout_seconds=900,
            max_retries=1,
            retry_delay_seconds=60,
        ),
        ScheduledJobDefinition(
            key='backup.cleanup',
            title='Очистка старых backup',
            description='Удалить локальные backup-файлы старше retention policy.',
            task=job_cleanup_old_backups,
            interval_minutes=10080,
            run_at_time=time(3, 45),
            timeout_seconds=300,
            max_retries=0,
            retry_delay_seconds=60,
        ),
        ScheduledJobDefinition(
            key='investment.fx_refresh',
            title='Обновление FX-курсов',
            description='Обновить USD/EUR/RUB cross-rates через configured FX provider.',
            task=job_refresh_fx_rates,
            run_at_time=time(8, 0),
            timeout_seconds=300,
            max_retries=2,
            retry_delay_seconds=30,
        ),
        ScheduledJobDefinition(
            key='investment.price_refresh',
            title='Обновление цен инструментов',
            description='Обновить цены активных финансовых инструментов через configured price provider.',
            task=job_refresh_prices,
            run_at_time=time(8, 5),
            timeout_seconds=600,
            max_retries=2,
            retry_delay_seconds=30,
        ),
        ScheduledJobDefinition(
            key='investment.market_health',
            title='Контроль свежести рыночных данных',
            description='Проверить свежесть price/fx snapshots после обновления курсов.',
            task=job_market_health,
            run_at_time=time(8, 10),
            timeout_seconds=120,
            max_retries=0,
            retry_delay_seconds=60,
        ),
        ScheduledJobDefinition(
            key='investment.snapshots_today',
            title='Снимок портфеля за сегодня',
            description='Пересчитать дневные snapshots портфелей за текущую дату.',
            task=job_rebuild_today_snapshots,
            run_at_time=time(8, 15),
            timeout_seconds=600,
            max_retries=1,
            retry_delay_seconds=60,
        ),
    ]
