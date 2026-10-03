import os
import signal
import socket
import threading
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from ops.models import ScheduledJobRun
from ops.scheduler import ensure_scheduled_jobs, run_due_jobs
from ops.scheduler_lease import (
    SchedulerHeartbeat,
    acquire_scheduler_lease,
    release_scheduler_lease,
    set_scheduler_error,
)


class Command(BaseCommand):
    help = 'Запустить long-running loop регламентных заданий с DB-lock и heartbeat.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Пауза между проверками due jobs, в секундах.',
        )
        parser.add_argument(
            '--lease-seconds',
            type=int,
            default=180,
            help='Срок DB-lock планировщика; heartbeat продлевает lock.',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        lease_seconds = options['lease_seconds']
        if interval < 1:
            raise CommandError('--interval must be at least 1 second.')
        if lease_seconds < 3:
            raise CommandError('--lease-seconds must be at least 3 seconds.')

        hostname = socket.gethostname()
        owner_id = f'{hostname}:{os.getpid()}:{uuid.uuid4().hex}'
        acquired, state = acquire_scheduler_lease(
            owner_id=owner_id,
            hostname=hostname,
            pid=os.getpid(),
            interval_seconds=interval,
            lease_seconds=lease_seconds,
        )
        if not acquired:
            owner = state.owner_id or 'unknown'
            raise CommandError(
                f'Scheduler is already running (owner={owner}, heartbeat={state.heartbeat_at}, '
                f'lock_until={state.lock_until}).'
            )

        shutdown_requested = threading.Event()
        heartbeat = SchedulerHeartbeat(owner_id=owner_id, lease_seconds=lease_seconds)
        previous_handlers = {}
        fatal_error = ''

        def request_shutdown(signum, _frame):
            shutdown_requested.set()

        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_shutdown)

        self.stdout.write(
            self.style.SUCCESS(
                f'Scheduler started: owner={owner_id}, interval={interval}s, lease={lease_seconds}s.'
            )
        )
        heartbeat.start()

        try:
            ensure_scheduled_jobs()
            while not shutdown_requested.is_set():
                if heartbeat.lost_event.is_set():
                    fatal_error = 'Scheduler DB lease was lost.'
                    raise CommandError(fatal_error)

                try:
                    close_old_connections()
                    runs = run_due_jobs(
                        triggered_by=ScheduledJobRun.TRIGGER_SCHEDULER,
                        should_stop=shutdown_requested.is_set,
                    )
                    set_scheduler_error(owner_id=owner_id, error='')
                    for run in runs:
                        self.stdout.write(
                            f'{run.job_key}\tstatus={run.status}\t'
                            f'attempts={run.attempts}\tduration_ms={run.duration_ms}'
                        )
                except CommandError:
                    raise
                except Exception as exc:
                    # Transient DB/provider failures must not kill the service;
                    # the lease thread decides when DB connectivity is lost for
                    # long enough that continuing would risk split brain.
                    self.stderr.write(self.style.ERROR(f'Scheduler cycle failed: {exc}'))
                    try:
                        set_scheduler_error(owner_id=owner_id, error=exc)
                    except Exception:
                        pass

                if heartbeat.lost_event.is_set():
                    fatal_error = 'Scheduler DB lease was lost.'
                    raise CommandError(fatal_error)
                shutdown_requested.wait(interval)
        except CommandError:
            raise
        except Exception as exc:
            fatal_error = str(exc)
            raise
        finally:
            # Keep renewing the lease while a SIGTERM-triggered graceful stop
            # waits for the current job, then relinquish it explicitly.
            heartbeat.stop()
            try:
                release_scheduler_lease(owner_id=owner_id, error=fatal_error)
            finally:
                close_old_connections()
                for signum, handler in previous_handlers.items():
                    signal.signal(signum, handler)

        self.stdout.write(self.style.SUCCESS('Scheduler stopped gracefully.'))
