from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import calendar
import logging

from django.db.models import Max, Min
from django.utils import timezone

from .fx_providers import FxRateProviderError, get_fx_rate_provider
from .models import FxRateSnapshot, Instrument, InstrumentPriceSnapshot, InvestmentOperation, InvestmentTargetAllocation, SUPPORTED_CURRENCIES
from .models import InvestmentPortfolio, InvestmentPortfolioSnapshot
from .price_providers import PriceProviderError, get_price_provider

logger = logging.getLogger(__name__)

ZERO_AMOUNT = Decimal('0')
PERFORMANCE_MONEY_FIELDS = (
    'cost_basis',
    'current_value',
    'realized_pl',
    'unrealized_pl',
    'total_pl',
    'bought',
    'sold',
)


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


def _snapshot_decimal(value):
    if value is None or value == '':
        return ZERO_AMOUNT
    return Decimal(str(value))


def _snapshot_money(value):
    return str(_money(value))


def _snapshot_datetime(value):
    return value.isoformat() if value is not None else None


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


def calculate_positions(
    portfolio,
    *,
    include_zero=False,
    as_of=None,
    price_as_of=None,
    include_targets=False,
    price_max_age_days=None,
):
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
        elif operation.operation_type == InvestmentOperation.TYPE_DIVIDEND:
            state.realized_pl_usd += amount_usd - fee_usd
        elif operation.operation_type == InvestmentOperation.TYPE_SPLIT:
            state.quantity *= quantity
            if state.quantity == ZERO_AMOUNT:
                state.cost_basis_usd = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_TRANSFER:
            # Перевод между инвестиционными счетами не меняет агрегированную позицию портфеля.
            continue

    price_cutoff = price_as_of or as_of
    latest_prices = _latest_price_snapshots(positions.keys(), as_of=price_cutoff)
    target_allocations = {
        str(allocation.instrument_id): allocation
        for allocation in InvestmentTargetAllocation.objects.filter(portfolio=portfolio).select_related('instrument')
    }

    result = []
    for instrument_id, state in positions.items():
        if not include_zero and state.quantity == ZERO_AMOUNT and state.realized_pl_usd == ZERO_AMOUNT:
            continue
        snapshot = latest_prices.get(instrument_id)
        if snapshot is not None and price_max_age_days is not None and price_cutoff is not None:
            snapshot_date = _date_part(snapshot.captured_at)
            cutoff_date = _date_part(price_cutoff)
            if snapshot_date is None or cutoff_date is None or snapshot_date < cutoff_date - timedelta(days=price_max_age_days):
                snapshot = None
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
    ).order_by('date', 'created_at', 'id')
    if exclude_operation is not None and exclude_operation.pk:
        queryset = queryset.exclude(pk=exclude_operation.pk)

    for operation in queryset:
        if operation.operation_type == InvestmentOperation.TYPE_BUY:
            quantity += operation.quantity
        elif operation.operation_type == InvestmentOperation.TYPE_SELL:
            quantity -= operation.quantity
        elif operation.operation_type == InvestmentOperation.TYPE_CORRECTION:
            quantity += operation.quantity
        elif operation.operation_type == InvestmentOperation.TYPE_SPLIT:
            quantity *= operation.quantity

    return quantity


def calculate_portfolio_totals(portfolio, *, as_of=None, price_max_age_days=None):
    positions = calculate_positions(
        portfolio,
        include_zero=True,
        as_of=as_of,
        price_as_of=as_of,
        price_max_age_days=price_max_age_days,
    )
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


def build_portfolio_snapshot_payload(portfolio, snapshot_date, *, price_max_age_days=0):
    cutoff = _aware_datetime(snapshot_date, end_of_day=True)
    totals = calculate_portfolio_totals(
        portfolio,
        as_of=cutoff,
        price_max_age_days=price_max_age_days,
    )
    positions_payload = [_serialize_snapshot_position(position) for position in totals['positions']]
    return {
        'portfolio': portfolio,
        'snapshot_date': snapshot_date,
        'cost_basis_usd': totals['cost_basis_usd'],
        'current_value_usd': totals['current_value_usd'],
        'realized_pl_usd': totals['realized_pl_usd'],
        'unrealized_pl_usd': totals['unrealized_pl_usd'],
        'total_pl_usd': totals['total_pl_usd'],
        'return_percent': totals['return_percent'],
        'valuation_complete': totals['valuation_complete'],
        'bought_usd': totals['bought_usd'],
        'sold_usd': totals['sold_usd'],
        'latest_price_at': totals['latest_price_at'],
        'positions_payload': positions_payload,
    }


def upsert_portfolio_snapshot(portfolio, snapshot_date, *, price_max_age_days=0):
    payload = build_portfolio_snapshot_payload(
        portfolio,
        snapshot_date,
        price_max_age_days=price_max_age_days,
    )
    snapshot, created = InvestmentPortfolioSnapshot.objects.update_or_create(
        portfolio=portfolio,
        snapshot_date=snapshot_date,
        defaults={
            'cost_basis_usd': payload['cost_basis_usd'],
            'current_value_usd': payload['current_value_usd'],
            'realized_pl_usd': payload['realized_pl_usd'],
            'unrealized_pl_usd': payload['unrealized_pl_usd'],
            'total_pl_usd': payload['total_pl_usd'],
            'return_percent': payload['return_percent'],
            'valuation_complete': payload['valuation_complete'],
            'bought_usd': payload['bought_usd'],
            'sold_usd': payload['sold_usd'],
            'latest_price_at': payload['latest_price_at'],
            'positions_payload': payload['positions_payload'],
        },
    )
    return snapshot, created


def rebuild_portfolio_snapshots(*, portfolio=None, date_from=None, date_to=None, price_max_age_days=0):
    today = timezone.localdate()
    if date_to is None or date_to > today:
        date_to = today

    portfolios = _resolve_snapshot_portfolios(portfolio)
    summary = {
        'portfolios': 0,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'snapshots': 0,
    }
    for portfolio_obj in portfolios:
        first_data_date, _latest_data_date = _portfolio_data_date_bounds(portfolio_obj)
        portfolio_date_from = date_from or first_data_date or today
        if portfolio_date_from > date_to:
            summary['skipped'] += 1
            continue

        summary['portfolios'] += 1
        cursor = portfolio_date_from
        while cursor <= date_to:
            _snapshot, created = upsert_portfolio_snapshot(
                portfolio_obj,
                cursor,
                price_max_age_days=price_max_age_days,
            )
            summary['snapshots'] += 1
            if created:
                summary['created'] += 1
            else:
                summary['updated'] += 1
            cursor = _next_day(cursor)
    return summary


def rebuild_portfolio_snapshots_for_change(
    *,
    portfolio=None,
    instrument=None,
    changed_at=None,
    date_from=None,
    date_to=None,
    price_max_age_days=0,
):
    today = timezone.localdate()
    start_date = _date_part(date_from or changed_at) or today
    if date_to is None or date_to > today:
        date_to = today

    summary = {
        'portfolios': 0,
        'created': 0,
        'updated': 0,
        'skipped': 0,
        'snapshots': 0,
    }
    if start_date > date_to:
        summary['skipped'] += 1
        return summary

    if portfolio is not None:
        portfolios = _resolve_snapshot_portfolios(portfolio)
    elif instrument is not None:
        instrument_id = instrument.pk if isinstance(instrument, Instrument) else instrument
        portfolios = (
            InvestmentPortfolio.objects
            .filter(
                operations__instrument_id=instrument_id,
                operations__deleted=False,
                operations__posted=True,
            )
            .distinct()
            .order_by('user_id', 'name')
        )
    else:
        return summary

    for portfolio_obj in portfolios:
        partial = rebuild_portfolio_snapshots(
            portfolio=portfolio_obj,
            date_from=start_date,
            date_to=date_to,
            price_max_age_days=price_max_age_days,
        )
        for key in summary:
            summary[key] += partial[key]
    return summary


def get_market_data_health(*, max_age_days=2, as_of=None):
    as_of_date = as_of or timezone.localdate()
    stale_before = as_of_date - timedelta(days=max_age_days)

    price_items = []
    latest_price_at = None
    for instrument in Instrument.objects.filter(is_active=True).order_by('type', 'ticker'):
        snapshot = (
            InstrumentPriceSnapshot.objects
            .filter(instrument=instrument)
            .order_by('-captured_at', '-created_at')
            .first()
        )
        snapshot_date = _date_part(snapshot.captured_at) if snapshot is not None else None
        if snapshot is None:
            item_status = 'missing'
        elif snapshot_date < stale_before:
            item_status = 'stale'
        else:
            item_status = 'ok'
        if snapshot is not None and (latest_price_at is None or snapshot.captured_at > latest_price_at):
            latest_price_at = snapshot.captured_at
        price_items.append({
            'instrument_id': str(instrument.id),
            'ticker': instrument.ticker,
            'name': instrument.name,
            'status': item_status,
            'latest_at': snapshot.captured_at if snapshot is not None else None,
            'age_days': (as_of_date - snapshot_date).days if snapshot_date is not None else None,
            'price_usd': _money(snapshot.price_usd) if snapshot is not None else None,
            'source': snapshot.source if snapshot is not None else None,
            'uses_fallback': item_status == 'stale',
        })

    fx_items = []
    latest_fx_at = None
    for base_currency, quote_currency in _fx_currency_pairs():
        snapshot = (
            FxRateSnapshot.objects
            .filter(base_currency=base_currency, quote_currency=quote_currency)
            .order_by('-captured_at', '-created_at')
            .first()
        )
        snapshot_date = _date_part(snapshot.captured_at) if snapshot is not None else None
        if snapshot is None:
            item_status = 'missing'
        elif snapshot_date < stale_before:
            item_status = 'stale'
        else:
            item_status = 'ok'
        if snapshot is not None and (latest_fx_at is None or snapshot.captured_at > latest_fx_at):
            latest_fx_at = snapshot.captured_at
        fx_items.append({
            'base_currency': base_currency,
            'quote_currency': quote_currency,
            'status': item_status,
            'latest_at': snapshot.captured_at if snapshot is not None else None,
            'age_days': (as_of_date - snapshot_date).days if snapshot_date is not None else None,
            'rate': snapshot.rate if snapshot is not None else None,
            'source': snapshot.source if snapshot is not None else None,
            'uses_fallback': item_status == 'stale',
        })

    price_counts = _health_counts(price_items)
    fx_counts = _health_counts(fx_items)
    return {
        'status': _overall_market_health_status(price_counts, fx_counts),
        'as_of': as_of_date.isoformat(),
        'max_age_days': max_age_days,
        'latest_successful_price_at': latest_price_at,
        'latest_successful_fx_at': latest_fx_at,
        'prices': {
            **price_counts,
            'items': price_items,
        },
        'fx_rates': {
            **fx_counts,
            'items': fx_items,
        },
    }


def _health_counts(items):
    return {
        'total': len(items),
        'ok': sum(1 for item in items if item['status'] == 'ok'),
        'stale': sum(1 for item in items if item['status'] == 'stale'),
        'missing': sum(1 for item in items if item['status'] == 'missing'),
    }


def _overall_market_health_status(price_counts, fx_counts):
    if price_counts['missing'] or fx_counts['missing']:
        return 'error'
    if price_counts['stale'] or fx_counts['stale']:
        return 'warning'
    return 'ok'


def _resolve_snapshot_portfolios(portfolio):
    if portfolio is None:
        return InvestmentPortfolio.objects.all().order_by('user_id', 'name')
    if isinstance(portfolio, InvestmentPortfolio):
        return InvestmentPortfolio.objects.filter(pk=portfolio.pk)
    return InvestmentPortfolio.objects.filter(pk=portfolio)


def _serialize_snapshot_position(position):
    return {
        'instrument_id': position['instrument_id'],
        'instrument_ticker': position['instrument_ticker'],
        'instrument_name': position['instrument_name'],
        'quantity': str(position['quantity']),
        'cost_basis_usd': _snapshot_money(position['cost_basis_usd']),
        'current_value_usd': _snapshot_money(position['current_value_usd']) if position['current_value_usd'] is not None else None,
        'realized_pl_usd': _snapshot_money(position['realized_pl_usd']),
        'unrealized_pl_usd': _snapshot_money(position['unrealized_pl_usd']) if position['unrealized_pl_usd'] is not None else None,
        'total_pl_usd': _snapshot_money(position['total_pl_usd']),
        'bought_usd': _snapshot_money(position['bought_usd']),
        'sold_usd': _snapshot_money(position['sold_usd']),
        'valuation_complete': not (position['current_value_usd'] is None and position['quantity'] != ZERO_AMOUNT),
        'latest_price_usd': _snapshot_money(position['latest_price_usd']) if position['latest_price_usd'] is not None else None,
        'latest_price_at': _snapshot_datetime(position['latest_price_at']),
    }


def calculate_portfolio_performance(
    portfolio,
    *,
    date_from,
    date_to,
    group_by='month',
    display_currency='USD',
    scope='portfolio',
    instrument_id=None,
):
    if date_from > date_to:
        raise ValueError('date_from must be before or equal to date_to.')
    if group_by not in {'day', 'month'}:
        raise ValueError('group_by must be day or month.')
    if scope not in {'portfolio', 'instrument', 'all'}:
        raise ValueError('scope must be portfolio, instrument or all.')
    display_currency = (display_currency or 'USD').strip().upper()

    start_dt = _aware_datetime(date_from)
    opening_cutoff = start_dt - timedelta(microseconds=1)
    opening = _performance_totals_for_cutoff(
        portfolio,
        opening_cutoff,
        label='Старт',
        display_currency=display_currency,
    )
    opening.update({
        'date': date_from.isoformat(),
        'period_start': None,
        'period_end': date_from.isoformat(),
    })

    first_data_date, latest_data_date = _portfolio_data_date_bounds(portfolio)
    effective_date_to = min(date_to, timezone.localdate())
    if latest_data_date is not None:
        effective_date_to = min(effective_date_to, latest_data_date)

    points = []
    instrument_series = defaultdict(lambda: {
        'instrument_id': '',
        'instrument_ticker': '',
        'instrument_name': '',
        'points': [],
        'missing_points': [],
    })
    if first_data_date is not None:
        cursor = max(date_from, first_data_date)
    else:
        cursor = date_from
    while cursor <= effective_date_to:
        if group_by == 'day':
            period_start = cursor
            period_end = min(cursor, effective_date_to)
            cursor = _next_day(cursor)
            label = period_end.isoformat()
        else:
            period_start = cursor
            period_end = min(_month_end(cursor), effective_date_to)
            cursor = _next_month(date(period_end.year, period_end.month, 1))
            label = period_end.strftime('%Y-%m')

        cutoff = _aware_datetime(period_end, end_of_day=True)
        snapshot = _fresh_portfolio_snapshot(portfolio, period_end, cutoff)
        if snapshot is not None:
            point = _performance_point_from_snapshot(
                portfolio,
                snapshot,
                label=label,
                period_start=period_start,
                period_end=period_end,
                display_currency=display_currency,
                fx_max_age_days=0,
            )
        else:
            point = _performance_totals_for_cutoff(
                portfolio,
                cutoff,
                label=label,
                price_max_age_days=0,
                display_currency=display_currency,
                fx_max_age_days=0,
            )
            point.update({
                'date': period_end.isoformat(),
                'period_start': period_start.isoformat(),
                'period_end': period_end.isoformat(),
            })

        if scope in {'instrument', 'all'}:
            if snapshot is not None:
                instrument_rows = _performance_instrument_points_from_snapshot(
                    portfolio,
                    snapshot,
                    label=label,
                    period_start=period_start,
                    period_end=period_end,
                    display_currency=display_currency,
                    instrument_id=instrument_id if scope == 'instrument' else None,
                    fx_max_age_days=0,
                )
            else:
                instrument_rows = _performance_instrument_points_for_cutoff(
                    portfolio,
                    cutoff,
                    label=label,
                    period_start=period_start,
                    period_end=period_end,
                    display_currency=display_currency,
                    instrument_id=instrument_id if scope == 'instrument' else None,
                    price_max_age_days=0,
                    fx_max_age_days=0,
                )
            for instrument_row in instrument_rows:
                series = instrument_series[instrument_row['instrument_id']]
                series['instrument_id'] = instrument_row['instrument_id']
                series['instrument_ticker'] = instrument_row['instrument_ticker']
                series['instrument_name'] = instrument_row['instrument_name']
                if instrument_row['point']['valuation_complete']:
                    series['points'].append(instrument_row['point'])
                else:
                    series['missing_points'].append(instrument_row['point'])

        if not point['valuation_complete'] or not _performance_point_has_state(point):
            continue
        points.append(point)

    return {
        'portfolio_id': str(portfolio.id),
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'group_by': group_by,
        'display_currency': display_currency,
        'scope': scope,
        'opening': opening,
        'points': points,
        'instrument_series': sorted(
            instrument_series.values(),
            key=lambda series: series['instrument_ticker'],
        ),
    }


def _fresh_portfolio_snapshot(portfolio, snapshot_date, cutoff):
    snapshot = InvestmentPortfolioSnapshot.objects.filter(
        portfolio=portfolio,
        snapshot_date=snapshot_date,
    ).first()
    if snapshot is None:
        return None
    if not _portfolio_snapshot_is_current(portfolio, snapshot, cutoff):
        return None
    return snapshot


def _portfolio_snapshot_is_current(portfolio, snapshot, cutoff):
    latest_operation_update = (
        InvestmentOperation.objects
        .filter(portfolio=portfolio, date__lte=cutoff)
        .aggregate(latest=Max('updated_at'))
    )['latest']
    if latest_operation_update is not None and latest_operation_update > snapshot.updated_at:
        return False

    instrument_ids = (
        InvestmentOperation.objects
        .filter(portfolio=portfolio, date__lte=cutoff)
        .values_list('instrument_id', flat=True)
        .distinct()
    )
    latest_price_create = (
        InstrumentPriceSnapshot.objects
        .filter(instrument_id__in=instrument_ids, captured_at__lte=cutoff)
        .aggregate(created=Max('created_at'), updated=Max('updated_at'))
    )
    latest_price_change = max(
        (value for value in latest_price_create.values() if value is not None),
        default=None,
    )
    return not (latest_price_change is not None and latest_price_change > snapshot.updated_at)


def _performance_point_from_snapshot(
    portfolio,
    snapshot,
    *,
    label,
    period_start,
    period_end,
    display_currency,
    fx_max_age_days=None,
):
    point = {
        'label': label,
        'date': period_end.isoformat(),
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'cost_basis_usd': snapshot.cost_basis_usd,
        'current_value_usd': snapshot.current_value_usd,
        'realized_pl_usd': snapshot.realized_pl_usd,
        'unrealized_pl_usd': snapshot.unrealized_pl_usd,
        'total_pl_usd': snapshot.total_pl_usd,
        'bought_usd': snapshot.bought_usd,
        'sold_usd': snapshot.sold_usd,
        'valuation_complete': snapshot.valuation_complete,
        'missing_reason': None if snapshot.valuation_complete else 'snapshot_incomplete',
    }
    _apply_display_currency(
        point,
        _aware_datetime(period_end, end_of_day=True),
        display_currency,
        portfolio=portfolio,
        fx_max_age_days=fx_max_age_days,
    )
    return point


def _performance_instrument_points_from_snapshot(
    portfolio,
    snapshot,
    *,
    label,
    period_start,
    period_end,
    display_currency,
    instrument_id=None,
    fx_max_age_days=None,
):
    rows = []
    for position in snapshot.positions_payload or []:
        if instrument_id is not None and str(position.get('instrument_id')) != str(instrument_id):
            continue
        quantity = _snapshot_decimal(position.get('quantity'))
        if quantity == ZERO_AMOUNT and not _snapshot_position_has_state(position):
            continue
        valuation_complete = bool(position.get('valuation_complete'))
        point = {
            'label': label,
            'date': period_end.isoformat(),
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'cost_basis_usd': _snapshot_decimal(position.get('cost_basis_usd')),
            'current_value_usd': _snapshot_decimal(position.get('current_value_usd')),
            'realized_pl_usd': _snapshot_decimal(position.get('realized_pl_usd')),
            'unrealized_pl_usd': _snapshot_decimal(position.get('unrealized_pl_usd')),
            'total_pl_usd': _snapshot_decimal(position.get('total_pl_usd')),
            'bought_usd': _snapshot_decimal(position.get('bought_usd')),
            'sold_usd': _snapshot_decimal(position.get('sold_usd')),
            'valuation_complete': valuation_complete,
            'missing_reason': None if valuation_complete else 'price_missing',
        }
        _apply_display_currency(
            point,
            _aware_datetime(period_end, end_of_day=True),
            display_currency,
            portfolio=portfolio,
            instrument_id=position.get('instrument_id'),
            fx_max_age_days=fx_max_age_days,
        )
        rows.append({
            'instrument_id': str(position.get('instrument_id')),
            'instrument_ticker': position.get('instrument_ticker') or '',
            'instrument_name': position.get('instrument_name') or '',
            'point': point,
        })
    return rows


def _snapshot_position_has_state(position):
    return any(
        _snapshot_decimal(position.get(field)) != ZERO_AMOUNT
        for field in (
            'cost_basis_usd',
            'current_value_usd',
            'realized_pl_usd',
            'unrealized_pl_usd',
            'total_pl_usd',
            'bought_usd',
            'sold_usd',
        )
    )


def _performance_instrument_points_for_cutoff(
    portfolio,
    cutoff,
    *,
    label,
    period_start,
    period_end,
    display_currency,
    instrument_id=None,
    price_max_age_days=None,
    fx_max_age_days=None,
):
    rows = []
    positions = calculate_positions(
        portfolio,
        include_zero=False,
        as_of=cutoff,
        price_as_of=cutoff,
        price_max_age_days=price_max_age_days,
    )
    for position in positions:
        if instrument_id is not None and str(position['instrument_id']) != str(instrument_id):
            continue
        valuation_complete = not (position['current_value_usd'] is None and position['quantity'] != ZERO_AMOUNT)
        if not valuation_complete:
            current_value_usd = ZERO_AMOUNT
            unrealized_pl_usd = ZERO_AMOUNT
            total_pl_usd = position['realized_pl_usd']
        else:
            current_value_usd = position['current_value_usd'] or ZERO_AMOUNT
            unrealized_pl_usd = position['unrealized_pl_usd'] or ZERO_AMOUNT
            total_pl_usd = position['total_pl_usd']
        point = {
            'label': label,
            'date': period_end.isoformat(),
            'period_start': period_start.isoformat(),
            'period_end': period_end.isoformat(),
            'cost_basis_usd': position['cost_basis_usd'],
            'current_value_usd': current_value_usd,
            'realized_pl_usd': position['realized_pl_usd'],
            'unrealized_pl_usd': unrealized_pl_usd,
            'total_pl_usd': total_pl_usd,
            'bought_usd': position['bought_usd'],
            'sold_usd': position['sold_usd'],
            'valuation_complete': valuation_complete,
            'missing_reason': None if valuation_complete else 'price_missing',
        }
        _apply_display_currency(
            point,
            cutoff,
            display_currency,
            portfolio=portfolio,
            instrument_id=position['instrument_id'],
            fx_max_age_days=fx_max_age_days,
        )
        rows.append({
            'instrument_id': position['instrument_id'],
            'instrument_ticker': position['instrument_ticker'],
            'instrument_name': position['instrument_name'],
            'point': point,
        })
    return rows


def _portfolio_data_date_bounds(portfolio):
    operations = InvestmentOperation.objects.filter(portfolio=portfolio, deleted=False, posted=True)
    operation_bounds = operations.aggregate(first=Min('date'), latest=Max('date'))
    instrument_ids = operations.values_list('instrument_id', flat=True).distinct()
    price_bounds = InstrumentPriceSnapshot.objects.filter(instrument_id__in=instrument_ids).aggregate(
        first=Min('captured_at'),
        latest=Max('captured_at'),
    )
    snapshot_bounds = InvestmentPortfolioSnapshot.objects.filter(portfolio=portfolio).aggregate(
        first=Min('snapshot_date'),
        latest=Max('snapshot_date'),
    )
    first_candidates = [
        _date_part(operation_bounds['first']),
        _date_part(price_bounds['first']),
        snapshot_bounds['first'],
    ]
    latest_candidates = [
        _date_part(operation_bounds['latest']),
        _date_part(price_bounds['latest']),
        snapshot_bounds['latest'],
    ]
    first_dates = [candidate for candidate in first_candidates if candidate is not None]
    latest_dates = [candidate for candidate in latest_candidates if candidate is not None]
    return (
        min(first_dates) if first_dates else None,
        max(latest_dates) if latest_dates else None,
    )


def _date_part(value):
    if value is None:
        return None
    return value.date() if hasattr(value, 'date') else value


def _performance_point_has_state(point):
    return any(
        point.get(field) != ZERO_AMOUNT
        for field in (
            'cost_basis_usd',
            'current_value_usd',
            'realized_pl_usd',
            'unrealized_pl_usd',
            'total_pl_usd',
            'bought_usd',
            'sold_usd',
        )
    )


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


def apply_portfolio_display_currency(portfolio, totals, display_currency='USD', *, cutoff=None, fx_max_age_days=None):
    currency = (display_currency or 'USD').strip().upper()
    cutoff = cutoff or timezone.now()
    display_point = {
        'cost_basis_usd': totals['cost_basis_usd'],
        'current_value_usd': totals['current_value_usd'],
        'realized_pl_usd': totals['realized_pl_usd'],
        'unrealized_pl_usd': totals['unrealized_pl_usd'],
        'total_pl_usd': totals['total_pl_usd'],
        'bought_usd': totals['bought_usd'],
        'sold_usd': totals['sold_usd'],
        'valuation_complete': totals['valuation_complete'],
    }
    _apply_display_currency(
        display_point,
        cutoff,
        currency,
        portfolio=portfolio,
        fx_max_age_days=fx_max_age_days,
    )
    display_totals = {
        key: value
        for key, value in display_point.items()
        if key.endswith('_display') or key in (
            'display_currency',
            'fx_rate_to_display',
            'fx_rate_at',
            'display_valuation_complete',
        )
    }
    display_positions = [
        _display_position(
            portfolio,
            position,
            cutoff,
            currency,
            fx_max_age_days=fx_max_age_days,
        )
        for position in totals['positions']
    ]
    return {
        **totals,
        **display_totals,
        'positions': display_positions,
    }


def _display_position(portfolio, position, cutoff, display_currency, *, fx_max_age_days=None):
    currency = (display_currency or 'USD').strip().upper()
    result = dict(position)
    result['display_currency'] = currency

    fx_snapshot, fx_rate = _latest_fx_rate_snapshot('USD', currency, as_of=cutoff, max_age_days=fx_max_age_days)
    result['fx_rate_to_display'] = fx_rate
    result['fx_rate_at'] = fx_snapshot.captured_at if fx_snapshot is not None else None
    result['display_valuation_complete'] = fx_rate is not None

    display_fields = (
        'cost_basis_display',
        'average_buy_price_display',
        'latest_price_display',
        'current_value_display',
        'realized_pl_display',
        'unrealized_pl_display',
        'total_pl_display',
        'bought_display',
        'sold_display',
    )
    if fx_rate is None:
        for field in display_fields:
            result[field] = None
        return result

    if currency == 'USD':
        result['cost_basis_display'] = position['cost_basis_usd']
        result['average_buy_price_display'] = position['average_buy_price_usd']
        result['latest_price_display'] = position['latest_price_usd']
        result['current_value_display'] = position['current_value_usd']
        result['realized_pl_display'] = position['realized_pl_usd']
        result['unrealized_pl_display'] = position['unrealized_pl_usd']
        result['total_pl_display'] = position['total_pl_usd']
        result['bought_display'] = position['bought_usd']
        result['sold_display'] = position['sold_usd']
        return result

    historical_totals = _historical_display_totals_for_cutoff(
        portfolio,
        cutoff,
        currency,
        instrument_id=position['instrument_id'],
        fx_max_age_days=fx_max_age_days,
    )
    result['latest_price_display'] = (
        _money(position['latest_price_usd'] * fx_rate)
        if position['latest_price_usd'] is not None
        else None
    )
    result['current_value_display'] = (
        _money(position['current_value_usd'] * fx_rate)
        if position['current_value_usd'] is not None
        else None
    )
    if not historical_totals['complete']:
        result['display_valuation_complete'] = False
        for field in ('cost_basis_display', 'average_buy_price_display', 'realized_pl_display', 'unrealized_pl_display', 'total_pl_display', 'bought_display', 'sold_display'):
            result[field] = None
        return result

    result['cost_basis_display'] = historical_totals['cost_basis']
    result['average_buy_price_display'] = (
        _money(result['cost_basis_display'] / position['quantity'])
        if position['quantity'] != ZERO_AMOUNT
        else ZERO_AMOUNT
    )
    result['realized_pl_display'] = historical_totals['realized_pl']
    result['bought_display'] = historical_totals['bought']
    result['sold_display'] = historical_totals['sold']
    result['unrealized_pl_display'] = (
        _money(result['current_value_display'] - result['cost_basis_display'])
        if result['current_value_display'] is not None
        else None
    )
    result['total_pl_display'] = (
        _money(result['realized_pl_display'] + result['unrealized_pl_display'])
        if result['unrealized_pl_display'] is not None
        else result['realized_pl_display']
    )
    result['display_valuation_complete'] = bool(
        result['display_valuation_complete']
        and not (position['current_value_usd'] is None and position['quantity'] != ZERO_AMOUNT)
    )
    return result


def _performance_totals_for_cutoff(
    portfolio,
    cutoff,
    *,
    label,
    price_max_age_days=None,
    display_currency='USD',
    fx_max_age_days=None,
):
    totals = calculate_portfolio_totals(portfolio, as_of=cutoff, price_max_age_days=price_max_age_days)
    point = {
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
    _apply_display_currency(
        point,
        cutoff,
        display_currency,
        portfolio=portfolio,
        fx_max_age_days=fx_max_age_days,
    )
    return point


def _latest_fx_rate_snapshot(base_currency, quote_currency, *, as_of=None, max_age_days=None):
    base = str(base_currency or '').strip().upper()
    quote = str(quote_currency or '').strip().upper()
    if base == quote:
        return None, Decimal('1')
    queryset = (
        FxRateSnapshot.objects
        .filter(base_currency=base, quote_currency=quote)
        .order_by('-captured_at', '-created_at')
    )
    if as_of is not None:
        queryset = queryset.filter(captured_at__lte=as_of)
    snapshot = queryset.first()
    if snapshot is None:
        return None, None
    if max_age_days is not None and as_of is not None:
        snapshot_date = _date_part(snapshot.captured_at)
        cutoff_date = _date_part(as_of)
        if snapshot_date is None or cutoff_date is None or snapshot_date < cutoff_date - timedelta(days=max_age_days):
            return None, None
    return snapshot, snapshot.rate


def display_money_for_date(amount, value_date, display_currency, *, fx_max_age_days=None):
    currency = (display_currency or 'USD').strip().upper()
    amount = amount or ZERO_AMOUNT
    if currency == 'USD':
        return {
            'display_currency': currency,
            'fx_rate_to_display': Decimal('1'),
            'fx_rate_at': None,
            'amount_display': _money(amount),
        }

    cutoff_date = _date_part(value_date)
    if cutoff_date is None:
        return {
            'display_currency': currency,
            'fx_rate_to_display': None,
            'fx_rate_at': None,
            'amount_display': None,
        }
    cutoff = _aware_datetime(cutoff_date, end_of_day=True)
    fx_snapshot, fx_rate = _latest_fx_rate_snapshot(
        'USD',
        currency,
        as_of=cutoff,
        max_age_days=fx_max_age_days,
    )
    return {
        'display_currency': currency,
        'fx_rate_to_display': fx_rate,
        'fx_rate_at': fx_snapshot.captured_at if fx_snapshot is not None else None,
        'amount_display': _money(amount * fx_rate) if fx_rate is not None else None,
    }


def _historical_display_totals_for_cutoff(portfolio, cutoff, display_currency, *, instrument_id=None, fx_max_age_days=None):
    currency = (display_currency or 'USD').strip().upper()
    states = {}
    fx_cache = {}
    complete = True

    operations = (
        InvestmentOperation.objects
        .filter(portfolio=portfolio, deleted=False, posted=True, date__lte=cutoff)
        .select_related('instrument')
        .order_by('date', 'created_at', 'id')
    )
    if instrument_id is not None:
        operations = operations.filter(instrument_id=instrument_id)

    def display_rate(operation):
        nonlocal complete
        if currency == 'USD':
            return Decimal('1')
        operation_date = _date_part(operation.date)
        if operation_date is None:
            complete = False
            return None
        if operation_date not in fx_cache:
            _snapshot, rate = _latest_fx_rate_snapshot(
                'USD',
                currency,
                as_of=_aware_datetime(operation_date, end_of_day=True),
                max_age_days=fx_max_age_days,
            )
            fx_cache[operation_date] = rate
        rate = fx_cache[operation_date]
        if rate is None:
            complete = False
        return rate

    for operation in operations:
        state = states.setdefault(operation.instrument_id, {
            'quantity': ZERO_AMOUNT,
            'cost_basis': ZERO_AMOUNT,
            'realized_pl': ZERO_AMOUNT,
            'bought': ZERO_AMOUNT,
            'sold': ZERO_AMOUNT,
        })
        quantity = operation.quantity or ZERO_AMOUNT
        amount_usd = operation.amount_usd or ZERO_AMOUNT
        fee_usd = operation.fee_usd or ZERO_AMOUNT
        rate = display_rate(operation)
        if rate is None:
            continue

        if operation.operation_type == InvestmentOperation.TYPE_BUY:
            cost = (amount_usd + fee_usd) * rate
            state['quantity'] += quantity
            state['cost_basis'] += cost
            state['bought'] += cost
        elif operation.operation_type == InvestmentOperation.TYPE_SELL:
            if quantity > state['quantity']:
                raise ValueError(f'Продажа {operation.instrument.ticker} превышает текущий остаток.')
            average_price = state['cost_basis'] / state['quantity'] if state['quantity'] != ZERO_AMOUNT else ZERO_AMOUNT
            sold_cost_basis = average_price * quantity
            proceeds = (amount_usd - fee_usd) * rate
            state['quantity'] -= quantity
            state['cost_basis'] -= sold_cost_basis
            state['realized_pl'] += proceeds - sold_cost_basis
            state['sold'] += proceeds
            if state['quantity'] == ZERO_AMOUNT:
                state['cost_basis'] = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_CORRECTION:
            state['quantity'] += quantity
            state['cost_basis'] += amount_usd * rate
            if state['quantity'] == ZERO_AMOUNT:
                state['cost_basis'] = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_DIVIDEND:
            state['realized_pl'] += (amount_usd - fee_usd) * rate
        elif operation.operation_type == InvestmentOperation.TYPE_SPLIT:
            state['quantity'] *= quantity
            if state['quantity'] == ZERO_AMOUNT:
                state['cost_basis'] = ZERO_AMOUNT
        elif operation.operation_type == InvestmentOperation.TYPE_TRANSFER:
            continue

    totals = defaultdict(lambda: ZERO_AMOUNT)
    for state in states.values():
        totals['cost_basis'] += state['cost_basis']
        totals['realized_pl'] += state['realized_pl']
        totals['bought'] += state['bought']
        totals['sold'] += state['sold']

    return {
        'complete': complete,
        'cost_basis': _money(totals['cost_basis']),
        'realized_pl': _money(totals['realized_pl']),
        'bought': _money(totals['bought']),
        'sold': _money(totals['sold']),
    }


def _apply_display_currency(point, cutoff, display_currency, *, fx_max_age_days=None, portfolio=None, instrument_id=None):
    currency = (display_currency or 'USD').strip().upper()
    fx_snapshot, fx_rate = _latest_fx_rate_snapshot('USD', currency, as_of=cutoff, max_age_days=fx_max_age_days)
    point['display_currency'] = currency
    point['fx_rate_to_display'] = fx_rate
    point['fx_rate_at'] = fx_snapshot.captured_at if fx_snapshot is not None else None
    point['display_valuation_complete'] = fx_rate is not None
    if fx_rate is None:
        point['valuation_complete'] = False
        for field in PERFORMANCE_MONEY_FIELDS:
            point[f'{field}_display'] = None
        return

    if portfolio is not None and currency != 'USD':
        historical_totals = _historical_display_totals_for_cutoff(
            portfolio,
            cutoff,
            currency,
            instrument_id=instrument_id,
            fx_max_age_days=fx_max_age_days,
        )
        point['current_value_display'] = _money(point['current_value_usd'] * fx_rate)
        if not historical_totals['complete']:
            point['display_valuation_complete'] = False
            for field in ('cost_basis', 'realized_pl', 'unrealized_pl', 'total_pl', 'bought', 'sold'):
                point[f'{field}_display'] = None
            return

        point['cost_basis_display'] = historical_totals['cost_basis']
        point['realized_pl_display'] = historical_totals['realized_pl']
        point['bought_display'] = historical_totals['bought']
        point['sold_display'] = historical_totals['sold']
        if not point['valuation_complete']:
            point['display_valuation_complete'] = False
            point['unrealized_pl_display'] = None
            point['total_pl_display'] = None
            return
        point['unrealized_pl_display'] = _money(point['current_value_display'] - point['cost_basis_display'])
        point['total_pl_display'] = _money(point['realized_pl_display'] + point['unrealized_pl_display'])
        point['display_valuation_complete'] = True
        return

    for field in PERFORMANCE_MONEY_FIELDS:
        point[f'{field}_display'] = _money(point[f'{field}_usd'] * fx_rate)


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

            snapshot, status = _upsert_price_snapshot(
                instrument=instrument,
                price_quote=price_quote,
                captured_at=captured_at,
                price_currency=price_currency,
                fx_rate_to_usd=fx_rate,
            )
            results.append({
                'instrument_id': str(instrument.id),
                'ticker': instrument.ticker,
                'status': status,
                'price_snapshot_id': str(snapshot.id),
                'fx_rate_snapshot_id': fx_snapshot_id,
                'price': str(price_quote.price),
                'price_currency': price_currency,
                'fx_rate_to_usd': str(fx_rate),
                'price_usd': f'{snapshot.price_usd:.2f}',
                'source': price_quote.source,
            })
        except (PriceProviderError, FxRateProviderError) as exc:
            logger.warning(
                'Investment price refresh failed for instrument %s.',
                instrument.ticker,
                exc_info=True,
            )
            results.append({
                'instrument_id': str(instrument.id),
                'ticker': instrument.ticker,
                'status': 'error',
                'error': str(exc),
            })

    return {
        'created': sum(1 for row in results if row['status'] == 'created'),
        'updated': sum(1 for row in results if row['status'] == 'updated'),
        'failed': sum(1 for row in results if row['status'] == 'error'),
        'results': results,
    }


def backfill_price_snapshots(*, date_from, date_to, price_provider=None, fx_provider=None, instruments=None):
    if date_from > date_to:
        raise ValueError('date_from must be before or equal to date_to.')

    price_provider = price_provider or get_price_provider()
    fx_provider = fx_provider or get_fx_rate_provider()
    instrument_queryset = (
        list(instruments)
        if instruments is not None
        else list(Instrument.objects.filter(is_active=True).order_by('type', 'ticker'))
    )
    effective_date_to = min(date_to, timezone.localdate())
    results = []
    fx_cache = {}

    def store_snapshot(*, instrument, price_quote, quote_date):
        captured_at = _aware_datetime(quote_date, end_of_day=True)
        price_currency = price_quote.price_currency.strip().upper()
        fx_rate = Decimal('1')
        fx_snapshot_id = None
        if price_currency != 'USD':
            fx_cache_key = (price_currency, quote_date)
            if fx_cache_key not in fx_cache:
                fx_quote = fx_provider.get_rate(price_currency, 'USD', on_date=quote_date)
                fx_snapshot, fx_status = _upsert_fx_rate_snapshot(fx_quote, captured_at)
                fx_cache[fx_cache_key] = (fx_quote.rate, str(fx_snapshot.id), fx_status)
            fx_rate, fx_snapshot_id, _ = fx_cache[fx_cache_key]

        snapshot, status = _upsert_price_snapshot(
            instrument=instrument,
            price_quote=price_quote,
            captured_at=captured_at,
            price_currency=price_currency,
            fx_rate_to_usd=fx_rate,
        )
        results.append({
            'instrument_id': str(instrument.id),
            'ticker': instrument.ticker,
            'date': quote_date.isoformat(),
            'status': status,
            'price_snapshot_id': str(snapshot.id),
            'fx_rate_snapshot_id': fx_snapshot_id,
            'price': str(price_quote.price),
            'price_currency': price_currency,
            'fx_rate_to_usd': str(fx_rate),
            'price_usd': f'{snapshot.price_usd:.2f}',
            'source': price_quote.source,
        })

    if date_from > effective_date_to:
        return {
            'created': 0,
            'updated': 0,
            'failed': 0,
            'results': results,
        }

    if getattr(price_provider, 'supports_historical_range', False):
        for instrument in instrument_queryset:
            try:
                quotes_by_date = price_provider.get_historical_prices(instrument, date_from, effective_date_to)
                for quote_date in sorted(quotes_by_date):
                    store_snapshot(
                        instrument=instrument,
                        price_quote=quotes_by_date[quote_date],
                        quote_date=quote_date,
                    )
            except (PriceProviderError, FxRateProviderError) as exc:
                logger.warning(
                    'Investment historical price range backfill failed for instrument %s.',
                    instrument.ticker,
                    exc_info=True,
                )
                results.append({
                    'instrument_id': str(instrument.id),
                    'ticker': instrument.ticker,
                    'date_from': date_from.isoformat(),
                    'date_to': effective_date_to.isoformat(),
                    'status': 'error',
                    'error': str(exc),
                })
        return {
            'created': sum(1 for row in results if row['status'] == 'created'),
            'updated': sum(1 for row in results if row['status'] == 'updated'),
            'failed': sum(1 for row in results if row['status'] == 'error'),
            'results': results,
        }

    cursor = date_from
    while cursor <= effective_date_to:
        for instrument in instrument_queryset:
            try:
                price_quote = price_provider.get_historical_price(instrument, cursor)
                store_snapshot(
                    instrument=instrument,
                    price_quote=price_quote,
                    quote_date=cursor,
                )
            except (PriceProviderError, FxRateProviderError) as exc:
                logger.warning(
                    'Investment historical price backfill failed for instrument %s on %s.',
                    instrument.ticker,
                    cursor.isoformat(),
                    exc_info=True,
                )
                results.append({
                    'instrument_id': str(instrument.id),
                    'ticker': instrument.ticker,
                    'date': cursor.isoformat(),
                    'status': 'error',
                    'error': str(exc),
                })
        cursor = _next_day(cursor)

    return {
        'created': sum(1 for row in results if row['status'] == 'created'),
        'updated': sum(1 for row in results if row['status'] == 'updated'),
        'failed': sum(1 for row in results if row['status'] == 'error'),
        'results': results,
    }


def _upsert_price_snapshot(*, instrument, price_quote, captured_at, price_currency, fx_rate_to_usd):
    captured_date = _date_part(captured_at)
    existing = (
        InstrumentPriceSnapshot.objects
        .filter(
            instrument=instrument,
            captured_at__date=captured_date,
            source=price_quote.source,
        )
        .order_by('-created_at')
        .first()
    )
    price_usd = _money(price_quote.price * fx_rate_to_usd)
    if existing is not None:
        existing.captured_at = captured_at
        existing.price = price_quote.price
        existing.price_currency = price_currency
        existing.fx_rate_to_usd = fx_rate_to_usd
        existing.price_usd = price_usd
        existing.save(update_fields=['captured_at', 'price', 'price_currency', 'fx_rate_to_usd', 'price_usd'])
        return existing, 'updated'
    return InstrumentPriceSnapshot.objects.create(
        instrument=instrument,
        captured_at=captured_at,
        price=price_quote.price,
        price_currency=price_currency,
        fx_rate_to_usd=fx_rate_to_usd,
        price_usd=price_usd,
        source=price_quote.source,
    ), 'created'


def refresh_fx_rate_snapshots(*, fx_provider=None, pairs=None, captured_at=None):
    fx_provider = fx_provider or get_fx_rate_provider()
    captured_at = captured_at or timezone.now()
    return _refresh_fx_rate_snapshots_for_date(
        fx_provider=fx_provider,
        pairs=pairs,
        captured_at=captured_at,
        rate_date=_date_part(captured_at),
    )


def backfill_fx_rate_snapshots(*, date_from, date_to, fx_provider=None, pairs=None):
    if date_from > date_to:
        raise ValueError('date_from must be before or equal to date_to.')

    fx_provider = fx_provider or get_fx_rate_provider()
    currency_pairs = _fx_currency_pairs(pairs)
    effective_date_to = min(date_to, timezone.localdate())
    cursor = date_from
    results = []

    while cursor <= effective_date_to:
        captured_at = _aware_datetime(cursor, end_of_day=True)
        day_result = _refresh_fx_rate_snapshots_for_date(
            fx_provider=fx_provider,
            pairs=currency_pairs,
            captured_at=captured_at,
            rate_date=cursor,
        )
        results.extend(day_result['results'])
        cursor = _next_day(cursor)

    return {
        'created': sum(1 for row in results if row['status'] == 'created'),
        'updated': sum(1 for row in results if row['status'] == 'updated'),
        'failed': sum(1 for row in results if row['status'] == 'error'),
        'results': results,
    }


def _refresh_fx_rate_snapshots_for_date(*, fx_provider, pairs=None, captured_at, rate_date):
    currency_pairs = _fx_currency_pairs(pairs)
    results = []

    for base_currency, quote_currency in currency_pairs:
        base = str(base_currency or '').strip().upper()
        quote = str(quote_currency or '').strip().upper()
        try:
            fx_quote = fx_provider.get_rate(base, quote, on_date=rate_date)
            snapshot, status = _upsert_fx_rate_snapshot(fx_quote, captured_at)
            results.append({
                'fx_rate_snapshot_id': str(snapshot.id),
                'base_currency': fx_quote.base_currency,
                'quote_currency': fx_quote.quote_currency,
                'date': _date_part(captured_at).isoformat(),
                'status': status,
                'rate': str(fx_quote.rate),
                'source': fx_quote.source,
            })
        except FxRateProviderError as exc:
            logger.warning(
                'Investment FX refresh failed for %s/%s.',
                base,
                quote,
                exc_info=True,
            )
            results.append({
                'base_currency': base,
                'quote_currency': quote,
                'status': 'error',
                'error': str(exc),
            })

    return {
        'created': sum(1 for row in results if row['status'] == 'created'),
        'updated': sum(1 for row in results if row['status'] == 'updated'),
        'failed': sum(1 for row in results if row['status'] == 'error'),
        'results': results,
    }


def _fx_currency_pairs(pairs=None):
    return pairs or [
        (base_currency, quote_currency)
        for base_currency in SUPPORTED_CURRENCIES
        for quote_currency in SUPPORTED_CURRENCIES
        if base_currency != quote_currency
    ]


def _upsert_fx_rate_snapshot(fx_quote, captured_at):
    captured_date = _date_part(captured_at)
    existing = (
        FxRateSnapshot.objects
        .filter(
            base_currency=fx_quote.base_currency,
            quote_currency=fx_quote.quote_currency,
            captured_at__date=captured_date,
            source=fx_quote.source,
        )
        .order_by('-created_at')
        .first()
    )
    if existing is not None:
        existing.captured_at = captured_at
        existing.rate = fx_quote.rate
        existing.save(update_fields=['captured_at', 'rate'])
        return existing, 'updated'
    return FxRateSnapshot.objects.create(
        captured_at=captured_at,
        base_currency=fx_quote.base_currency,
        quote_currency=fx_quote.quote_currency,
        rate=fx_quote.rate,
        source=fx_quote.source,
    ), 'created'
