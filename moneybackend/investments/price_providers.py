import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from django.conf import settings

from .models import COMMON_CRYPTO_PROVIDER_SYMBOLS


class PriceProviderError(Exception):
    """Controlled provider failure that should not break the money accounting module."""


@dataclass(frozen=True)
class PriceQuote:
    instrument_id: str | None
    symbol: str
    price: Decimal
    price_currency: str
    source: str


class BasePriceProvider:
    source = 'base'
    supports_historical_range = False

    def get_price(self, instrument):
        raise NotImplementedError

    def get_historical_price(self, instrument, on_date):
        raise PriceProviderError('Provider не поддерживает исторические цены.')

    def get_historical_prices(self, instrument, date_from, date_to):
        raise PriceProviderError('Provider не поддерживает пакетную загрузку исторических цен.')


class StaticPriceProvider(BasePriceProvider):
    source = 'static'

    def __init__(self, prices):
        self.prices = {
            (str(symbol).strip().upper(), str(currency).strip().upper()): Decimal(str(price))
            for (symbol, currency), price in prices.items()
        }

    def get_price(self, instrument):
        symbol = (instrument.provider_symbol or instrument.ticker).strip().upper()
        currency = (instrument.quote_currency or 'USD').strip().upper()
        try:
            price = self.prices[(symbol, currency)]
        except KeyError as exc:
            raise PriceProviderError(f'Нет тестовой цены для {symbol}/{currency}.') from exc
        return PriceQuote(
            instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
            symbol=symbol,
            price=price,
            price_currency=currency,
            source=self.source,
        )


class CoinGeckoPriceProvider(BasePriceProvider):
    source = 'coingecko'
    supports_historical_range = True

    def __init__(self, *, base_url=None, history_base_url=None, timeout=None, opener=None):
        self.base_url = base_url or getattr(
            settings,
            'INVESTMENT_PRICE_PROVIDER_BASE_URL',
            'https://api.coingecko.com/api/v3/simple/price',
        )
        self.history_base_url = history_base_url or getattr(
            settings,
            'INVESTMENT_PRICE_PROVIDER_HISTORY_BASE_URL',
            'https://api.coingecko.com/api/v3/coins',
        )
        self.timeout = timeout if timeout is not None else getattr(settings, 'INVESTMENT_PRICE_PROVIDER_TIMEOUT', 10)
        self.opener = opener or urlrequest.urlopen

    def get_price(self, instrument):
        provider_symbol = self._coingecko_id(instrument)
        quote_currency = (instrument.quote_currency or 'USD').strip().lower()
        if not provider_symbol:
            raise PriceProviderError('У инструмента не указан provider_symbol или ticker.')

        query = urlparse.urlencode({
            'ids': provider_symbol,
            'vs_currencies': quote_currency,
        })
        url = f'{self.base_url}?{query}'
        request = urlrequest.Request(
            url,
            headers={'User-Agent': 'MoneyInvestmentPriceProvider/1.0'},
        )

        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise PriceProviderError(f'Не удалось получить цену {provider_symbol}/{quote_currency}.') from exc

        raw_price = payload.get(provider_symbol, {}).get(quote_currency)
        if raw_price is None:
            raise PriceProviderError(f'Provider не вернул цену {provider_symbol}/{quote_currency}.')

        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError) as exc:
            raise PriceProviderError(f'Provider вернул некорректную цену {provider_symbol}/{quote_currency}.') from exc

        if price <= 0:
            raise PriceProviderError(f'Provider вернул неположительную цену {provider_symbol}/{quote_currency}.')

        return PriceQuote(
            instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
            symbol=provider_symbol,
            price=price,
            price_currency=quote_currency.upper(),
            source=self.source,
        )

    def get_historical_price(self, instrument, on_date):
        provider_symbol = self._coingecko_id(instrument)
        quote_currency = (instrument.quote_currency or 'USD').strip().lower()
        rate_date = _normalize_price_date(on_date)
        if not provider_symbol:
            raise PriceProviderError('У инструмента не указан provider_symbol или ticker.')
        if rate_date is None:
            raise PriceProviderError('Не указана дата исторической цены.')

        query = urlparse.urlencode({
            'date': rate_date.strftime('%d-%m-%Y'),
            'localization': 'false',
        })
        url = f'{self.history_base_url.rstrip("/")}/{urlparse.quote(provider_symbol)}/history?{query}'
        request = urlrequest.Request(
            url,
            headers={'User-Agent': 'MoneyInvestmentPriceProvider/1.0'},
        )

        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise PriceProviderError(f'Не удалось получить историческую цену {provider_symbol}/{quote_currency}.') from exc

        raw_price = payload.get('market_data', {}).get('current_price', {}).get(quote_currency)
        if raw_price is None:
            raise PriceProviderError(f'Provider не вернул историческую цену {provider_symbol}/{quote_currency} за {rate_date.isoformat()}.')

        try:
            price = Decimal(str(raw_price))
        except (InvalidOperation, TypeError) as exc:
            raise PriceProviderError(f'Provider вернул некорректную историческую цену {provider_symbol}/{quote_currency}.') from exc

        if price <= 0:
            raise PriceProviderError(f'Provider вернул неположительную историческую цену {provider_symbol}/{quote_currency}.')

        return PriceQuote(
            instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
            symbol=provider_symbol,
            price=price,
            price_currency=quote_currency.upper(),
            source=self.source,
        )

    def get_historical_prices(self, instrument, date_from, date_to):
        provider_symbol = self._coingecko_id(instrument)
        quote_currency = (instrument.quote_currency or 'USD').strip().lower()
        start_date = _normalize_price_date(date_from)
        end_date = _normalize_price_date(date_to)
        if not provider_symbol:
            raise PriceProviderError('У инструмента не указан provider_symbol или ticker.')
        if start_date is None or end_date is None:
            raise PriceProviderError('Не указан период исторических цен.')
        if start_date > end_date:
            raise PriceProviderError('Дата начала исторических цен больше даты окончания.')

        start_at = datetime.combine(start_date, time.min, tzinfo=datetime_timezone.utc)
        end_at = datetime.combine(end_date, time.max, tzinfo=datetime_timezone.utc)
        query = urlparse.urlencode({
            'vs_currency': quote_currency,
            'from': int(start_at.timestamp()),
            'to': int(end_at.timestamp()),
        })
        url = f'{self.history_base_url.rstrip("/")}/{urlparse.quote(provider_symbol)}/market_chart/range?{query}'
        request = urlrequest.Request(
            url,
            headers={'User-Agent': 'MoneyInvestmentPriceProvider/1.0'},
        )

        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise PriceProviderError(f'Не удалось получить исторические цены {provider_symbol}/{quote_currency}.') from exc

        raw_prices = payload.get('prices')
        if not isinstance(raw_prices, list):
            raise PriceProviderError(f'Provider не вернул список исторических цен {provider_symbol}/{quote_currency}.')

        quotes = {}
        for point in raw_prices:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                timestamp_seconds = float(Decimal(str(point[0])) / Decimal('1000'))
                point_date = datetime.fromtimestamp(timestamp_seconds, datetime_timezone.utc).date()
                price = Decimal(str(point[1]))
            except (InvalidOperation, TypeError, ValueError, OSError):
                continue
            if price <= 0 or point_date < start_date or point_date > end_date:
                continue
            quotes[point_date] = PriceQuote(
                instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
                symbol=provider_symbol,
                price=price,
                price_currency=quote_currency.upper(),
                source=self.source,
            )

        if not quotes:
            raise PriceProviderError(f'Provider не вернул исторические цены {provider_symbol}/{quote_currency} за период.')

        return quotes

    def _coingecko_id(self, instrument):
        symbol = (instrument.provider_symbol or instrument.ticker or '').strip().lower()
        return COMMON_CRYPTO_PROVIDER_SYMBOLS.get(symbol.upper(), symbol)


def _normalize_price_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, 'date'):
        return value.date()
    return None


def get_price_provider(name=None):
    provider_name = (name or getattr(settings, 'INVESTMENT_PRICE_PROVIDER', 'coingecko')).strip().lower()
    if provider_name == 'coingecko':
        return CoinGeckoPriceProvider()
    if provider_name == 'static':
        return StaticPriceProvider({})
    if provider_name in {'disabled', 'manual'}:
        raise PriceProviderError('Автоматический price provider отключен.')
    raise PriceProviderError(f'Неизвестный price provider: {provider_name}.')
