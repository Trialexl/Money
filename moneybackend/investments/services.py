from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .models import InstrumentPriceSnapshot, InvestmentOperation


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
        'positions': positions,
    }
