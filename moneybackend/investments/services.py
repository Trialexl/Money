from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from .fx_providers import FxRateProviderError, get_fx_rate_provider
from .models import FxRateSnapshot, Instrument, InstrumentPriceSnapshot, InvestmentOperation
from .price_providers import PriceProviderError, get_price_provider

ZERO_AMOUNT = Decimal('0')


@dataclass
class PositionState:
    instrument_id: str
    instrument_ticker: str
    instrument_name: str
    quantity: Decimal = ZERO_AMOUNT
    cost_basis_rub: Decimal = ZERO_AMOUNT
    realized_pl_rub: Decimal = ZERO_AMOUNT
    bought_rub: Decimal = ZERO_AMOUNT
    sold_rub: Decimal = ZERO_AMOUNT

    @property
    def average_buy_price_rub(self):
        if self.quantity == ZERO_AMOUNT:
            return ZERO_AMOUNT
        return self.cost_basis_rub / self.quantity


def _money(value):
    return (value or ZERO_AMOUNT).quantize(Decimal('0.01'))


def _percent(value):
    if value is None:
        return None
    return value.quantize(Decimal('0.01'))


def _latest_price_snapshots(instrument_ids):
    latest = {}
    if not instrument_ids:
        return latest

    snapshots = (
        InstrumentPriceSnapshot.objects
        .filter(instrument_id__in=instrument_ids)
        .order_by('instrument_id', '-captured_at', '-created_at')
    )
    for snapshot in snapshots:
        latest.setdefault(snapshot.instrument_id, snapshot)
    return latest


def calculate_positions(portfolio, *, include_zero=False):
    positions = {}

    operations = (
        InvestmentOperation.objects
        .filter(portfolio=portfolio, deleted=False, posted=True)
        .select_related('instrument')
        .order_by('date', 'created_at', 'id')
    )

    for operation in operations:
        instrument = operation.instrument
        state = positions.get(instrument.id)
        if state is None:
            state = PositionState(
                instrument_id=str(instrument.id),
                instrument_ticker=instrument.ticker,
                instrument_name=instrument.name,
            )
            positions[instrument.id] = state

        quantity = operation.quantity or ZERO_AMOUNT
        amount_rub = operation.amount_rub or ZERO_AMOUNT
        fee_rub = operation.fee_rub or ZERO_AMOUNT

        if operation.operation_type == InvestmentOperation.TYPE_BUY:
            state.quantity += quantity
            state.cost_basis_rub += amount_rub + fee_rub
            state.bought_rub += amount_rub + fee_rub
        elif operation.operation_type == InvestmentOperation.TYPE_SELL:
            if quantity > state.quantity:
                raise ValueError(f'Продажа {instrument.ticker} превышает текущий остаток.')
            average_price = state.average_buy_price_rub
            sold_cost_basis = average_price * quantity
            proceeds = amount_rub - fee_rub
            state.quantity -= quantity
            state.cost_basis_rub -= sold_cost_basis
            state.realized_pl_rub += proceeds - sold_cost_basis
            state.sold_rub += proceeds
            if state.quantity == ZERO_AMOUNT:
                state.cost_basis_rub = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_CORRECTION:
            state.quantity += quantity
            state.cost_basis_rub += amount_rub
            if state.quantity == ZERO_AMOUNT:
                state.cost_basis_rub = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_TRANSFER:
            # Перевод между инвестиционными счетами не меняет агрегированную позицию портфеля.
            continue

    latest_prices = _latest_price_snapshots(positions.keys())

    result = []
    for instrument_id, state in positions.items():
        if not include_zero and state.quantity == ZERO_AMOUNT:
            continue
        snapshot = latest_prices.get(instrument_id)
        latest_price_rub = _money(snapshot.price_rub) if snapshot is not None else None
        current_value_rub = _money(latest_price_rub * state.quantity) if latest_price_rub is not None and state.quantity != ZERO_AMOUNT else None
        unrealized_pl_rub = _money(current_value_rub - state.cost_basis_rub) if current_value_rub is not None else None
        total_pl_rub = _money(state.realized_pl_rub + (unrealized_pl_rub or ZERO_AMOUNT))
        return_percent = None
        if unrealized_pl_rub is not None and state.cost_basis_rub != ZERO_AMOUNT:
            return_percent = _percent((total_pl_rub / state.cost_basis_rub) * Decimal('100'))
        result.append({
            'instrument_id': state.instrument_id,
            'instrument_ticker': state.instrument_ticker,
            'instrument_name': state.instrument_name,
            'quantity': state.quantity,
            'cost_basis_rub': _money(state.cost_basis_rub),
            'average_buy_price_rub': _money(state.average_buy_price_rub),
            'latest_price_rub': latest_price_rub,
            'latest_price_at': snapshot.captured_at if snapshot is not None else None,
            'current_value_rub': current_value_rub,
            'realized_pl_rub': _money(state.realized_pl_rub),
            'unrealized_pl_rub': unrealized_pl_rub,
            'total_pl_rub': total_pl_rub,
            'return_percent': return_percent,
            'bought_rub': _money(state.bought_rub),
            'sold_rub': _money(state.sold_rub),
        })

    total_current_value = sum(
        (row['current_value_rub'] for row in result if row['current_value_rub'] is not None),
        ZERO_AMOUNT,
    )
    for row in result:
        row['allocation_percent'] = (
            _percent((row['current_value_rub'] / total_current_value) * Decimal('100'))
            if row['current_value_rub'] is not None and total_current_value != ZERO_AMOUNT
            else None
        )
        row['target_allocation_percent'] = None
        row['allocation_deviation_percent'] = None

    return sorted(result, key=lambda row: row['instrument_ticker'])


def calculate_instrument_quantity(portfolio, instrument, *, exclude_operation=None):
    quantity = ZERO_AMOUNT
    queryset = InvestmentOperation.objects.filter(
        portfolio=portfolio,
        instrument=instrument,
        deleted=False,
        posted=True,
    )
    if exclude_operation is not None and exclude_operation.pk:
        queryset = queryset.exclude(pk=exclude_operation.pk)

    for operation in queryset:
        if operation.operation_type == InvestmentOperation.TYPE_BUY:
            quantity += operation.quantity
        elif operation.operation_type == InvestmentOperation.TYPE_SELL:
            quantity -= operation.quantity
        elif operation.operation_type == InvestmentOperation.TYPE_CORRECTION:
            quantity += operation.quantity

    return quantity


def calculate_portfolio_totals(portfolio):
    positions = calculate_positions(portfolio, include_zero=True)
    totals = defaultdict(lambda: ZERO_AMOUNT)
    valuation_complete = True

    for position in positions:
        totals['cost_basis_rub'] += position['cost_basis_rub']
        totals['realized_pl_rub'] += position['realized_pl_rub']
        if position['current_value_rub'] is None and position['quantity'] != ZERO_AMOUNT:
            valuation_complete = False
        if position['current_value_rub'] is not None:
            totals['current_value_rub'] += position['current_value_rub']
        if position['unrealized_pl_rub'] is not None:
            totals['unrealized_pl_rub'] += position['unrealized_pl_rub']
        totals['bought_rub'] += position['bought_rub']
        totals['sold_rub'] += position['sold_rub']

    total_pl_rub = totals['realized_pl_rub'] + totals['unrealized_pl_rub']
    return_percent = None
    if valuation_complete and totals['cost_basis_rub'] != ZERO_AMOUNT:
        return_percent = _percent((total_pl_rub / totals['cost_basis_rub']) * Decimal('100'))
    largest_asset = None
    positions_with_value = [position for position in positions if position['current_value_rub'] is not None]
    if positions_with_value:
        largest_asset = max(positions_with_value, key=lambda position: position['current_value_rub'])
    latest_price_at = None
    latest_price_dates = [position['latest_price_at'] for position in positions if position['latest_price_at'] is not None]
    if latest_price_dates:
        latest_price_at = max(latest_price_dates)

    return {
        'cost_basis_rub': _money(totals['cost_basis_rub']),
        'current_value_rub': _money(totals['current_value_rub']),
        'realized_pl_rub': _money(totals['realized_pl_rub']),
        'unrealized_pl_rub': _money(totals['unrealized_pl_rub']),
        'total_pl_rub': _money(total_pl_rub),
        'return_percent': return_percent,
        'valuation_complete': valuation_complete,
        'bought_rub': _money(totals['bought_rub']),
        'sold_rub': _money(totals['sold_rub']),
        'largest_asset': largest_asset,
        'latest_price_at': latest_price_at,
        'positions': positions,
    }


def refresh_price_snapshots(*, price_provider=None, fx_provider=None, instruments=None, captured_at=None):
    price_provider = price_provider or get_price_provider()
    fx_provider = fx_provider or get_fx_rate_provider()
    captured_at = captured_at or timezone.now()
    instrument_queryset = (
        instruments
        if instruments is not None
        else Instrument.objects.filter(is_active=True).order_by('type', 'ticker')
    )
    fx_cache = {}
    results = []

    for instrument in instrument_queryset:
        try:
            price_quote = price_provider.get_price(instrument)
            price_currency = price_quote.price_currency.strip().upper()
            fx_rate = Decimal('1')
            fx_snapshot_id = None

            if price_currency != 'RUB':
                if price_currency not in fx_cache:
                    fx_quote = fx_provider.get_rate(price_currency, 'RUB')
                    fx_snapshot = FxRateSnapshot.objects.create(
                        captured_at=captured_at,
                        base_currency=fx_quote.base_currency,
                        quote_currency=fx_quote.quote_currency,
                        rate=fx_quote.rate,
                        source=fx_quote.source,
                    )
                    fx_cache[price_currency] = (fx_quote.rate, str(fx_snapshot.id))
                fx_rate, fx_snapshot_id = fx_cache[price_currency]

            snapshot = InstrumentPriceSnapshot.objects.create(
                instrument=instrument,
                captured_at=captured_at,
                price=price_quote.price,
                price_currency=price_currency,
                fx_rate_to_rub=fx_rate,
                price_rub=_money(price_quote.price * fx_rate),
                source=price_quote.source,
            )
            results.append({
                'instrument_id': str(instrument.id),
                'ticker': instrument.ticker,
                'status': 'created',
                'price_snapshot_id': str(snapshot.id),
                'fx_rate_snapshot_id': fx_snapshot_id,
                'price': str(price_quote.price),
                'price_currency': price_currency,
                'fx_rate_to_rub': str(fx_rate),
                'price_rub': f'{snapshot.price_rub:.2f}',
                'source': price_quote.source,
            })
        except (PriceProviderError, FxRateProviderError) as exc:
            results.append({
                'instrument_id': str(instrument.id),
                'ticker': instrument.ticker,
                'status': 'error',
                'error': str(exc),
            })

    return {
        'created': sum(1 for row in results if row['status'] == 'created'),
        'failed': sum(1 for row in results if row['status'] == 'error'),
        'results': results,
    }
