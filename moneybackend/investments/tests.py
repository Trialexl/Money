from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from money.models import BudgetExpense, BudgetIncome, FlowOfFunds, OneCSyncOutbox, Wallet
from users.models import CustomUser

from .models import Instrument, InvestmentAccount, InvestmentOperation, InvestmentPortfolio
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
