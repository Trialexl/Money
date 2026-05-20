import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from investments.models import InvestmentPortfolio
from investments.services import calculate_portfolio_totals
from money.models import TelegramUserBinding


ZERO_AMOUNT = Decimal('0')


def _format_money(value):
    value = value or ZERO_AMOUNT
    sign = '-' if value < ZERO_AMOUNT else ''
    amount = abs(value).quantize(Decimal('0.01'))
    whole, fraction = f'{amount:.2f}'.split('.')
    grouped = f'{int(whole):,}'.replace(',', ' ')
    return f'{sign}{grouped}.{fraction} $'


def _format_signed_money(value):
    value = value or ZERO_AMOUNT
    prefix = '+' if value > ZERO_AMOUNT else ''
    return f'{prefix}{_format_money(value)}'


def _format_percent(value):
    if value is None:
        return 'н/д'
    return f'{value.quantize(Decimal("0.01"))}%'


def _default_portfolio_for_user(user):
    portfolio = InvestmentPortfolio.objects.filter(user=user, is_default=True).first()
    if portfolio is not None:
        return portfolio
    return InvestmentPortfolio.objects.filter(user=user).order_by('name').first()


def build_portfolio_report_text(portfolio):
    totals = calculate_portfolio_totals(
        portfolio,
        price_max_age_days=getattr(settings, 'SCHEDULED_JOBS_MARKET_MAX_AGE_DAYS', 2),
    )
    positions = sorted(
        totals.get('positions') or [],
        key=lambda item: item.get('current_value_usd') or ZERO_AMOUNT,
        reverse=True,
    )
    positions = [
        position for position in positions
        if (position.get('quantity') or ZERO_AMOUNT) != ZERO_AMOUNT
    ]

    lines = [
        f'💼 {portfolio.name}',
        f'Стоимость: {_format_money(totals.get("current_value_usd"))}',
        f'P/L: {_format_signed_money(totals.get("total_pl_usd"))} ({_format_percent(totals.get("return_percent"))})',
        f'Себестоимость: {_format_money(totals.get("cost_basis_usd"))}',
    ]

    latest_price_at = totals.get('latest_price_at')
    if latest_price_at is not None:
        lines.append(f'Цены: {timezone.localtime(latest_price_at).strftime("%d.%m.%Y %H:%M")}')
    if not totals.get('valuation_complete', True):
        lines.append('⚠️ Есть активы без актуальной цены.')

    if positions:
        lines.append('')
        lines.append('Топ позиций:')
        for index, position in enumerate(positions[:5], start=1):
            ticker = position.get('instrument_ticker') or ''
            value = _format_money(position.get('current_value_usd'))
            pl = _format_signed_money(position.get('total_pl_usd'))
            percent = _format_percent(position.get('return_percent'))
            lines.append(f'{index}. {ticker}: {value} | P/L {pl} ({percent})')

    return '\n'.join(lines)


def _telegram_api_url(method):
    token = getattr(settings, 'AI_TELEGRAM_BOT_TOKEN', '')
    base_url = getattr(settings, 'AI_TELEGRAM_API_BASE_URL', 'https://api.telegram.org').rstrip('/')
    return f'{base_url}/bot{token}/{method}'


def _send_telegram_message(chat_id, text, *, urlopen=None):
    urlopen = urlopen or urllib.request.urlopen
    request = urllib.request.Request(
        _telegram_api_url('sendMessage'),
        data=json.dumps({'chat_id': chat_id, 'text': text}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'Telegram sendMessage failed: {error_body or exc.reason}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Telegram sendMessage failed: {exc.reason}') from exc

    if not raw.get('ok', False):
        raise RuntimeError('Telegram sendMessage response is not ok.')
    return raw


def send_portfolio_report_to_telegram(*, urlopen=None):
    if not getattr(settings, 'AI_TELEGRAM_BOT_TOKEN', ''):
        return {
            'sent': 0,
            'skipped': 1,
            'failed': 0,
            'reason': 'telegram_token_missing',
        }

    result = {
        'sent': 0,
        'skipped': 0,
        'failed': 0,
        'recipients': [],
    }
    bindings = (
        TelegramUserBinding.objects
        .select_related('user')
        .filter(user__isnull=False, user__is_active=True)
        .order_by('telegram_user_id')
    )

    for binding in bindings:
        portfolio = _default_portfolio_for_user(binding.user)
        if portfolio is None:
            result['skipped'] += 1
            result['recipients'].append({
                'telegram_user_id': binding.telegram_user_id,
                'status': 'skipped',
                'reason': 'portfolio_missing',
            })
            continue

        try:
            _send_telegram_message(
                binding.telegram_chat_id,
                build_portfolio_report_text(portfolio),
                urlopen=urlopen,
            )
        except Exception as exc:
            result['failed'] += 1
            result['recipients'].append({
                'telegram_user_id': binding.telegram_user_id,
                'portfolio_id': str(portfolio.id),
                'status': 'error',
                'error': str(exc),
            })
            continue

        result['sent'] += 1
        result['recipients'].append({
            'telegram_user_id': binding.telegram_user_id,
            'portfolio_id': str(portfolio.id),
            'status': 'sent',
        })

    if not result['recipients']:
        result['skipped'] = 1
        result['reason'] = 'telegram_recipients_missing'
    return result
