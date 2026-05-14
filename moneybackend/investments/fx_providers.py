import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from django.conf import settings


class FxRateProviderError(Exception):
    """Controlled FX provider failure that must not affect money accounting."""


@dataclass(frozen=True)
class FxRateQuote:
    base_currency: str
    quote_currency: str
    rate: Decimal
    source: str


class BaseFxRateProvider:
    source = 'base'

    def get_rate(self, base_currency, quote_currency='USD', on_date=None):
        raise NotImplementedError


class StaticFxRateProvider(BaseFxRateProvider):
    source = 'static'

    def __init__(self, rates):
        self.rates = {
            (str(base).strip().upper(), str(quote).strip().upper()): Decimal(str(rate))
            for (base, quote), rate in rates.items()
        }

    def get_rate(self, base_currency, quote_currency='USD', on_date=None):
        base = str(base_currency or '').strip().upper()
        quote = str(quote_currency or 'USD').strip().upper()
        if base == quote:
            return FxRateQuote(base_currency=base, quote_currency=quote, rate=Decimal('1'), source=self.source)
        try:
            rate = self.rates[(base, quote)]
        except KeyError as exc:
            raise FxRateProviderError(f'Нет тестового курса {base}/{quote}.') from exc
        if rate <= 0:
            raise FxRateProviderError(f'Некорректный тестовый курс {base}/{quote}.')
        return FxRateQuote(base_currency=base, quote_currency=quote, rate=rate, source=self.source)


class CbrFxRateProvider(BaseFxRateProvider):
    source = 'cbr'

    def __init__(self, *, base_url=None, timeout=None, opener=None):
        self.base_url = base_url or getattr(
            settings,
            'INVESTMENT_FX_PROVIDER_BASE_URL',
            'https://www.cbr.ru/scripts/XML_daily.asp',
        )
        self.timeout = timeout if timeout is not None else getattr(settings, 'INVESTMENT_FX_PROVIDER_TIMEOUT', 10)
        self.opener = opener or urlrequest.urlopen
        self._rates_by_date = {}

    def get_rate(self, base_currency, quote_currency='USD', on_date=None):
        base = str(base_currency or '').strip().upper()
        quote = str(quote_currency or 'USD').strip().upper()
        if not base:
            raise FxRateProviderError('Не указана базовая валюта курса.')
        if base == quote:
            return FxRateQuote(base_currency=base, quote_currency=quote, rate=Decimal('1'), source=self.source)

        rates = self._get_rates(on_date=on_date)
        try:
            base_to_rub = rates[base]
            quote_to_rub = rates[quote]
        except KeyError as exc:
            raise FxRateProviderError(f'CBR provider не вернул курс для пары {base}/{quote}.') from exc
        return FxRateQuote(base_currency=base, quote_currency=quote, rate=base_to_rub / quote_to_rub, source=self.source)

    def _get_rates(self, on_date=None):
        rate_date = _normalize_rate_date(on_date)
        cache_key = rate_date.isoformat() if rate_date is not None else 'latest'
        if cache_key in self._rates_by_date:
            return self._rates_by_date[cache_key]

        url = self.base_url
        if rate_date is not None:
            separator = '&' if '?' in url else '?'
            url = f'{url}{separator}{urlparse.urlencode({"date_req": rate_date.strftime("%d/%m/%Y")})}'

        request = urlrequest.Request(
            url,
            headers={'User-Agent': 'MoneyInvestmentFxProvider/1.0'},
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                payload = response.read()
            root = ET.fromstring(payload)
        except (HTTPError, URLError, TimeoutError, OSError, ET.ParseError) as exc:
            raise FxRateProviderError('Не удалось получить курсы CBR.') from exc

        rates = {'RUB': Decimal('1')}
        for node in root.findall('Valute'):
            code_node = node.find('CharCode')
            nominal_node = node.find('Nominal')
            value_node = node.find('Value')
            if code_node is None or nominal_node is None or value_node is None:
                continue
            code = (code_node.text or '').strip().upper()
            try:
                nominal = Decimal((nominal_node.text or '').replace(',', '.'))
                value = Decimal((value_node.text or '').replace(',', '.'))
                rate = value / nominal
            except (InvalidOperation, ZeroDivisionError) as exc:
                raise FxRateProviderError(f'CBR provider вернул некорректный курс {code}/RUB.') from exc
            if code and rate > 0:
                rates[code] = rate

        self._rates_by_date[cache_key] = rates
        return rates


def _normalize_rate_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if hasattr(value, 'date'):
        return value.date()
    return None


def get_fx_rate_provider(name=None):
    provider_name = (name or getattr(settings, 'INVESTMENT_FX_PROVIDER', 'cbr')).strip().lower()
    if provider_name == 'cbr':
        return CbrFxRateProvider()
    if provider_name == 'static':
        return StaticFxRateProvider({})
    if provider_name in {'disabled', 'manual'}:
        raise FxRateProviderError('Автоматический FX provider отключен.')
    raise FxRateProviderError(f'Неизвестный FX provider: {provider_name}.')
