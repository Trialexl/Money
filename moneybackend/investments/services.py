from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import calendar

from django.utils import timezone

from .fx_providers import FxRateProviderError, get_fx_rate_provider
from .models import FxRateSnapshot, Instrument, InstrumentPriceSnapshot, InvestmentOperation, InvestmentTargetAllocation
from .price_providers import PriceProviderError, get_price_provider

ZERO_AMOUNT = Decimal('0')


@dataclass
class PositionState:
    instrument_id: str
    instrument_ticker: str
    instrument_name: str
    quantity: Decimal = ZERO_AMOUNT
    cost_basis_usd: Decimal = ZERO_AMOUNT
    realized_pl_usd: Decimal = ZERO_AMOUNT
    bought_usd: Decimal = ZERO_AMOUNT
    sold_usd: Decimal = ZERO_AMOUNT

    @property
    def average_buy_price_usd(self):
        if self.quantity == ZERO_AMOUNT:
            return ZERO_AMOUNT
        return self.cost_basis_usd / self.quantity


def _money(value):
    return (value or ZERO_AMOUNT).quantize(Decimal('0.01'))


def _percent(value):
    if value is None:
        return None
    return value.quantize(Decimal('0.01'))


def _aware_datetime(value, *, end_of_day=False):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, time.max if end_of_day else time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _month_end(value):
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _next_day(value):
    return value + timedelta(days=1)


def _next_month(value):
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _latest_price_snapshots(instrument_ids, *, as_of=None):
    latest = {}
    if not instrument_ids:
        return latest

    snapshots = (
        InstrumentPriceSnapshot.objects
        .filter(instrument_id__in=instrument_ids)
        .order_by('instrument_id', '-captured_at', '-created_at')
    )
    if as_of is not None:
        snapshots = snapshots.filter(captured_at__lte=as_of)
    for snapshot in snapshots:
        latest.setdefault(snapshot.instrument_id, snapshot)
    return latest


def calculate_positions(portfolio, *, include_zero=False, as_of=None, price_as_of=None, include_targets=False):
    positions = {}

    operations = (
        InvestmentOperation.objects
        .filter(portfolio=portfolio, deleted=False, posted=True)
        .select_related('instrument')
        .order_by('date', 'created_at', 'id')
    )
    if as_of is not None:
        operations = operations.filter(date__lte=as_of)

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
        amount_usd = operation.amount_usd or ZERO_AMOUNT
        fee_usd = operation.fee_usd or ZERO_AMOUNT

        if operation.operation_type == InvestmentOperation.TYPE_BUY:
            state.quantity += quantity
            state.cost_basis_usd += amount_usd + fee_usd
            state.bought_usd += amount_usd + fee_usd
        elif operation.operation_type == InvestmentOperation.TYPE_SELL:
            if quantity > state.quantity:
                raise ValueError(f'Продажа {instrument.ticker} превышает текущий остаток.')
            average_price = state.average_buy_price_usd
            sold_cost_basis = average_price * quantity
            proceeds = amount_usd - fee_usd
            state.quantity -= quantity
            state.cost_basis_usd -= sold_cost_basis
            state.realized_pl_usd += proceeds - sold_cost_basis
            state.sold_usd += proceeds
            if state.quantity == ZERO_AMOUNT:
                state.cost_basis_usd = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_CORRECTION:
            state.quantity += quantity
            state.cost_basis_usd += amount_usd
            if state.quantity == ZERO_AMOUNT:
                state.cost_basis_usd = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_TRANSFER:
            # Перевод между инвестиционными счетами не меняет агрегированную позицию портфеля.
            continue

    latest_prices = _latest_price_snapshots(positions.keys(), as_of=price_as_of or as_of)
    target_allocations = {
        str(allocation.instrument_id): allocation
        for allocation in InvestmentTargetAllocation.objects.filter(portfolio=portfolio).select_related('instrument')
    }

    result = []
    for instrument_id, state in positions.items():
        if not include_zero and state.quantity == ZERO_AMOUNT:
            continue
        snapshot = latest_prices.get(instrument_id)
        latest_price_usd = _money(snapshot.price_usd) if snapshot is not None else None
        current_value_usd = _money(latest_price_usd * state.quantity) if latest_price_usd is not None and state.quantity != ZERO_AMOUNT else None
        unrealized_pl_usd = _money(current_value_usd - state.cost_basis_usd) if current_value_usd is not None else None
        total_pl_usd = _money(state.realized_pl_usd + (unrealized_pl_usd or ZERO_AMOUNT))
        return_percent = None
        if unrealized_pl_usd is not None and state.cost_basis_usd != ZERO_AMOUNT:
            return_percent = _percent((total_pl_usd / state.cost_basis_usd) * Decimal('100'))
        result.append({
            'instrument_id': state.instrument_id,
            'instrument_ticker': state.instrument_ticker,
            'instrument_name': state.instrument_name,
            'quantity': state.quantity,
            'cost_basis_usd': _money(state.cost_basis_usd),
            'average_buy_price_usd': _money(state.average_buy_price_usd),
            'latest_price_usd': latest_price_usd,
            'latest_price_at': snapshot.captured_at if snapshot is not None else None,
            'current_value_usd': current_value_usd,
            'realized_pl_usd': _money(state.realized_pl_usd),
            'unrealized_pl_usd': unrealized_pl_usd,
            'total_pl_usd': total_pl_usd,
            'return_percent': return_percent,
            'bought_usd': _money(state.bought_usd),
            'sold_usd': _money(state.sold_usd),
        })

    if include_targets:
        existing_instrument_ids = {row['instrument_id'] for row in result}
        for allocation in target_allocations.values():
            if str(allocation.instrument_id) in existing_instrument_ids:
                continue
            result.append({
                'instrument_id': str(allocation.instrument_id),
                'instrument_ticker': allocation.instrument.ticker,
                'instrument_name': allocation.instrument.name,
                'quantity': ZERO_AMOUNT,
                'cost_basis_usd': ZERO_AMOUNT,
                'average_buy_price_usd': ZERO_AMOUNT,
                'latest_price_usd': None,
                'latest_price_at': None,
                'current_value_usd': ZERO_AMOUNT,
                'realized_pl_usd': ZERO_AMOUNT,
                'unrealized_pl_usd': ZERO_AMOUNT,
                'total_pl_usd': ZERO_AMOUNT,
                'return_percent': None,
                'bought_usd': ZERO_AMOUNT,
                'sold_usd': ZERO_AMOUNT,
            })

    total_current_value = sum(
        (row['current_value_usd'] for row in result if row['current_value_usd'] is not None),
        ZERO_AMOUNT,
    )
    for row in result:
        allocation = target_allocations.get(row['instrument_id'])
        current_value_usd = row['current_value_usd'] or ZERO_AMOUNT
        target_percent = allocation.target_percent if allocation is not None else None
        tolerance_percent = allocation.tolerance_percent if allocation is not None else None
        row['allocation_percent'] = (
            _percent((row['current_value_usd'] / total_current_value) * Decimal('100'))
            if row['current_value_usd'] is not None and total_current_value != ZERO_AMOUNT
            else None
        )
        row['target_allocation_percent'] = target_percent
        row['tolerance_percent'] = tolerance_percent
        row['allocation_deviation_percent'] = (
            _percent((row['allocation_percent'] or ZERO_AMOUNT) - target_percent)
            if target_percent is not None
            else None
        )
        target_value_usd = _money((total_current_value * target_percent / Decimal('100'))) if target_percent is not None else None
        allocation_deviation_usd = _money(current_value_usd - target_value_usd) if target_value_usd is not None else None
        row['target_value_usd'] = target_value_usd
        row['allocation_deviation_usd'] = allocation_deviation_usd
        row['is_within_tolerance'] = (
            abs(row['allocation_deviation_percent']) <= tolerance_percent
            if row['allocation_deviation_percent'] is not None and tolerance_percent is not None
            else None
        )
        if allocation_deviation_usd is None or allocation_deviation_usd == ZERO_AMOUNT:
            row['rebalance_action'] = 'hold'
            row['rebalance_amount_usd'] = ZERO_AMOUNT
        elif allocation_deviation_usd > ZERO_AMOUNT:
            row['rebalance_action'] = 'sell'
            row['rebalance_amount_usd'] = allocation_deviation_usd
        else:
            row['rebalance_action'] = 'buy'
            row['rebalance_amount_usd'] = abs(allocation_deviation_usd)

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


def calculate_portfolio_totals(portfolio, *, as_of=None):
    positions = calculate_positions(portfolio, include_zero=True, as_of=as_of, price_as_of=as_of)
    totals = defaultdict(lambda: ZERO_AMOUNT)
    valuation_complete = True

    for position in positions:
        totals['cost_basis_usd'] += position['cost_basis_usd']
        totals['realized_pl_usd'] += position['realized_pl_usd']
        if position['current_value_usd'] is None and position['quantity'] != ZERO_AMOUNT:
            valuation_complete = False
        if position['current_value_usd'] is not None:
            totals['current_value_usd'] += position['current_value_usd']
        if position['unrealized_pl_usd'] is not None:
            totals['unrealized_pl_usd'] += position['unrealized_pl_usd']
        totals['bought_usd'] += position['bought_usd']
        totals['sold_usd'] += position['sold_usd']

    total_pl_usd = totals['realized_pl_usd'] + totals['unrealized_pl_usd']
    return_percent = None
    if valuation_complete and totals['cost_basis_usd'] != ZERO_AMOUNT:
        return_percent = _percent((total_pl_usd / totals['cost_basis_usd']) * Decimal('100'))
    largest_asset = None
    positions_with_value = [position for position in positions if position['current_value_usd'] is not None]
    if positions_with_value:
        largest_asset = max(positions_with_value, key=lambda position: position['current_value_usd'])
    latest_price_at = None
    latest_price_dates = [position['latest_price_at'] for position in positions if position['latest_price_at'] is not None]
    if latest_price_dates:
        latest_price_at = max(latest_price_dates)

    return {
        'cost_basis_usd': _money(totals['cost_basis_usd']),
        'current_value_usd': _money(totals['current_value_usd']),
        'realized_pl_usd': _money(totals['realized_pl_usd']),
        'unrealized_pl_usd': _money(totals['unrealized_pl_usd']),
        'total_pl_usd': _money(total_pl_usd),
        'return_percent': return_percent,
        'valuation_complete': valuation_complete,
        'bought_usd': _money(totals['bought_usd']),
        'sold_usd': _money(totals['sold_usd']),
        'largest_asset': largest_asset,
        'latest_price_at': latest_price_at,
        'positions': positions,
    }


def calculate_portfolio_performance(portfolio, *, date_from, date_to, group_by='month'):
    if date_from > date_to:
        raise ValueError('date_from must be before or equal to date_to.')
    if group_by not in {'day', 'month'}:
        raise ValueError('group_by must be day or month.')

    start_dt = _aware_datetime(date_from)
    opening_cutoff = start_dt - timedelta(microseconds=1)
    opening = _performance_totals_for_cutoff(portfolio, opening_cutoff, label='Старт')
    opening.update({
        'date': date_from.isoformat(),
        'period_start': None,
        'period_end': date_from.isoformat(),
    })

    points = []
    cursor = date_from
    while cursor <= date_to:
        if group_by == 'day':
            period_start = cursor
            period_end = min(cursor, date_to)
            cursor = _next_day(cursor)
            label = period_end.isoformat()
        else:
            period_start = cursor
            period_end = min(_month_end(cursor), date_to)
            cursor = _next_month(date(period_end.year, period_end.month, 1))
            label = period_end.strftime('%Y-%m')

        cutoff = _aware_datetime(period_end, end_of_day=True)
        point = _performance_totals_for_cutoff(portfolio, cutoff, label=label)
        point.update({
            'date': period_end.isoformat(),
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
        })
        points.append(point)

    return {
        'portfolio_id': str(portfolio.id),
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'group_by': group_by,
        'opening': opening,
        'points': points,
    }


def calculate_rebalance_status(portfolio):
    positions = calculate_positions(portfolio, include_zero=True, include_targets=True)
    return {
        'portfolio_id': str(portfolio.id),
        'current_value_usd': _money(sum(
            (position['current_value_usd'] for position in positions if position['current_value_usd'] is not None),
            ZERO_AMOUNT,
        )),
        'positions': positions,
        'disclaimer': 'Расчет показывает отклонение от целевых долей и не является инвестиционной рекомендацией.',
    }


def _performance_totals_for_cutoff(portfolio, cutoff, *, label):
    totals = calculate_portfolio_totals(portfolio, as_of=cutoff)
    return {
        'label': label,
        'cost_basis_usd': totals['cost_basis_usd'],
        'current_value_usd': totals['current_value_usd'],
        'realized_pl_usd': totals['realized_pl_usd'],
        'unrealized_pl_usd': totals['unrealized_pl_usd'],
        'total_pl_usd': totals['total_pl_usd'],
        'bought_usd': totals['bought_usd'],
        'sold_usd': totals['sold_usd'],
        'valuation_complete': totals['valuation_complete'],
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

            if price_currency != 'USD':
                if price_currency not in fx_cache:
                    fx_quote = fx_provider.get_rate(price_currency, 'USD')
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
                fx_rate_to_usd=fx_rate,
                price_usd=_money(price_quote.price * fx_rate),
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
                'fx_rate_to_usd': str(fx_rate),
                'price_usd': f'{snapshot.price_usd:.2f}',
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
