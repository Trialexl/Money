from decimal import Decimal
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from money.ai_service import AiOperationService
from money.models import BudgetExpense, BudgetIncome, FlowOfFunds, OneCSyncOutbox, Wallet
from users.models import CustomUser

from .fx_providers import CbrFxRateProvider, FxRateProviderError, FxRateQuote, StaticFxRateProvider, get_fx_rate_provider
from .models import (
    FxRateSnapshot,
    Instrument,
    InstrumentPriceSnapshot,
    InvestmentAccount,
    InvestmentOperation,
    InvestmentPortfolio,
    InvestmentPortfolioSnapshot,
    InvestmentTargetAllocation,
)
from .price_providers import (
    CoinGeckoPriceProvider,
    CompositePriceProvider,
    PriceProviderError,
    PriceQuote,
    StaticPriceProvider,
    StooqPriceProvider,
    get_price_provider,
)
from .services import (
    calculate_portfolio_performance,
    calculate_positions,
    calculate_portfolio_totals,
    rebuild_portfolio_snapshots,
    upsert_portfolio_snapshot,
    refresh_price_snapshots,
    refresh_fx_rate_snapshots,
    backfill_price_snapshots,
)


class InvestmentModuleIsolationTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(username='investor', password='pass12345')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.wallet = Wallet.objects.create(name='Альфа')
        self.portfolio = InvestmentPortfolio.objects.create(user=self.user, name='Основной', is_default=True)
        self.account = InvestmentAccount.objects.create(portfolio=self.portfolio, name='Биржа')
        self.instrument = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='BTC', name='Bitcoin')

    def _create_buy_operation(self):
        return InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0000000000'),
            price_usd=Decimal('100000.00000000'),
            amount_usd=Decimal('100000.00'),
            date=timezone.now(),
        )

    def _dt(self, year, month, day, hour=12):
        return timezone.make_aware(
            datetime(year, month, day, hour, 0, 0),
            timezone.get_current_timezone(),
        )

    def _create_foreign_investment_data(self):
        other_user = CustomUser.objects.create_user(username='other-investor', password='pass12345')
        other_portfolio = InvestmentPortfolio.objects.create(user=other_user, name='Чужой портфель', is_default=True)
        other_account = InvestmentAccount.objects.create(portfolio=other_portfolio, name='Чужая биржа')
        other_operation = InvestmentOperation.objects.create(
            portfolio=other_portfolio,
            account=other_account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('2.0000000000'),
            price_usd=Decimal('200000.00000000'),
            amount_usd=Decimal('400000.00'),
            date=timezone.now(),
        )
        return other_user, other_portfolio, other_account, other_operation

    def test_buy_operation_does_not_create_money_registers_or_onec_outbox(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_BUY,
            'quantity': '0.1000000000',
            'price_usd': '1000000.00000000',
            'amount_usd': '100000.00',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(FlowOfFunds.objects.exists())
        self.assertFalse(BudgetIncome.objects.exists())
        self.assertFalse(BudgetExpense.objects.exists())
        self.assertFalse(OneCSyncOutbox.objects.filter(object_id=response.data['id']).exists())

    def test_sell_operation_does_not_create_money_registers_or_onec_outbox(self):
        self._create_buy_operation()

        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_SELL,
            'quantity': '0.5000000000',
            'price_usd': '120000.00000000',
            'amount_usd': '60000.00',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(FlowOfFunds.objects.exists())
        self.assertFalse(BudgetIncome.objects.exists())
        self.assertFalse(BudgetExpense.objects.exists())
        self.assertFalse(OneCSyncOutbox.objects.filter(object_id=response.data['id']).exists())

    def test_investment_operations_do_not_affect_dashboard_or_money_reports(self):
        operation = self._create_buy_operation()
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_SELL,
            quantity=Decimal('0.2500000000'),
            price_usd=Decimal('120000.00000000'),
            amount_usd=Decimal('30000.00'),
            date=operation.date + timedelta(hours=1),
        )
        date_from = (operation.date - timedelta(days=1)).isoformat()
        date_to = (operation.date + timedelta(days=1)).isoformat()

        admin_user = CustomUser.objects.create_superuser(username='money-admin', password='pass12345')
        admin_client = APIClient()
        admin_client.force_authenticate(admin_user)

        dashboard_response = admin_client.get('/api/v1/dashboard/overview/', {'date': operation.date.isoformat()})
        cash_flow_response = admin_client.get('/api/v1/reports/cash-flow/', {'date_from': date_from, 'date_to': date_to})
        budget_expense_response = admin_client.get('/api/v1/reports/budget-expense/', {'date_from': date_from, 'date_to': date_to})
        budget_income_response = admin_client.get('/api/v1/reports/budget-income/', {'date_from': date_from, 'date_to': date_to})

        self.assertEqual(dashboard_response.status_code, 200, dashboard_response.data)
        self.assertEqual(cash_flow_response.status_code, 200, cash_flow_response.data)
        self.assertEqual(budget_expense_response.status_code, 200, budget_expense_response.data)
        self.assertEqual(budget_income_response.status_code, 200, budget_income_response.data)
        self.assertEqual(dashboard_response.data['wallet_total'], '0.00')
        self.assertEqual(dashboard_response.data['wallets'], [])
        self.assertEqual(cash_flow_response.data['totals'], {'income': '0.00', 'expense': '0.00'})
        self.assertEqual(cash_flow_response.data['details'], [])
        self.assertEqual(budget_expense_response.data['totals'], {'actual': '0.00', 'budget': '0.00', 'balance': '0.00'})
        self.assertEqual(budget_expense_response.data['details'], [])
        self.assertEqual(budget_income_response.data['totals'], {'actual': '0.00', 'budget': '0.00', 'balance': '0.00'})
        self.assertEqual(budget_income_response.data['details'], [])

    def test_positions_calculate_average_price_and_realized_pl(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=timezone.now(),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('200.00'),
            amount_usd=Decimal('200.00'),
            date=timezone.now(),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_SELL,
            quantity=Decimal('0.5'),
            price_usd=Decimal('300.00'),
            amount_usd=Decimal('150.00'),
            date=timezone.now(),
        )

        positions = calculate_positions(self.portfolio)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]['quantity'], Decimal('1.5000000000'))
        self.assertEqual(positions[0]['average_buy_price_usd'], Decimal('150.00'))
        self.assertEqual(positions[0]['cost_basis_usd'], Decimal('225.00'))
        self.assertEqual(positions[0]['realized_pl_usd'], Decimal('75.00'))

    def test_positions_use_latest_price_for_unrealized_pl(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=timezone.now(),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('150.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('150.00'),
            captured_at=timezone.now(),
        )

        positions = calculate_positions(self.portfolio)
        totals = calculate_portfolio_totals(self.portfolio)

        self.assertEqual(positions[0]['current_value_usd'], Decimal('150.00'))
        self.assertEqual(positions[0]['unrealized_pl_usd'], Decimal('50.00'))
        self.assertEqual(positions[0]['total_pl_usd'], Decimal('50.00'))
        self.assertEqual(positions[0]['return_percent'], Decimal('50.00'))
        self.assertEqual(positions[0]['allocation_percent'], Decimal('100.00'))

    def test_dividend_increases_realized_pl_without_money_movement(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_DIVIDEND,
            quantity=Decimal('0'),
            amount_usd=Decimal('25.00'),
            fee_usd=Decimal('1.00'),
            date=timezone.now(),
        )

        positions = calculate_positions(self.portfolio)
        totals = calculate_portfolio_totals(self.portfolio)

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]['quantity'], Decimal('0'))
        self.assertEqual(positions[0]['realized_pl_usd'], Decimal('24.00'))
        self.assertEqual(totals['realized_pl_usd'], Decimal('24.00'))
        self.assertEqual(totals['total_pl_usd'], Decimal('24.00'))
        self.assertFalse(FlowOfFunds.objects.exists())
        self.assertIsNone(positions[0]['target_allocation_percent'])
        self.assertIsNone(positions[0]['allocation_deviation_percent'])
        self.assertEqual(totals['current_value_usd'], Decimal('0.00'))
        self.assertEqual(totals['unrealized_pl_usd'], Decimal('0.00'))
        self.assertEqual(totals['total_pl_usd'], Decimal('24.00'))
        self.assertTrue(totals['valuation_complete'])
        self.assertIsNone(totals['largest_asset'])
        self.assertIsNone(totals['latest_price_at'])

    def test_split_changes_quantity_without_creating_pl(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('10.0000000000'),
            price_usd=Decimal('10.00000000'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 10),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_SPLIT,
            quantity=Decimal('2.0000000000'),
            amount_usd=Decimal('0.00'),
            date=self._dt(2026, 1, 11),
        )

        positions = calculate_positions(self.portfolio)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]['quantity'], Decimal('20.0000000000'))
        self.assertEqual(positions[0]['cost_basis_usd'], Decimal('100.00'))
        self.assertEqual(positions[0]['average_buy_price_usd'], Decimal('5.00'))
        self.assertEqual(positions[0]['realized_pl_usd'], Decimal('0.00'))
        self.assertEqual(positions[0]['total_pl_usd'], Decimal('0.00'))
        self.assertFalse(FlowOfFunds.objects.exists())

    def test_reverse_split_changes_quantity_without_changing_cost_basis(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('10.0000000000'),
            price_usd=Decimal('10.00000000'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 10),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_SPLIT,
            quantity=Decimal('0.5000000000'),
            amount_usd=Decimal('0.00'),
            date=self._dt(2026, 1, 11),
        )

        positions = calculate_positions(self.portfolio)
        self.assertEqual(positions[0]['quantity'], Decimal('5.00000000000'))
        self.assertEqual(positions[0]['cost_basis_usd'], Decimal('100.00'))
        self.assertEqual(positions[0]['average_buy_price_usd'], Decimal('20.00'))

    def test_target_allocations_reject_total_above_100_percent(self):
        eth = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='ETH', name='Ethereum')
        usdt = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='USDT', name='Tether')
        extra = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='SOL', name='Solana')

        responses = [
            self.client.post('/api/v1/investment/target-allocations/', {
                'portfolio': str(self.portfolio.id),
                'instrument': str(self.instrument.id),
                'target_percent': '50.00',
                'tolerance_percent': '5.00',
            }, format='json'),
            self.client.post('/api/v1/investment/target-allocations/', {
                'portfolio': str(self.portfolio.id),
                'instrument': str(eth.id),
                'target_percent': '30.00',
                'tolerance_percent': '5.00',
            }, format='json'),
            self.client.post('/api/v1/investment/target-allocations/', {
                'portfolio': str(self.portfolio.id),
                'instrument': str(usdt.id),
                'target_percent': '20.00',
                'tolerance_percent': '5.00',
            }, format='json'),
        ]
        overflow_response = self.client.post('/api/v1/investment/target-allocations/', {
            'portfolio': str(self.portfolio.id),
            'instrument': str(extra.id),
            'target_percent': '1.00',
            'tolerance_percent': '5.00',
        }, format='json')

        self.assertTrue(all(response.status_code == 201 for response in responses), [response.data for response in responses])
        self.assertEqual(overflow_response.status_code, 400)
        self.assertIn('target_percent', overflow_response.data)

    def test_rebalance_endpoint_returns_current_deviation_without_creating_operations(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=timezone.now(),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('100.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('100.00'),
            captured_at=timezone.now(),
        )
        InvestmentTargetAllocation.objects.create(
            portfolio=self.portfolio,
            instrument=self.instrument,
            target_percent=Decimal('50.00'),
            tolerance_percent=Decimal('5.00'),
        )

        response = self.client.get(f'/api/v1/investment/portfolios/{self.portfolio.id}/rebalance/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['positions'][0]['target_allocation_percent'], Decimal('50.00'))
        self.assertEqual(response.data['positions'][0]['allocation_deviation_percent'], Decimal('50.00'))
        self.assertEqual(response.data['positions'][0]['rebalance_action'], 'sell')
        self.assertIn('не является инвестиционной рекомендацией', response.data['disclaimer'])

    def test_ai_service_returns_portfolio_overview(self):
        self._create_buy_operation()
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('120000.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('120000.00'),
            captured_at=timezone.now(),
        )

        result = AiOperationService().process(text='портфель', user=self.user, source='telegram', dry_run=True)

        self.assertEqual(result['status'], 'info')
        self.assertEqual(result['intent'], 'get_portfolio_overview')
        self.assertIn('Стоимость', result['reply_text'])
        self.assertEqual(result['investment_overview']['portfolio_id'], str(self.portfolio.id))

    def test_ai_service_returns_instrument_position(self):
        self._create_buy_operation()

        result = AiOperationService().process(text='сколько btc', user=self.user, source='telegram', dry_run=True)

        self.assertEqual(result['status'], 'info')
        self.assertEqual(result['intent'], 'get_instrument_position')
        self.assertEqual(result['investment_position']['instrument_ticker'], 'BTC')
        self.assertIn('Количество', result['reply_text'])

    def test_ai_service_returns_rebalance_status(self):
        self._create_buy_operation()
        InvestmentTargetAllocation.objects.create(
            portfolio=self.portfolio,
            instrument=self.instrument,
            target_percent=Decimal('50.00'),
            tolerance_percent=Decimal('5.00'),
        )

        result = AiOperationService().process(text='ребалансировка портфеля', user=self.user, source='telegram', dry_run=True)

        self.assertEqual(result['status'], 'info')
        self.assertEqual(result['intent'], 'get_rebalance_status')
        self.assertEqual(result['investment_rebalance']['portfolio_id'], str(self.portfolio.id))
        self.assertIn('Ребаланс', result['reply_text'])

    def test_ai_service_previews_investment_buy_before_creation(self):
        service = AiOperationService()

        result = service.process(
            text='купил btc 0.1 по 100000',
            user=self.user,
            source='telegram',
            dry_run=True,
        )

        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertEqual(result['intent'], 'create_investment_buy')
        self.assertEqual(result['missing_fields'], ['final_confirmation'])
        self.assertIn('BTC', result['reply_text'])
        self.assertEqual(InvestmentOperation.objects.count(), 0)

        confirmation = service.continue_confirmation(
            normalized_payload=service.serialize_normalized(result['parsed']),
            missing_fields=result['missing_fields'],
            answer_text='да',
            provider_name=result['provider'],
            dry_run=True,
            source='telegram',
        )
        created = service.create_from_normalized(
            normalized=confirmation['parsed'],
            provider_name=confirmation['provider'],
        )

        self.assertEqual(created['status'], 'created')
        operation = InvestmentOperation.objects.get()
        self.assertEqual(operation.operation_type, InvestmentOperation.TYPE_BUY)
        self.assertEqual(operation.instrument, self.instrument)
        self.assertEqual(operation.account, self.account)
        self.assertEqual(operation.quantity, Decimal('0.1000000000'))
        self.assertEqual(operation.price_usd, Decimal('100000.00000000'))
        self.assertEqual(operation.amount_usd, Decimal('10000.00'))

    def test_ai_service_asks_missing_investment_trade_fields(self):
        result = AiOperationService().process(
            text='купил btc на 1000',
            user=self.user,
            source='telegram',
            dry_run=True,
        )

        self.assertEqual(result['status'], 'needs_confirmation')
        self.assertEqual(result['intent'], 'create_investment_buy')
        self.assertIn('quantity', result['missing_fields'])
        self.assertIn('price_usd', result['missing_fields'])
        self.assertEqual(InvestmentOperation.objects.count(), 0)

    def test_ai_service_keeps_money_transfer_to_crypto_wallet_out_of_investments(self):
        Wallet.objects.create(name='Крипта')

        result = AiOperationService().process(
            text='перевод альфа в крипта 2000',
            user=self.user,
            source='telegram',
            dry_run=True,
        )

        self.assertEqual(result['intent'], 'create_transfer')
        self.assertNotIn('investment', result['intent'])
        self.assertEqual(InvestmentOperation.objects.count(), 0)

    def test_portfolio_performance_uses_opening_value_before_period(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2025, 12, 20),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('120.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('120.00'),
            captured_at=self._dt(2025, 12, 31),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('200.00'),
            amount_usd=Decimal('200.00'),
            date=self._dt(2026, 1, 10),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('150.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('150.00'),
            captured_at=self._dt(2026, 1, 31),
        )

        performance = calculate_portfolio_performance(
            self.portfolio,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            group_by='month',
        )

        self.assertEqual(performance['opening']['cost_basis_usd'], Decimal('100.00'))
        self.assertEqual(performance['opening']['current_value_usd'], Decimal('120.00'))
        self.assertEqual(performance['points'][0]['cost_basis_usd'], Decimal('300.00'))
        self.assertEqual(performance['points'][0]['current_value_usd'], Decimal('300.00'))
        self.assertEqual(performance['points'][0]['period_start'], '2026-01-01')
        self.assertEqual(performance['points'][0]['period_end'], '2026-01-31')

    def test_portfolio_performance_uses_purchase_date_fx_for_display_cost_basis(self):
        for day, rate in ((10, Decimal('90.00000000')), (20, Decimal('100.00000000')), (31, Decimal('110.00000000'))):
            FxRateSnapshot.objects.create(
                captured_at=self._dt(2026, 1, day),
                base_currency='USD',
                quote_currency='RUB',
                rate=rate,
                source='test-fx',
            )
        for day in (10, 20):
            InvestmentOperation.objects.create(
                portfolio=self.portfolio,
                account=self.account,
                instrument=self.instrument,
                operation_type=InvestmentOperation.TYPE_BUY,
                quantity=Decimal('1.0'),
                price_usd=Decimal('100.00'),
                amount_usd=Decimal('100.00'),
                date=self._dt(2026, 1, day),
            )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('150.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('150.00'),
            captured_at=self._dt(2026, 1, 31),
        )

        performance = calculate_portfolio_performance(
            self.portfolio,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            group_by='month',
            display_currency='RUB',
        )

        point = performance['points'][0]
        self.assertEqual(point['cost_basis_usd'], Decimal('200.00'))
        self.assertEqual(point['cost_basis_display'], Decimal('19000.00'))
        self.assertEqual(point['current_value_display'], Decimal('33000.00'))
        self.assertEqual(point['unrealized_pl_display'], Decimal('14000.00'))

    def test_portfolio_performance_skips_month_without_exact_price(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 5),
        )
        for captured_at, price in (
            (self._dt(2026, 1, 31), Decimal('100.00')),
            (self._dt(2026, 3, 31), Decimal('130.00')),
        ):
            InstrumentPriceSnapshot.objects.create(
                instrument=self.instrument,
                price=price,
                price_currency='USD',
                fx_rate_to_usd=Decimal('1'),
                price_usd=price,
                captured_at=captured_at,
            )

        performance = calculate_portfolio_performance(
            self.portfolio,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 3, 31),
            group_by='month',
        )

        self.assertEqual([point['period_end'] for point in performance['points']], ['2026-01-31', '2026-03-31'])
        self.assertEqual([point['current_value_usd'] for point in performance['points']], [Decimal('100.00'), Decimal('130.00')])

    def test_portfolio_performance_returns_instrument_pl_series(self):
        eth = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='ETH', name='Ethereum')
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 5),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=eth,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('50.00'),
            amount_usd=Decimal('50.00'),
            date=self._dt(2026, 1, 6),
        )
        for instrument, price in ((self.instrument, Decimal('150.00')), (eth, Decimal('50.00'))):
            InstrumentPriceSnapshot.objects.create(
                instrument=instrument,
                price=price,
                price_currency='USD',
                fx_rate_to_usd=Decimal('1'),
                price_usd=price,
                captured_at=self._dt(2026, 1, 31),
            )

        performance = calculate_portfolio_performance(
            self.portfolio,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            group_by='month',
            scope='all',
        )

        self.assertEqual(performance['points'][0]['total_pl_usd'], Decimal('50.00'))
        series_by_ticker = {series['instrument_ticker']: series for series in performance['instrument_series']}
        self.assertEqual(series_by_ticker['BTC']['points'][0]['total_pl_usd'], Decimal('50.00'))
        self.assertEqual(series_by_ticker['ETH']['points'][0]['total_pl_usd'], Decimal('0.00'))
        self.assertEqual(
            sum(series['points'][0]['total_pl_usd'] for series in performance['instrument_series']),
            performance['points'][0]['total_pl_usd'],
        )

    def test_rebuild_portfolio_snapshots_creates_daily_snapshots(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 1),
        )
        for day, price in ((1, Decimal('100.00')), (2, Decimal('110.00'))):
            InstrumentPriceSnapshot.objects.create(
                instrument=self.instrument,
                price=price,
                price_currency='USD',
                fx_rate_to_usd=Decimal('1'),
                price_usd=price,
                captured_at=self._dt(2026, 1, day),
            )

        summary = rebuild_portfolio_snapshots(
            portfolio=self.portfolio,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 2),
        )

        self.assertEqual(summary['created'], 2)
        snapshots = InvestmentPortfolioSnapshot.objects.filter(portfolio=self.portfolio).order_by('snapshot_date')
        self.assertEqual([snapshot.snapshot_date for snapshot in snapshots], [date(2026, 1, 1), date(2026, 1, 2)])
        self.assertEqual([snapshot.current_value_usd for snapshot in snapshots], [Decimal('100.00'), Decimal('110.00')])
        self.assertEqual(snapshots[1].positions_payload[0]['instrument_ticker'], 'BTC')

    def test_operation_api_rebuilds_portfolio_snapshots_after_create(self):
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('100.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('100.00'),
            captured_at=self._dt(2026, 1, 1),
        )

        with patch('investments.services.timezone.localdate', return_value=date(2026, 1, 2)):
            response = self.client.post('/api/v1/investment/operations/', {
                'portfolio': str(self.portfolio.id),
                'account': str(self.account.id),
                'instrument': str(self.instrument.id),
                'operation_type': InvestmentOperation.TYPE_BUY,
                'quantity': '1.0000000000',
                'price_usd': '100.00000000',
                'amount_usd': '100.00',
                'date': self._dt(2026, 1, 1).isoformat(),
            }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        snapshots = InvestmentPortfolioSnapshot.objects.filter(portfolio=self.portfolio).order_by('snapshot_date')
        self.assertEqual([snapshot.snapshot_date for snapshot in snapshots], [date(2026, 1, 1), date(2026, 1, 2)])

    def test_operation_api_display_amounts_use_operation_date_fx(self):
        FxRateSnapshot.objects.create(
            captured_at=self._dt(2026, 1, 1),
            base_currency='USD',
            quote_currency='RUB',
            rate=Decimal('70.00000000'),
            source='test-fx',
        )
        FxRateSnapshot.objects.create(
            captured_at=self._dt(2026, 2, 3),
            base_currency='USD',
            quote_currency='RUB',
            rate=Decimal('80.00000000'),
            source='test-fx',
        )
        FxRateSnapshot.objects.create(
            captured_at=self._dt(2026, 2, 4),
            base_currency='USD',
            quote_currency='RUB',
            rate=Decimal('100.00000000'),
            source='test-fx',
        )
        operation = InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('2.0000000000'),
            price_usd=Decimal('50.00000000'),
            amount_usd=Decimal('100.00'),
            fee_usd=Decimal('1.00'),
            date=self._dt(2026, 2, 3),
        )

        response = self.client.get('/api/v1/investment/operations/', {'display_currency': 'RUB'})

        self.assertEqual(response.status_code, 200, response.data)
        row = next(item for item in response.data if item['id'] == str(operation.id))
        self.assertEqual(row['display_currency'], 'RUB')
        self.assertEqual(row['fx_rate_to_display'], Decimal('80.00000000'))
        self.assertEqual(row['price_display'], Decimal('4000.00'))
        self.assertEqual(row['amount_display'], Decimal('8000.00'))
        self.assertEqual(row['fee_display'], Decimal('80.00'))

    def test_price_api_rebuilds_related_portfolio_snapshots_after_create(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 1),
        )

        with patch('investments.services.timezone.localdate', return_value=date(2026, 1, 2)):
            response = self.client.post('/api/v1/investment/prices/', {
                'instrument': str(self.instrument.id),
                'captured_at': self._dt(2026, 1, 2).isoformat(),
                'price': '120.00000000',
                'price_currency': 'USD',
                'fx_rate_to_usd': '1.00000000',
            }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        snapshot = InvestmentPortfolioSnapshot.objects.get(portfolio=self.portfolio, snapshot_date=date(2026, 1, 2))
        self.assertEqual(snapshot.current_value_usd, Decimal('120.00'))

    def test_portfolio_performance_can_use_fresh_snapshot_without_price_snapshot(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 5),
        )
        price_snapshot = InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('150.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('150.00'),
            captured_at=self._dt(2026, 1, 31),
        )
        snapshot, _created = upsert_portfolio_snapshot(self.portfolio, date(2026, 1, 31))
        price_snapshot.delete()

        performance = calculate_portfolio_performance(
            self.portfolio,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            group_by='month',
            scope='all',
        )

        self.assertEqual(snapshot.current_value_usd, Decimal('150.00'))
        self.assertEqual(performance['points'][0]['current_value_usd'], Decimal('150.00'))
        self.assertEqual(performance['instrument_series'][0]['points'][0]['total_pl_usd'], Decimal('50.00'))

    def test_investment_operations_do_not_mutate_price_snapshots(self):
        snapshot = InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('120.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('120.00'),
            captured_at=self._dt(2026, 1, 31),
        )
        operation = InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 5),
        )

        operation.quantity = Decimal('2.0')
        operation.amount_usd = Decimal('200.00')
        operation.save()
        operation.deleted = True
        operation.save()

        snapshot.refresh_from_db()
        self.assertEqual(InstrumentPriceSnapshot.objects.count(), 1)
        self.assertEqual(snapshot.price_usd, Decimal('120.00'))
        self.assertEqual(snapshot.captured_at, self._dt(2026, 1, 31))

    def test_price_lookup_endpoint_returns_latest_snapshot_before_date(self):
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('110.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('110.00'),
            captured_at=self._dt(2026, 1, 10),
        )
        snapshot = InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('120.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('120.00'),
            captured_at=self._dt(2026, 1, 20),
        )

        response = self.client.get('/api/v1/investment/prices/lookup/', {
            'instrument': str(self.instrument.id),
            'date': '2026-01-25',
        })

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['found'])
        self.assertEqual(response.data['snapshot_id'], str(snapshot.id))
        self.assertEqual(response.data['snapshot_date'], '2026-01-20')
        self.assertEqual(response.data['stale_days'], 5)
        self.assertEqual(response.data['price_usd'], '120.00')

    def test_portfolio_performance_endpoint_returns_period_series(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=self._dt(2026, 1, 10),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('150.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('150.00'),
            captured_at=self._dt(2026, 1, 31),
        )

        response = self.client.get(f'/api/v1/investment/portfolios/{self.portfolio.id}/performance/', {
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
            'group_by': 'month',
        })

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['group_by'], 'month')
        self.assertEqual(str(response.data['opening']['current_value_usd']), '0.00')
        self.assertEqual(str(response.data['points'][0]['current_value_usd']), '150.00')

    def test_portfolio_overview_endpoint_returns_default_portfolio(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price_usd=Decimal('100.00'),
            amount_usd=Decimal('100.00'),
            date=timezone.now(),
        )

        response = self.client.get('/api/v1/investment/portfolio-overview/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['portfolio']['id'], str(self.portfolio.id))
        self.assertEqual(str(response.data['cost_basis_usd']), '100.00')

    def test_sell_more_than_position_is_rejected(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_SELL,
            'quantity': '1.0000000000',
            'price_usd': '1000000.00000000',
            'amount_usd': '1000000.00',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.data)

    def test_operation_api_uses_usd_fields_only(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_BUY,
            'quantity': '1.0000000000',
            'price_usd': '110.00000000',
            'amount_usd': '110.00',
            'fee_usd': '2.00',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        operation = InvestmentOperation.objects.get(id=response.data['id'])
        self.assertEqual(operation.price_usd, Decimal('110.00000000'))
        self.assertEqual(operation.amount_usd, Decimal('110.00'))
        self.assertEqual(operation.fee_usd, Decimal('2.00'))

    def test_operation_api_accepts_dividend_without_price_or_wallet_movement(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_DIVIDEND,
            'amount_usd': '25.00',
            'fee_usd': '1.00',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        operation = InvestmentOperation.objects.get(id=response.data['id'])
        self.assertEqual(operation.quantity, Decimal('0E-10'))
        self.assertIsNone(operation.price_usd)
        self.assertEqual(operation.amount_usd, Decimal('25.00'))
        self.assertFalse(FlowOfFunds.objects.exists())

    def test_operation_api_accepts_split_without_price_or_amount(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_SPLIT,
            'quantity': '2.0000000000',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        operation = InvestmentOperation.objects.get(id=response.data['id'])
        self.assertEqual(operation.operation_type, InvestmentOperation.TYPE_SPLIT)
        self.assertEqual(operation.quantity, Decimal('2.0000000000'))
        self.assertIsNone(operation.price_usd)
        self.assertEqual(operation.amount_usd, Decimal('0.00'))
        self.assertFalse(FlowOfFunds.objects.exists())

    def test_operation_api_rejects_split_with_money_amount(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_SPLIT,
            'quantity': '2.0000000000',
            'amount_usd': '10.00',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('amount_usd', response.data)

    def test_operation_api_rejects_split_with_price(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_SPLIT,
            'quantity': '2.0000000000',
            'price_usd': '10.00000000',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('price_usd', response.data)

    def test_investment_operations_csv_import_dry_run_and_create(self):
        csv_content = '\n'.join([
            'date,operation_type,ticker,account,quantity,price_usd,comment',
            '2026-01-10,buy,BTC,Биржа,0.1000000000,100000.00000000,first buy',
        ])

        preview_response = self.client.post('/api/v1/investment/operations/import-csv/', {
            'portfolio': str(self.portfolio.id),
            'csv': csv_content,
        }, format='json')

        self.assertEqual(preview_response.status_code, 200, preview_response.data)
        self.assertTrue(preview_response.data['dry_run'])
        self.assertEqual(preview_response.data['results'][0]['status'], 'preview')
        self.assertEqual(InvestmentOperation.objects.count(), 0)

        create_response = self.client.post('/api/v1/investment/operations/import-csv/', {
            'portfolio': str(self.portfolio.id),
            'csv': csv_content,
            'dry_run': False,
        }, format='json')

        self.assertEqual(create_response.status_code, 201, create_response.data)
        self.assertEqual(create_response.data['created'], 1)
        operation = InvestmentOperation.objects.get()
        self.assertEqual(operation.instrument, self.instrument)
        self.assertEqual(operation.account, self.account)
        self.assertEqual(operation.amount_usd, Decimal('10000.00'))

        duplicate_response = self.client.post('/api/v1/investment/operations/import-csv/', {
            'portfolio': str(self.portfolio.id),
            'csv': csv_content,
            'dry_run': False,
        }, format='json')

        self.assertEqual(duplicate_response.status_code, 201, duplicate_response.data)
        self.assertEqual(duplicate_response.data['created'], 0)
        self.assertEqual(duplicate_response.data['skipped'], 1)
        self.assertEqual(InvestmentOperation.objects.count(), 1)

    def test_openapi_schema_contains_investment_contract(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('/api/v1/investment/instruments/', content)
        self.assertIn('/api/v1/investment/prices/', content)
        self.assertIn('/api/v1/investment/prices/refresh/', content)
        self.assertIn('/api/v1/investment/fx-rates/', content)
        self.assertIn('/api/v1/investment/fx-rates/refresh/', content)
        self.assertIn('/api/v1/investment/portfolios/', content)
        self.assertIn('/api/v1/investment/portfolios/{id}/performance/', content)
        self.assertIn('/api/v1/investment/portfolios/{id}/rebalance/', content)
        self.assertIn('/api/v1/investment/target-allocations/', content)
        self.assertIn('/api/v1/investment/accounts/', content)
        self.assertIn('/api/v1/investment/operations/', content)
        self.assertIn('/api/v1/investment/operations/import-csv/', content)
        self.assertIn('/api/v1/investment/portfolio-overview/', content)
        self.assertIn('/api/v1/investment/market-health/', content)
        self.assertIn('InstrumentPriceSnapshot', content)
        self.assertIn('InvestmentOperationRequest', content)
        self.assertIn('operation_type', content)
        self.assertIn('date_from', content)
        self.assertIn('date_to', content)
        self.assertIn('не синхронизируется с 1С', content)

    def test_refresh_price_snapshots_creates_price_and_fx_snapshots(self):
        eth = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='ETH', name='Ethereum')

        class PriceProvider:
            def get_price(self, instrument):
                return PriceQuote(
                    instrument_id=str(instrument.id),
                    symbol=instrument.ticker,
                    price=Decimal('100.00'),
                    price_currency='EUR',
                    source='test-price',
                )

        class FxProvider:
            def get_rate(self, base_currency, quote_currency='USD'):
                return FxRateQuote(
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    rate=Decimal('1.10000000'),
                    source='test-fx',
                )

        result = refresh_price_snapshots(price_provider=PriceProvider(), fx_provider=FxProvider())

        self.assertEqual(result['created'], 2)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(InstrumentPriceSnapshot.objects.count(), 2)
        self.assertEqual(FxRateSnapshot.objects.count(), 1)
        eth_snapshot = InstrumentPriceSnapshot.objects.get(instrument=eth)
        self.assertEqual(eth_snapshot.price_currency, 'EUR')
        self.assertEqual(eth_snapshot.fx_rate_to_usd, Decimal('1.10000000'))
        self.assertEqual(eth_snapshot.price_usd, Decimal('110.00'))
        self.assertEqual(eth_snapshot.source, 'test-price')

    def test_backfill_price_snapshots_creates_daily_prices(self):
        eth = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='ETH', name='Ethereum')

        class PriceProvider:
            def get_historical_price(self, instrument, on_date):
                return PriceQuote(
                    instrument_id=str(instrument.id),
                    symbol=instrument.ticker,
                    price=Decimal('100.00'),
                    price_currency='USD',
                    source='test-price',
                )

        result = backfill_price_snapshots(
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 2),
            price_provider=PriceProvider(),
            instruments=Instrument.objects.filter(id=eth.id),
        )

        self.assertEqual(result['created'], 2)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(InstrumentPriceSnapshot.objects.filter(instrument=eth).count(), 2)

    def test_backfill_price_snapshots_uses_range_provider_when_supported(self):
        eth = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='ETH', name='Ethereum')

        class PriceProvider:
            supports_historical_range = True

            def __init__(self):
                self.calls = 0

            def get_historical_prices(self, instrument, date_from, date_to):
                self.calls += 1
                self.requested_period = (date_from, date_to)
                return {
                    date(2026, 1, 1): PriceQuote(
                        instrument_id=str(instrument.id),
                        symbol=instrument.ticker,
                        price=Decimal('100.00'),
                        price_currency='USD',
                        source='test-price',
                    ),
                    date(2026, 1, 2): PriceQuote(
                        instrument_id=str(instrument.id),
                        symbol=instrument.ticker,
                        price=Decimal('101.00'),
                        price_currency='USD',
                        source='test-price',
                    ),
                }

        provider = PriceProvider()

        result = backfill_price_snapshots(
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 2),
            price_provider=provider,
            instruments=Instrument.objects.filter(id=eth.id),
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.requested_period, (date(2026, 1, 1), date(2026, 1, 2)))
        self.assertEqual(result['created'], 2)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(
            list(
                InstrumentPriceSnapshot.objects
                .filter(instrument=eth)
                .order_by('captured_at')
                .values_list('price', flat=True)
            ),
            [Decimal('100.00000000'), Decimal('101.00000000')],
        )

    def test_refresh_fx_rate_snapshots_creates_supported_cross_rates(self):
        result = refresh_fx_rate_snapshots(
            fx_provider=StaticFxRateProvider({
                ('USD', 'RUB'): '91.25',
                ('USD', 'EUR'): '0.90',
            }),
            pairs=[('USD', 'RUB'), ('USD', 'EUR')],
        )

        self.assertEqual(result['created'], 2)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(FxRateSnapshot.objects.count(), 2)
        self.assertTrue(FxRateSnapshot.objects.filter(base_currency='USD', quote_currency='RUB', rate=Decimal('91.25000000')).exists())
        self.assertTrue(FxRateSnapshot.objects.filter(base_currency='USD', quote_currency='EUR', rate=Decimal('0.90000000')).exists())

    def test_refresh_fx_rates_api_endpoint(self):
        with patch('investments.views.refresh_fx_rate_snapshots', return_value={'created': 1, 'failed': 0, 'results': []}):
            response = self.client.post('/api/v1/investment/fx-rates/refresh/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['created'], 1)

    def test_market_health_endpoint_reports_stale_prices(self):
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('100.00'),
            price_currency='USD',
            fx_rate_to_usd=Decimal('1'),
            price_usd=Decimal('100.00'),
            captured_at=self._dt(2026, 1, 1),
            source='test-price',
        )

        with patch('investments.services.timezone.localdate', return_value=date(2026, 1, 5)):
            response = self.client.get('/api/v1/investment/market-health/', {'max_age_days': '2'})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['prices']['total'], 1)
        self.assertEqual(response.data['prices']['stale'], 1)
        self.assertEqual(response.data['prices']['items'][0]['ticker'], 'BTC')
        self.assertEqual(response.data['prices']['items'][0]['status'], 'stale')
        self.assertTrue(response.data['prices']['items'][0]['uses_fallback'])
        self.assertIsNotNone(response.data['latest_successful_price_at'])

    def test_market_health_endpoint_validates_max_age(self):
        response = self.client.get('/api/v1/investment/market-health/', {'max_age_days': '-1'})

        self.assertEqual(response.status_code, 400)
        self.assertIn('max_age_days', response.data)

    def test_regular_user_does_not_see_foreign_portfolios_accounts_or_operations(self):
        _, other_portfolio, other_account, other_operation = self._create_foreign_investment_data()
        own_operation = self._create_buy_operation()

        portfolios_response = self.client.get('/api/v1/investment/portfolios/')
        accounts_response = self.client.get('/api/v1/investment/accounts/')
        operations_response = self.client.get('/api/v1/investment/operations/')
        foreign_overview_response = self.client.get('/api/v1/investment/portfolio-overview/', {
            'portfolio': str(other_portfolio.id),
        })

        self.assertEqual(portfolios_response.status_code, 200, portfolios_response.data)
        self.assertEqual(accounts_response.status_code, 200, accounts_response.data)
        self.assertEqual(operations_response.status_code, 200, operations_response.data)
        self.assertEqual(foreign_overview_response.status_code, 200, foreign_overview_response.data)
        portfolio_ids = {row['id'] for row in portfolios_response.data}
        account_ids = {row['id'] for row in accounts_response.data}
        operation_ids = {row['id'] for row in operations_response.data}
        self.assertIn(str(self.portfolio.id), portfolio_ids)
        self.assertNotIn(str(other_portfolio.id), portfolio_ids)
        self.assertIn(str(self.account.id), account_ids)
        self.assertNotIn(str(other_account.id), account_ids)
        self.assertIn(str(own_operation.id), operation_ids)
        self.assertNotIn(str(other_operation.id), operation_ids)
        self.assertIsNone(foreign_overview_response.data['portfolio'])
        self.assertEqual(foreign_overview_response.data['positions'], [])

    def test_regular_user_cannot_retrieve_or_use_foreign_investment_data(self):
        _, other_portfolio, other_account, other_operation = self._create_foreign_investment_data()

        self.assertEqual(self.client.get(f'/api/v1/investment/portfolios/{other_portfolio.id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/investment/accounts/{other_account.id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/investment/operations/{other_operation.id}/').status_code, 404)

        account_response = self.client.post('/api/v1/investment/accounts/', {
            'portfolio': str(other_portfolio.id),
            'name': 'Попытка чужого счета',
            'type': InvestmentAccount.TYPE_MANUAL,
            'currency': 'USD',
        }, format='json')
        operation_response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(other_portfolio.id),
            'account': str(other_account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_BUY,
            'quantity': '1.0000000000',
            'price_usd': '100000.00000000',
            'amount_usd': '100000.00',
        }, format='json')

        self.assertEqual(account_response.status_code, 400)
        self.assertIn('portfolio', account_response.data)
        self.assertEqual(operation_response.status_code, 400)
        self.assertIn('portfolio', operation_response.data)

    def test_staff_user_can_access_investment_data_across_users(self):
        _, other_portfolio, other_account, other_operation = self._create_foreign_investment_data()
        staff_user = CustomUser.objects.create_superuser(
            username='investment-admin',
            email='investment-admin@example.com',
            password='pass12345',
        )
        self.client.force_authenticate(staff_user)

        portfolios_response = self.client.get('/api/v1/investment/portfolios/')
        accounts_response = self.client.get('/api/v1/investment/accounts/')
        operations_response = self.client.get('/api/v1/investment/operations/', {'deleted': 'false'})

        self.assertEqual(portfolios_response.status_code, 200, portfolios_response.data)
        self.assertEqual(accounts_response.status_code, 200, accounts_response.data)
        self.assertEqual(operations_response.status_code, 200, operations_response.data)
        self.assertIn(str(other_portfolio.id), {row['id'] for row in portfolios_response.data})
        self.assertIn(str(other_account.id), {row['id'] for row in accounts_response.data})
        self.assertIn(str(other_operation.id), {row['id'] for row in operations_response.data})


class _FakeProviderResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload.encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.request_url = None
        self.timeout = None

    def __call__(self, request, timeout=None):
        self.request_url = request.full_url
        self.timeout = timeout
        return _FakeProviderResponse(self.payload)


class InvestmentPriceProviderTests(SimpleTestCase):
    def test_crypto_instrument_save_normalizes_common_ticker_to_provider_id(self):
        provider_symbol = Instrument.normalize_provider_symbol(Instrument.TYPE_CRYPTO, 'BTC', 'BTC')

        self.assertEqual(provider_symbol, 'bitcoin')

    def test_static_provider_returns_configured_quote(self):
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTC', ticker='BTC', quote_currency='USD')
        provider = StaticPriceProvider({('BTC', 'USD'): '62000.50'})

        quote = provider.get_price(instrument)

        self.assertEqual(quote.instrument_id, 'btc-id')
        self.assertEqual(quote.symbol, 'BTC')
        self.assertEqual(quote.price, Decimal('62000.50'))
        self.assertEqual(quote.price_currency, 'USD')
        self.assertEqual(quote.source, 'static')

    def test_static_provider_raises_controlled_error_for_missing_price(self):
        instrument = SimpleNamespace(id='eth-id', provider_symbol='ETH', ticker='ETH', quote_currency='USD')
        provider = StaticPriceProvider({('BTC', 'USD'): '62000.50'})

        with self.assertRaises(PriceProviderError):
            provider.get_price(instrument)

    def test_coingecko_provider_maps_common_crypto_tickers(self):
        opener = _FakeOpener('{"bitcoin": {"usd": 62000.5}}')
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTC', ticker='BTC', quote_currency='USD')
        provider = CoinGeckoPriceProvider(base_url='https://prices.example/simple', timeout=3, opener=opener)

        quote = provider.get_price(instrument)

        self.assertIn('ids=bitcoin', opener.request_url)
        self.assertIn('vs_currencies=usd', opener.request_url)
        self.assertEqual(opener.timeout, 3)
        self.assertEqual(quote.symbol, 'bitcoin')
        self.assertEqual(quote.price, Decimal('62000.5'))
        self.assertEqual(quote.price_currency, 'USD')
        self.assertEqual(quote.source, 'coingecko')

    def test_coingecko_provider_maps_sol_ticker(self):
        opener = _FakeOpener('{"solana": {"usd": 150.25}}')
        instrument = SimpleNamespace(id='sol-id', provider_symbol='SOL', ticker='SOL', quote_currency='USD')
        provider = CoinGeckoPriceProvider(base_url='https://prices.example/simple', opener=opener)

        quote = provider.get_price(instrument)

        self.assertIn('ids=solana', opener.request_url)
        self.assertEqual(quote.symbol, 'solana')
        self.assertEqual(quote.price, Decimal('150.25'))

    def test_coingecko_provider_reads_historical_price(self):
        opener = _FakeOpener('{"market_data": {"current_price": {"usd": 62000.5}}}')
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTC', ticker='BTC', quote_currency='USD')
        provider = CoinGeckoPriceProvider(history_base_url='https://prices.example/coins', opener=opener)

        quote = provider.get_historical_price(instrument, date(2026, 1, 10))

        self.assertIn('/bitcoin/history?', opener.request_url)
        self.assertIn('date=10-01-2026', opener.request_url)
        self.assertIn('localization=false', opener.request_url)
        self.assertEqual(quote.symbol, 'bitcoin')
        self.assertEqual(quote.price, Decimal('62000.5'))

    def test_coingecko_provider_reads_historical_prices_range(self):
        opener = _FakeOpener('{"prices": [[1767225600000, 62000.5], [1767312000000, 63010.25]]}')
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTC', ticker='BTC', quote_currency='USD')
        provider = CoinGeckoPriceProvider(history_base_url='https://prices.example/coins', opener=opener)

        quotes = provider.get_historical_prices(instrument, date(2026, 1, 1), date(2026, 1, 2))

        self.assertIn('/bitcoin/market_chart/range?', opener.request_url)
        self.assertIn('vs_currency=usd', opener.request_url)
        self.assertIn('from=1767225600', opener.request_url)
        self.assertIn('to=1767398399', opener.request_url)
        self.assertEqual(quotes[date(2026, 1, 1)].symbol, 'bitcoin')
        self.assertEqual(quotes[date(2026, 1, 1)].price, Decimal('62000.5'))
        self.assertEqual(quotes[date(2026, 1, 2)].price, Decimal('63010.25'))

    def test_coingecko_provider_does_not_map_exchange_pairs(self):
        opener = _FakeOpener('{"bitcoin": {"usd": 62000.5}}')
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTCUSDT', ticker='BTC', quote_currency='USD')
        provider = CoinGeckoPriceProvider(base_url='https://prices.example/simple', opener=opener)

        with self.assertRaises(PriceProviderError):
            provider.get_price(instrument)
        self.assertIn('ids=btcusdt', opener.request_url)

    def test_coingecko_provider_raises_controlled_error_for_missing_price(self):
        opener = _FakeOpener('{"bitcoin": {}}')
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTC', ticker='BTC', quote_currency='USD')
        provider = CoinGeckoPriceProvider(base_url='https://prices.example/simple', opener=opener)

        with self.assertRaises(PriceProviderError):
            provider.get_price(instrument)

    def test_stooq_provider_reads_stock_quote(self):
        opener = _FakeOpener('Symbol,Date,Time,Open,High,Low,Close,Volume\nAAPL.US,2026-01-10,22:00:00,190,195,189,194.50,1000\n')
        instrument = SimpleNamespace(id='aapl-id', type='stock', provider_symbol='AAPL.US', ticker='AAPL', quote_currency='USD')
        provider = StooqPriceProvider(quote_base_url='https://stocks.example/q/l/', opener=opener)

        quote = provider.get_price(instrument)

        self.assertIn('s=aapl.us', opener.request_url)
        self.assertEqual(quote.symbol, 'aapl.us')
        self.assertEqual(quote.price, Decimal('194.50'))
        self.assertEqual(quote.price_currency, 'USD')
        self.assertEqual(quote.source, 'stooq')

    def test_stooq_provider_reads_historical_stock_prices(self):
        opener = _FakeOpener('Date,Open,High,Low,Close,Volume\n2026-01-10,190,195,189,194.50,1000\n2026-01-11,194,198,193,197.10,900\n')
        instrument = SimpleNamespace(id='aapl-id', type='stock', provider_symbol='AAPL.US', ticker='AAPL', quote_currency='USD')
        provider = StooqPriceProvider(history_base_url='https://stocks.example/q/d/l/', opener=opener)

        quotes = provider.get_historical_prices(instrument, date(2026, 1, 10), date(2026, 1, 11))

        self.assertIn('s=aapl.us', opener.request_url)
        self.assertIn('d1=20260110', opener.request_url)
        self.assertIn('d2=20260111', opener.request_url)
        self.assertEqual(quotes[date(2026, 1, 10)].price, Decimal('194.50'))
        self.assertEqual(quotes[date(2026, 1, 11)].price, Decimal('197.10'))

    def test_composite_provider_routes_stocks_and_crypto(self):
        crypto_provider = StaticPriceProvider({('BTC', 'USD'): '62000.00'})
        stock_provider = StaticPriceProvider({('AAPL.US', 'USD'): '194.50'})
        provider = CompositePriceProvider(crypto_provider=crypto_provider, stock_provider=stock_provider)

        crypto_quote = provider.get_price(SimpleNamespace(id='btc-id', type='crypto', provider_symbol='BTC', ticker='BTC', quote_currency='USD'))
        stock_quote = provider.get_price(SimpleNamespace(id='aapl-id', type='stock', provider_symbol='AAPL.US', ticker='AAPL', quote_currency='USD'))

        self.assertEqual(crypto_quote.price, Decimal('62000.00'))
        self.assertEqual(stock_quote.price, Decimal('194.50'))

    def test_provider_factory_defaults_to_composite_provider(self):
        self.assertIsInstance(get_price_provider(), CompositePriceProvider)

    @override_settings(INVESTMENT_PRICE_PROVIDER='coingecko')
    def test_provider_factory_reads_settings(self):
        self.assertIsInstance(get_price_provider(), CoinGeckoPriceProvider)

    @override_settings(INVESTMENT_PRICE_PROVIDER='manual')
    def test_provider_factory_can_disable_automatic_provider(self):
        with self.assertRaises(PriceProviderError):
            get_price_provider()


class InvestmentFxRateProviderTests(SimpleTestCase):
    def test_static_fx_provider_returns_configured_rate(self):
        provider = StaticFxRateProvider({('USD', 'RUB'): '91.25'})

        quote = provider.get_rate('usd', 'rub')

        self.assertEqual(quote.base_currency, 'USD')
        self.assertEqual(quote.quote_currency, 'RUB')
        self.assertEqual(quote.rate, Decimal('91.25'))
        self.assertEqual(quote.source, 'static')

    def test_static_fx_provider_returns_one_for_same_currency(self):
        provider = StaticFxRateProvider({})

        quote = provider.get_rate('rub', 'rub')

        self.assertEqual(quote.rate, Decimal('1'))
        self.assertEqual(quote.base_currency, 'RUB')
        self.assertEqual(quote.quote_currency, 'RUB')

    def test_cbr_provider_returns_cross_currency_rates(self):
        payload = (
            '<ValCurs Date="10.05.2026">'
            '<Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>91,2500</Value></Valute>'
            '<Valute><CharCode>EUR</CharCode><Nominal>1</Nominal><Value>101,5000</Value></Valute>'
            '</ValCurs>'
        )
        opener = _FakeOpener(payload)
        provider = CbrFxRateProvider(base_url='https://rates.example/cbr.xml', timeout=4, opener=opener)

        usd_quote = provider.get_rate('USD', 'RUB')
        eur_quote = provider.get_rate('EUR', 'USD')

        self.assertEqual(opener.request_url, 'https://rates.example/cbr.xml')
        self.assertEqual(opener.timeout, 4)
        self.assertEqual(usd_quote.rate, Decimal('91.2500'))
        self.assertEqual(eur_quote.rate, Decimal('101.5000') / Decimal('91.2500'))
        self.assertEqual(usd_quote.source, 'cbr')

    def test_cbr_provider_requests_historical_rate_date(self):
        payload = (
            '<ValCurs Date="10.01.2026">'
            '<Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>91,2500</Value></Valute>'
            '</ValCurs>'
        )
        opener = _FakeOpener(payload)
        provider = CbrFxRateProvider(base_url='https://rates.example/cbr.xml', opener=opener)

        quote = provider.get_rate('USD', 'RUB', on_date=date(2026, 1, 10))

        self.assertIn('date_req=10%2F01%2F2026', opener.request_url)
        self.assertEqual(quote.rate, Decimal('91.2500'))

    def test_cbr_provider_raises_controlled_error_for_missing_currency(self):
        opener = _FakeOpener('<ValCurs><Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>91,25</Value></Valute></ValCurs>')
        provider = CbrFxRateProvider(opener=opener)

        with self.assertRaises(FxRateProviderError):
            provider.get_rate('EUR', 'RUB')

    def test_cbr_provider_returns_one_for_same_currency_without_fetching(self):
        provider = CbrFxRateProvider(opener=_FakeOpener('<ValCurs></ValCurs>'))

        quote = provider.get_rate('USD', 'USD')

        self.assertEqual(quote.rate, Decimal('1'))
        self.assertEqual(quote.base_currency, 'USD')
        self.assertEqual(quote.quote_currency, 'USD')

    @override_settings(INVESTMENT_FX_PROVIDER='cbr')
    def test_fx_provider_factory_reads_settings(self):
        self.assertIsInstance(get_fx_rate_provider(), CbrFxRateProvider)
