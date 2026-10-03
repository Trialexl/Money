import logging
import threading
from datetime import timedelta
from time import monotonic

from django.db import DatabaseError, close_old_connections, transaction
from django.utils import timezone

from .models import SchedulerState


logger = logging.getLogger(__name__)
SCHEDULER_KEY = 'default'


def acquire_scheduler_lease(*, owner_id, hostname, pid, interval_seconds, lease_seconds):
    now = timezone.now()
    with transaction.atomic():
        state, _created = SchedulerState.objects.select_for_update().get_or_create(
            singleton_key=SCHEDULER_KEY,
        )
        if state.owner_id and state.owner_id != owner_id and state.lock_until and state.lock_until > now:
            return False, state

        state.owner_id = owner_id
        state.hostname = hostname
        state.pid = pid
        state.status = SchedulerState.STATUS_RUNNING
        state.interval_seconds = interval_seconds
        state.started_at = now
        state.heartbeat_at = now
        state.lock_until = now + timedelta(seconds=lease_seconds)
        state.stopped_at = None
        state.last_error = ''
        state.save()
        return True, state


def renew_scheduler_lease(*, owner_id, lease_seconds):
    now = timezone.now()
    return SchedulerState.objects.filter(
        singleton_key=SCHEDULER_KEY,
        owner_id=owner_id,
        status=SchedulerState.STATUS_RUNNING,
    ).update(
        heartbeat_at=now,
        lock_until=now + timedelta(seconds=lease_seconds),
        updated_at=now,
    ) == 1


def set_scheduler_error(*, owner_id, error):
    SchedulerState.objects.filter(
        singleton_key=SCHEDULER_KEY,
        owner_id=owner_id,
    ).update(last_error=str(error), updated_at=timezone.now())


def release_scheduler_lease(*, owner_id, error=''):
    now = timezone.now()
    status = SchedulerState.STATUS_ERROR if error else SchedulerState.STATUS_STOPPED
    return SchedulerState.objects.filter(
        singleton_key=SCHEDULER_KEY,
        owner_id=owner_id,
    ).update(
        owner_id='',
        status=status,
        heartbeat_at=now,
        lock_until=None,
        stopped_at=now,
        last_error=str(error),
        updated_at=now,
    ) == 1


class SchedulerHeartbeat:
    def __init__(self, *, owner_id, lease_seconds):
        self.owner_id = owner_id
        self.lease_seconds = lease_seconds
        self.interval_seconds = min(30, max(1, lease_seconds // 3))
        self.stop_event = threading.Event()
        self.lost_event = threading.Event()
        self.last_success_at = monotonic()
        self.thread = threading.Thread(
            target=self._run,
            name='scheduler-heartbeat',
            daemon=True,
        )

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self):
        close_old_connections()
        try:
            while not self.stop_event.wait(self.interval_seconds):
                try:
                    close_old_connections()
                    renewed = renew_scheduler_lease(
                        owner_id=self.owner_id,
                        lease_seconds=self.lease_seconds,
                    )
                    if not renewed:
                        logger.error('Scheduler DB lease is owned by another process.')
                        self.lost_event.set()
                        return
                    self.last_success_at = monotonic()
                except DatabaseError:
                    logger.exception('Could not update scheduler heartbeat.')
                    if monotonic() - self.last_success_at >= self.lease_seconds:
                        self.lost_event.set()
                        return
                except Exception:
                    logger.exception('Scheduler heartbeat stopped unexpectedly.')
                    self.lost_event.set()
                    return
        finally:
            close_old_connections()
