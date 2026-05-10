from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from money.models import BudgetExpense, BudgetIncome, FlowOfFunds, OneCSyncOutbox, Wallet
from users.models import CustomUser

from .models import Instrument, InstrumentPriceSnapshot, InvestmentAccount, InvestmentOperation, InvestmentPortfolio
from .services import calculate_positions, calculate_portfolio_totals


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
            price=Decimal('100000.00000000'),
            price_currency='RUB',
            amount=Decimal('100000.00000000'),
            amount_currency='RUB',
            amount_rub=Decimal('100000.00'),
            fx_rate_to_rub=Decimal('1.00000000'),
            date=timezone.now(),
        )

    def test_buy_operation_does_not_create_money_registers_or_onec_outbox(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_BUY,
            'quantity': '0.1000000000',
            'price': '1000000.00000000',
            'price_currency': 'RUB',
            'amount': '100000.00000000',
            'amount_currency': 'RUB',
            'amount_rub': '100000.00',
            'fx_rate_to_rub': '1.00000000',
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
            'price': '120000.00000000',
            'price_currency': 'RUB',
            'amount': '60000.00000000',
            'amount_currency': 'RUB',
            'amount_rub': '60000.00',
            'fx_rate_to_rub': '1.00000000',
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
            price=Decimal('120000.00000000'),
            price_currency='RUB',
            amount=Decimal('30000.00000000'),
            amount_currency='RUB',
            amount_rub=Decimal('30000.00'),
            fx_rate_to_rub=Decimal('1.00000000'),
            date=operation.date + timedelta(hours=1),
        )
        date_from = (operation.date - timedelta(days=1)).isoformat()
        date_to = (operation.date + timedelta(days=1)).isoformat()

        dashboard_response = self.client.get('/api/v1/dashboard/overview/', {'date': operation.date.isoformat()})
        cash_flow_response = self.client.get('/api/v1/reports/cash-flow/', {'date_from': date_from, 'date_to': date_to})
        budget_expense_response = self.client.get('/api/v1/reports/budget-expense/', {'date_from': date_from, 'date_to': date_to})
        budget_income_response = self.client.get('/api/v1/reports/budget-income/', {'date_from': date_from, 'date_to': date_to})

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
            price=Decimal('100.00'),
            amount=Decimal('100.00'),
            amount_rub=Decimal('100.00'),
            date=timezone.now(),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price=Decimal('200.00'),
            amount=Decimal('200.00'),
            amount_rub=Decimal('200.00'),
            date=timezone.now(),
        )
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_SELL,
            quantity=Decimal('0.5'),
            price=Decimal('300.00'),
            amount=Decimal('150.00'),
            amount_rub=Decimal('150.00'),
            date=timezone.now(),
        )

        positions = calculate_positions(self.portfolio)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]['quantity'], Decimal('1.5000000000'))
        self.assertEqual(positions[0]['average_buy_price_rub'], Decimal('150.00'))
        self.assertEqual(positions[0]['cost_basis_rub'], Decimal('225.00'))
        self.assertEqual(positions[0]['realized_pl_rub'], Decimal('75.00'))

    def test_positions_use_latest_price_for_unrealized_pl(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price=Decimal('100.00'),
            amount=Decimal('100.00'),
            amount_rub=Decimal('100.00'),
            date=timezone.now(),
        )
        InstrumentPriceSnapshot.objects.create(
            instrument=self.instrument,
            price=Decimal('150.00'),
            price_currency='RUB',
            fx_rate_to_rub=Decimal('1'),
            price_rub=Decimal('150.00'),
            captured_at=timezone.now(),
        )

        positions = calculate_positions(self.portfolio)
        totals = calculate_portfolio_totals(self.portfolio)

        self.assertEqual(positions[0]['current_value_rub'], Decimal('150.00'))
        self.assertEqual(positions[0]['unrealized_pl_rub'], Decimal('50.00'))
        self.assertEqual(positions[0]['total_pl_rub'], Decimal('50.00'))
        self.assertEqual(positions[0]['return_percent'], Decimal('50.00'))
        self.assertEqual(totals['current_value_rub'], Decimal('150.00'))
        self.assertEqual(totals['unrealized_pl_rub'], Decimal('50.00'))
        self.assertEqual(totals['total_pl_rub'], Decimal('50.00'))
        self.assertTrue(totals['valuation_complete'])

    def test_portfolio_overview_endpoint_returns_default_portfolio(self):
        InvestmentOperation.objects.create(
            portfolio=self.portfolio,
            account=self.account,
            instrument=self.instrument,
            operation_type=InvestmentOperation.TYPE_BUY,
            quantity=Decimal('1.0'),
            price=Decimal('100.00'),
            amount=Decimal('100.00'),
            amount_rub=Decimal('100.00'),
            date=timezone.now(),
        )

        response = self.client.get('/api/v1/investment/portfolio-overview/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['portfolio']['id'], str(self.portfolio.id))
        self.assertEqual(response.data['cost_basis_rub'], '100.00')

    def test_sell_more_than_position_is_rejected(self):
        response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(self.portfolio.id),
            'account': str(self.account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_SELL,
            'quantity': '1.0000000000',
            'price': '1000000.00000000',
            'price_currency': 'RUB',
            'amount': '1000000.00000000',
            'amount_currency': 'RUB',
            'amount_rub': '1000000.00',
            'fx_rate_to_rub': '1.00000000',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('quantity', response.data)

    def test_openapi_schema_contains_investment_contract(self):
        response = self.client.get('/api/schema/')

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('/api/v1/investment/instruments/', content)
        self.assertIn('/api/v1/investment/prices/', content)
        self.assertIn('/api/v1/investment/portfolios/', content)
        self.assertIn('/api/v1/investment/accounts/', content)
        self.assertIn('/api/v1/investment/operations/', content)
        self.assertIn('/api/v1/investment/portfolio-overview/', content)
        self.assertIn('InstrumentPriceSnapshot', content)
        self.assertIn('InvestmentOperationRequest', content)
        self.assertIn('operation_type', content)
        self.assertIn('date_from', content)
        self.assertIn('date_to', content)
        self.assertIn('Инвестиционный модуль не синхронизируется с 1С.', content)
