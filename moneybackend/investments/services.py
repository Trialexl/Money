from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .models import InvestmentOperation


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

    result = []
    for state in positions.values():
        if not include_zero and state.quantity == ZERO_AMOUNT:
            continue
        result.append({
            'instrument_id': state.instrument_id,
            'instrument_ticker': state.instrument_ticker,
            'instrument_name': state.instrument_name,
            'quantity': state.quantity,
            'cost_basis_rub': _money(state.cost_basis_rub),
            'average_buy_price_rub': _money(state.average_buy_price_rub),
            'realized_pl_rub': _money(state.realized_pl_rub),
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

    for position in positions:
        totals['cost_basis_rub'] += position['cost_basis_rub']
        totals['realized_pl_rub'] += position['realized_pl_rub']
        totals['bought_rub'] += position['bought_rub']
        totals['sold_rub'] += position['sold_rub']

    return {
        'cost_basis_rub': _money(totals['cost_basis_rub']),
        'realized_pl_rub': _money(totals['realized_pl_rub']),
        'bought_rub': _money(totals['bought_rub']),
        'sold_rub': _money(totals['sold_rub']),
        'positions': positions,
    }
