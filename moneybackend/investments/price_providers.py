import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from django.conf import settings


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

    def get_price(self, instrument):
        raise NotImplementedError


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
    COMMON_CRYPTO_IDS = {
        'btc': 'bitcoin',
        'eth': 'ethereum',
        'usdt': 'tether',
    }

    def __init__(self, *, base_url=None, timeout=None, opener=None):
        self.base_url = base_url or getattr(
            settings,
            'INVESTMENT_PRICE_PROVIDER_BASE_URL',
            'https://api.coingecko.com/api/v3/simple/price',
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

    def _coingecko_id(self, instrument):
        symbol = (instrument.provider_symbol or instrument.ticker or '').strip().lower()
        return self.COMMON_CRYPTO_IDS.get(symbol, symbol)


def get_price_provider(name=None):
    provider_name = (name or getattr(settings, 'INVESTMENT_PRICE_PROVIDER', 'coingecko')).strip().lower()
    if provider_name == 'coingecko':
        return CoinGeckoPriceProvider()
    if provider_name == 'static':
        return StaticPriceProvider({})
    if provider_name in {'disabled', 'manual'}:
        raise PriceProviderError('Автоматический price provider отключен.')
    raise PriceProviderError(f'Неизвестный price provider: {provider_name}.')
