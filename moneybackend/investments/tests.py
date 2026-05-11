from decimal import Decimal
from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from money.models import BudgetExpense, BudgetIncome, FlowOfFunds, OneCSyncOutbox, Wallet
from users.models import CustomUser

from .fx_providers import CbrFxRateProvider, FxRateProviderError, FxRateQuote, StaticFxRateProvider, get_fx_rate_provider
from .models import FxRateSnapshot, Instrument, InstrumentPriceSnapshot, InvestmentAccount, InvestmentOperation, InvestmentPortfolio
from .price_providers import CoinGeckoPriceProvider, PriceProviderError, PriceQuote, StaticPriceProvider, get_price_provider
from .services import calculate_positions, calculate_portfolio_totals, refresh_price_snapshots


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
            price=Decimal('200000.00000000'),
            price_currency='RUB',
            amount=Decimal('400000.00000000'),
            amount_currency='RUB',
            amount_rub=Decimal('400000.00'),
            fx_rate_to_rub=Decimal('1.00000000'),
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
        self.assertEqual(positions[0]['allocation_percent'], Decimal('100.00'))
        self.assertIsNone(positions[0]['target_allocation_percent'])
        self.assertIsNone(positions[0]['allocation_deviation_percent'])
        self.assertEqual(totals['current_value_rub'], Decimal('150.00'))
        self.assertEqual(totals['unrealized_pl_rub'], Decimal('50.00'))
        self.assertEqual(totals['total_pl_rub'], Decimal('50.00'))
        self.assertTrue(totals['valuation_complete'])
        self.assertEqual(totals['largest_asset']['instrument_ticker'], 'BTC')
        self.assertIsNotNone(totals['latest_price_at'])

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
        self.assertIn('/api/v1/investment/prices/refresh/', content)
        self.assertIn('/api/v1/investment/fx-rates/', content)
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

    def test_refresh_price_snapshots_creates_price_and_fx_snapshots(self):
        eth = Instrument.objects.create(type=Instrument.TYPE_CRYPTO, ticker='ETH', name='Ethereum')

        class PriceProvider:
            def get_price(self, instrument):
                return PriceQuote(
                    instrument_id=str(instrument.id),
                    symbol=instrument.ticker,
                    price=Decimal('100.00'),
                    price_currency='USD',
                    source='test-price',
                )

        class FxProvider:
            def get_rate(self, base_currency, quote_currency='RUB'):
                return FxRateQuote(
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    rate=Decimal('90.00000000'),
                    source='test-fx',
                )

        result = refresh_price_snapshots(price_provider=PriceProvider(), fx_provider=FxProvider())

        self.assertEqual(result['created'], 2)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(InstrumentPriceSnapshot.objects.count(), 2)
        self.assertEqual(FxRateSnapshot.objects.count(), 1)
        eth_snapshot = InstrumentPriceSnapshot.objects.get(instrument=eth)
        self.assertEqual(eth_snapshot.price_currency, 'USD')
        self.assertEqual(eth_snapshot.fx_rate_to_rub, Decimal('90.00000000'))
        self.assertEqual(eth_snapshot.price_rub, Decimal('9000.00'))
        self.assertEqual(eth_snapshot.source, 'test-price')

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
            'currency': 'RUB',
        }, format='json')
        operation_response = self.client.post('/api/v1/investment/operations/', {
            'portfolio': str(other_portfolio.id),
            'account': str(other_account.id),
            'instrument': str(self.instrument.id),
            'operation_type': InvestmentOperation.TYPE_BUY,
            'quantity': '1.0000000000',
            'price': '100000.00000000',
            'price_currency': 'RUB',
            'amount': '100000.00000000',
            'amount_currency': 'RUB',
            'amount_rub': '100000.00',
            'fx_rate_to_rub': '1.00000000',
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

    def test_coingecko_provider_raises_controlled_error_for_missing_price(self):
        opener = _FakeOpener('{"bitcoin": {}}')
        instrument = SimpleNamespace(id='btc-id', provider_symbol='BTC', ticker='BTC', quote_currency='USD')
        provider = CoinGeckoPriceProvider(base_url='https://prices.example/simple', opener=opener)

        with self.assertRaises(PriceProviderError):
            provider.get_price(instrument)

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

    def test_cbr_provider_returns_usd_and_eur_rates(self):
        payload = (
            '<ValCurs Date="10.05.2026">'
            '<Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>91,2500</Value></Valute>'
            '<Valute><CharCode>EUR</CharCode><Nominal>1</Nominal><Value>101,5000</Value></Valute>'
            '</ValCurs>'
        )
        opener = _FakeOpener(payload)
        provider = CbrFxRateProvider(base_url='https://rates.example/cbr.xml', timeout=4, opener=opener)

        usd_quote = provider.get_rate('USD', 'RUB')
        eur_quote = provider.get_rate('EUR', 'RUB')

        self.assertEqual(opener.request_url, 'https://rates.example/cbr.xml')
        self.assertEqual(opener.timeout, 4)
        self.assertEqual(usd_quote.rate, Decimal('91.2500'))
        self.assertEqual(eur_quote.rate, Decimal('101.5000'))
        self.assertEqual(usd_quote.source, 'cbr')

    def test_cbr_provider_raises_controlled_error_for_missing_currency(self):
        opener = _FakeOpener('<ValCurs><Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>91,25</Value></Valute></ValCurs>')
        provider = CbrFxRateProvider(opener=opener)

        with self.assertRaises(FxRateProviderError):
            provider.get_rate('EUR', 'RUB')

    def test_cbr_provider_rejects_non_rub_quote_currency(self):
        provider = CbrFxRateProvider(opener=_FakeOpener('<ValCurs></ValCurs>'))

        with self.assertRaises(FxRateProviderError):
            provider.get_rate('USD', 'EUR')

    @override_settings(INVESTMENT_FX_PROVIDER='cbr')
    def test_fx_provider_factory_reads_settings(self):
        self.assertIsInstance(get_fx_rate_provider(), CbrFxRateProvider)
