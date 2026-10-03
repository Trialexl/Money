import json
import signal
import time
from decimal import Decimal
from datetime import timedelta
from unittest import skipUnless

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from investments.models import (
    Instrument,
    InstrumentPriceSnapshot,
    InvestmentAccount,
    InvestmentOperation,
    InvestmentPortfolio,
)
from money.models import TelegramUserBinding
from users.models import CustomUser

from .models import ScheduledJobRun, ScheduledJobState, SchedulerState
from .scheduler import ScheduledJobDefinition, ensure_scheduled_jobs, get_job_definitions, run_due_jobs
from .scheduler_lease import (
    acquire_scheduler_lease,
    release_scheduler_lease,
    renew_scheduler_lease,
)
from .telegram_reports import send_portfolio_report_to_telegram


class FakeTelegramResponse:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self):
        return json.dumps({'ok': True}).encode('utf-8')


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

    def test_force_run_still_respects_active_job_lock(self):
        calls = []
        definition = ScheduledJobDefinition(
            key='test.locked',
            title='Locked job',
            description='Test job',
            task=lambda: calls.append('ran'),
            interval_minutes=60,
        )
        ensure_scheduled_jobs([definition])
        ScheduledJobState.objects.filter(job_key=definition.key).update(
            lock_until=timezone.now() + timedelta(minutes=5),
        )

        from . import scheduler
        original_get_job_definitions = scheduler.get_job_definitions
        scheduler.get_job_definitions = lambda: [definition]
        try:
            runs = run_due_jobs(force=True, triggered_by=ScheduledJobRun.TRIGGER_MANUAL)
        finally:
            scheduler.get_job_definitions = original_get_job_definitions

        self.assertEqual(calls, [])
        self.assertEqual(runs[0].status, ScheduledJobState.STATUS_SKIPPED)

    @skipUnless(hasattr(signal, 'SIGALRM'), 'Job timeout requires SIGALRM')
    def test_job_timeout_is_recorded_as_error(self):
        definition = ScheduledJobDefinition(
            key='test.timeout',
            title='Timeout job',
            description='Test job',
            task=lambda: time.sleep(2),
            interval_minutes=60,
            timeout_seconds=1,
            max_retries=0,
            retry_delay_seconds=0,
        )
        ensure_scheduled_jobs([definition])

        from . import scheduler
        original_get_job_definitions = scheduler.get_job_definitions
        scheduler.get_job_definitions = lambda: [definition]
        try:
            runs = run_due_jobs(force=True, triggered_by=ScheduledJobRun.TRIGGER_MANUAL)
        finally:
            scheduler.get_job_definitions = original_get_job_definitions

        self.assertEqual(runs[0].status, ScheduledJobState.STATUS_ERROR)
        self.assertIn('Job exceeded timeout', runs[0].error)

    def test_management_command_lists_jobs(self):
        output = []

        class Writer:
            def write(self, message):
                output.append(message)

        command_output = Writer()
        call_command('run_scheduled_jobs', '--list', stdout=command_output)

        self.assertTrue(any('investment.fx_refresh' in line for line in output))

    def test_heavy_jobs_are_spread_out_and_restore_check_is_weekly(self):
        definitions = {definition.key: definition for definition in get_job_definitions()}

        self.assertEqual(definitions['backup.restore_check'].interval_minutes, 10080)
        self.assertEqual(str(definitions['backup.restore_check'].run_at_time), '04:20:00')
        self.assertEqual(str(definitions['investment.fx_refresh'].run_at_time), '05:30:00')
        self.assertEqual(str(definitions['investment.price_refresh'].run_at_time), '05:45:00')
        self.assertEqual(str(definitions['investment.market_health'].run_at_time), '06:10:00')
        self.assertEqual(str(definitions['investment.snapshots_today'].run_at_time), '06:40:00')
        self.assertEqual(str(definitions['investment.telegram_portfolio_report'].run_at_time), '06:50:00')

    def test_scheduler_db_lease_allows_only_one_owner(self):
        acquired, _state = acquire_scheduler_lease(
            owner_id='owner-one',
            hostname='host-one',
            pid=101,
            interval_seconds=60,
            lease_seconds=180,
        )
        second_acquired, state = acquire_scheduler_lease(
            owner_id='owner-two',
            hostname='host-two',
            pid=202,
            interval_seconds=60,
            lease_seconds=180,
        )

        self.assertTrue(acquired)
        self.assertFalse(second_acquired)
        self.assertEqual(state.owner_id, 'owner-one')
        self.assertTrue(state.is_alive)

    def test_scheduler_lease_heartbeat_and_release(self):
        acquired, state = acquire_scheduler_lease(
            owner_id='owner-one',
            hostname='host-one',
            pid=101,
            interval_seconds=10,
            lease_seconds=30,
        )
        first_heartbeat = state.heartbeat_at

        self.assertTrue(acquired)
        self.assertTrue(renew_scheduler_lease(owner_id='owner-one', lease_seconds=30))
        self.assertFalse(renew_scheduler_lease(owner_id='wrong-owner', lease_seconds=30))
        self.assertTrue(release_scheduler_lease(owner_id='owner-one'))

        state = SchedulerState.objects.get(singleton_key='default')
        self.assertGreaterEqual(state.heartbeat_at, first_heartbeat)
        self.assertEqual(state.status, SchedulerState.STATUS_STOPPED)
        self.assertEqual(state.owner_id, '')
        self.assertIsNone(state.lock_until)

    def test_market_refresh_job_marks_all_failed_result_as_error(self):
        from . import scheduler
        original_refresh = scheduler.refresh_fx_rate_snapshots
        scheduler.refresh_fx_rate_snapshots = lambda: {'created': 0, 'updated': 0, 'failed': 2, 'results': []}
        try:
            result = scheduler.job_refresh_fx_rates()
        finally:
            scheduler.refresh_fx_rate_snapshots = original_refresh

        self.assertEqual(result.status, ScheduledJobState.STATUS_ERROR)
        self.assertEqual(result.payload['failed'], 2)

    def test_market_refresh_job_marks_partial_failed_result_as_warning(self):
        from . import scheduler
        original_refresh = scheduler.refresh_price_snapshots
        scheduler.refresh_price_snapshots = lambda: {'created': 1, 'updated': 0, 'failed': 1, 'results': []}
        try:
            result = scheduler.job_refresh_prices()
        finally:
            scheduler.refresh_price_snapshots = original_refresh

        self.assertEqual(result.status, ScheduledJobState.STATUS_WARNING)
        self.assertEqual(result.payload['created'], 1)

    @override_settings(AI_TELEGRAM_BOT_TOKEN='')
    def test_telegram_portfolio_report_warns_without_bot_token(self):
        from . import scheduler

        result = scheduler.job_send_telegram_portfolio_report()

        self.assertEqual(result.status, ScheduledJobState.STATUS_WARNING)
        self.assertEqual(result.payload['reason'], 'telegram_token_missing')

    @override_settings(AI_TELEGRAM_BOT_TOKEN='telegram-token')
    def test_telegram_portfolio_report_sends_default_portfolio_summary(self):
        user = CustomUser.objects.create_user(username='investor', password='pass12345')
        portfolio = InvestmentPortfolio.objects.create(user=user, name='Крипта', is_default=True)
        account = InvestmentAccount.objects.create(portfolio=portfolio, name='Биржа')
        instrument = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='BTC', name='Bitcoin')
        InvestmentOperation.objects.create(
            portfolio=portfolio,
            account=account,
            instrument=instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0000000000'),
            price_usd=Decimal('100.00000000'),
            amount_usd=Decimal('100.00'),
            date=timezone.now(),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=instrument,
            captured_at=timezone.now(),
            price=Decimal('120.00000000'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1.00000000'),
            price_usd=Decimal('120.00'),
            source='test',
        )
        TelegramUserBinding.objects.create(
            user=user,
            telegram_user_id=1001,
            telegram_chat_id=2002,
            telegram_username='investor',
            linked_at=timezone.now(),
        )
        requests = []

        def fake_urlopen(request, timeout=20):
            requests.append((request, timeout))
            return FakeTelegramResponse()

        result = send_portfolio_report_to_telegram(urlopen=fake_urlopen)

        self.assertEqual(result['sent'], 1)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(len(requests), 1)
        request, timeout = requests[0]
        payload = json.loads(request.data.decode('utf-8'))
        self.assertEqual(timeout, 20)
        self.assertIn('/bottelegram-token/sendMessage', request.full_url)
        self.assertEqual(payload['chat_id'], 2002)
        self.assertIn('💼 Крипта', payload['text'])
        self.assertIn('Стоимость: 120.00 $', payload['text'])
        self.assertIn('P/L: +20.00 $', payload['text'])
        self.assertIn('BTC', payload['text'])
