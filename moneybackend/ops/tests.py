from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import ScheduledJobRun, ScheduledJobState
from .scheduler import ScheduledJobDefinition, ensure_scheduled_jobs, run_due_jobs


class ScheduledJobsTests(TestCase):
    def test_ensure_scheduled_jobs_creates_registry_state(self):
        definition = ScheduledJobDefinition(
            key='test.registry',
            title='Registry job',
            description='Test job',
            task=lambda: {'ok': True},
            interval_minutes=60,
            retry_delay_seconds=0,
        )

        states = ensure_scheduled_jobs([definition])

        self.assertEqual(len(states), 1)
        state = ScheduledJobState.objects.get(job_key='test.registry')
        self.assertEqual(state.title, 'Registry job')
        self.assertTrue(state.enabled)
        self.assertIsNotNone(state.next_run_at)

    def test_run_due_jobs_records_success_and_next_run(self):
        definition = ScheduledJobDefinition(
            key='test.success',
            title='Success job',
            description='Test job',
            task=lambda: {'created': 1},
            interval_minutes=60,
            retry_delay_seconds=0,
        )
        ensure_scheduled_jobs([definition])
        state = ScheduledJobState.objects.get(job_key='test.success')
        state.next_run_at = timezone.now() - timedelta(minutes=1)
        state.save(update_fields=['next_run_at'])

        from . import scheduler
        original_get_job_definitions = scheduler.get_job_definitions
        scheduler.get_job_definitions = lambda: [definition]
        try:
            runs = run_due_jobs(force=False, dry_run=False, triggered_by=ScheduledJobRun.TRIGGER_SCHEDULER)
        finally:
            scheduler.get_job_definitions = original_get_job_definitions

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, ScheduledJobState.STATUS_SUCCESS)
        state.refresh_from_db()
        self.assertEqual(state.last_result, {'created': 1})
        self.assertEqual(state.last_status, ScheduledJobState.STATUS_SUCCESS)
        self.assertIsNotNone(state.next_run_at)

    def test_one_failed_job_does_not_stop_next_job(self):
        calls = []

        def failed_task():
            calls.append('failed')
            raise RuntimeError('provider failed')

        def ok_task():
            calls.append('ok')
            return {'ok': True}

        definitions = [
            ScheduledJobDefinition(
                key='test.failed',
                title='Failed job',
                description='Test job',
                task=failed_task,
                interval_minutes=60,
                max_retries=0,
                retry_delay_seconds=0,
            ),
            ScheduledJobDefinition(
                key='test.ok',
                title='OK job',
                description='Test job',
                task=ok_task,
                interval_minutes=60,
                max_retries=0,
                retry_delay_seconds=0,
            ),
        ]
        ensure_scheduled_jobs(definitions)

        from . import scheduler
        original_get_job_definitions = scheduler.get_job_definitions
        scheduler.get_job_definitions = lambda: definitions
        try:
            runs = run_due_jobs(force=True, triggered_by=ScheduledJobRun.TRIGGER_MANUAL)
        finally:
            scheduler.get_job_definitions = original_get_job_definitions

        self.assertEqual(calls, ['failed', 'ok'])
        self.assertEqual([run.status for run in runs], [ScheduledJobState.STATUS_ERROR, ScheduledJobState.STATUS_SUCCESS])
        self.assertEqual(ScheduledJobRun.objects.count(), 2)

    def test_management_command_lists_jobs(self):
        output = []

        class Writer:
            def write(self, message):
                output.append(message)

        command_output = Writer()
        call_command('run_scheduled_jobs', '--list', stdout=command_output)

        self.assertTrue(any('investment.fx_refresh' in line for line in output))
