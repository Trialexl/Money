import json
from decimal import Decimal
from datetime import timedelta

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

from .models import ScheduledJobRun, ScheduledJobState
from .scheduler import ScheduledJobDefinition, ensure_scheduled_jobs, run_due_jobs
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

    def test_management_command_lists_jobs(self):
        output = []

        class Writer:
            def write(self, message):
                output.append(message)

        command_output = Writer()
        call_command('run_scheduled_jobs', '--list', stdout=command_output)

        self.assertTrue(any('investment.fx_refresh' in line for line in output))

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
