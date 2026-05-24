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


class StooqPriceProvider(BasePriceProvider):
    source = 'stooq'
    supports_historical_range = True

    def __init__(self, *, quote_base_url=None, history_base_url=None, timeout=None, opener=None):
        self.quote_base_url = quote_base_url or getattr(
            settings,
            'INVESTMENT_STOCK_PRICE_PROVIDER_BASE_URL',
            'https://stooq.com/q/l/',
        )
        self.history_base_url = history_base_url or getattr(
            settings,
            'INVESTMENT_STOCK_PRICE_PROVIDER_HISTORY_BASE_URL',
            'https://stooq.com/q/d/l/',
        )
        self.timeout = timeout if timeout is not None else getattr(settings, 'INVESTMENT_PRICE_PROVIDER_TIMEOUT', 10)
        self.opener = opener or urlrequest.urlopen

    def get_price(self, instrument):
        symbol = self._stooq_symbol(instrument)
        if not symbol:
            raise PriceProviderError('У акции не указан provider_symbol или ticker.')
        query = urlparse.urlencode({
            's': symbol,
            'f': 'sd2t2ohlcv',
            'h': '',
            'e': 'csv',
        })
        url = f'{self.quote_base_url}?{query}'
        rows = self._read_csv_rows(url, symbol)
        if not rows:
            raise PriceProviderError(f'Provider не вернул цену акции {symbol}.')
        row = rows[0]
        price = self._parse_positive_decimal(row.get('Close'), symbol)
        return PriceQuote(
            instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
            symbol=symbol,
            price=price,
            price_currency=(instrument.quote_currency or 'USD').strip().upper(),
            source=self.source,
        )

    def get_historical_price(self, instrument, on_date):
        prices = self.get_historical_prices(instrument, on_date, on_date)
        normalized_date = _normalize_price_date(on_date)
        try:
            return prices[normalized_date]
        except KeyError as exc:
            raise PriceProviderError(f'Provider не вернул историческую цену акции за {normalized_date.isoformat()}.') from exc

    def get_historical_prices(self, instrument, date_from, date_to):
        symbol = self._stooq_symbol(instrument)
        start_date = _normalize_price_date(date_from)
        end_date = _normalize_price_date(date_to)
        if not symbol:
            raise PriceProviderError('У акции не указан provider_symbol или ticker.')
        if start_date is None or end_date is None:
            raise PriceProviderError('Не указан период исторических цен.')
        if start_date > end_date:
            raise PriceProviderError('Дата начала исторических цен больше даты окончания.')

        query = urlparse.urlencode({
            's': symbol,
            'd1': start_date.strftime('%Y%m%d'),
            'd2': end_date.strftime('%Y%m%d'),
            'i': 'd',
        })
        url = f'{self.history_base_url}?{query}'
        rows = self._read_csv_rows(url, symbol)
        quotes = {}
        for row in rows:
            row_date = _parse_stooq_date(row.get('Date'))
            if row_date is None or row_date < start_date or row_date > end_date:
                continue
            price = self._parse_positive_decimal(row.get('Close'), symbol)
            quotes[row_date] = PriceQuote(
                instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
                symbol=symbol,
                price=price,
                price_currency=(instrument.quote_currency or 'USD').strip().upper(),
                source=self.source,
            )
        if not quotes:
            raise PriceProviderError(f'Provider не вернул исторические цены акции {symbol} за период.')
        return quotes

    def _read_csv_rows(self, url, symbol):
        request = urlrequest.Request(
            url,
            headers={'User-Agent': 'MoneyInvestmentStockPriceProvider/1.0'},
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw_text = response.read().decode('utf-8')
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise PriceProviderError(f'Не удалось получить цену акции {symbol}.') from exc

        rows = [line.strip().split(',') for line in raw_text.splitlines() if line.strip()]
        if len(rows) < 2:
            raise PriceProviderError(f'Provider не вернул CSV с ценой акции {symbol}.')
        headers = rows[0]
        parsed_rows = []
        for values in rows[1:]:
            row = {header: values[index] if index < len(values) else '' for index, header in enumerate(headers)}
            if row.get('Close') in {'', 'N/D', 'No data'}:
                continue
            parsed_rows.append(row)
        return parsed_rows

    def _parse_positive_decimal(self, value, symbol):
        try:
            price = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise PriceProviderError(f'Provider вернул некорректную цену акции {symbol}.') from exc
        if price <= 0:
            raise PriceProviderError(f'Provider вернул неположительную цену акции {symbol}.')
        return price

    def _stooq_symbol(self, instrument):
        return (instrument.provider_symbol or instrument.ticker or '').strip().lower()


class MoexPriceProvider(BasePriceProvider):
    source = 'moex'
    supports_historical_range = True
    DEFAULT_BOARDS = {
        'bond': 'TQOB',
        'stock': 'TQBR',
    }
    DEFAULT_MARKETS = {
        'bond': 'bonds',
        'stock': 'shares',
    }

    def __init__(self, *, base_url=None, board=None, timeout=None, opener=None):
        self.base_url = (base_url or getattr(
            settings,
            'INVESTMENT_MOEX_PRICE_PROVIDER_BASE_URL',
            'https://iss.moex.com/iss',
        )).rstrip('/')
        self.board = board.strip().upper() if board else None
        self.default_board = getattr(settings, 'INVESTMENT_MOEX_BOARD', 'TQBR').strip().upper()
        self.timeout = timeout if timeout is not None else getattr(settings, 'INVESTMENT_PRICE_PROVIDER_TIMEOUT', 10)
        self.opener = opener or urlrequest.urlopen

    def get_price(self, instrument):
        symbol = self._moex_symbol(instrument)
        if not symbol:
            raise PriceProviderError('У инструмента MOEX не указан provider_symbol или ticker.')
        market, board = self._market_and_board_for(instrument)
        query = urlparse.urlencode({
            'iss.meta': 'off',
            'iss.only': 'securities,marketdata',
            'securities.columns': 'SECID,FACEVALUE,FACEUNIT',
            'marketdata.columns': 'SECID,LAST,LCURRENTPRICE,MARKETPRICE,CLOSEPRICE,PREVPRICE',
        })
        url = f'{self.base_url}/engines/stock/markets/{market}/boards/{board}/securities/{urlparse.quote(symbol)}.json?{query}'
        payload = self._read_json(url, symbol)
        marketdata = payload.get('marketdata') if isinstance(payload, dict) else None
        row = self._first_table_row(marketdata)
        raw_price = self._first_positive_decimal(
            row,
            ('LAST', 'LCURRENTPRICE', 'MARKETPRICE', 'CLOSEPRICE', 'PREVPRICE'),
            symbol,
        )
        price, price_currency = self._normalize_moex_price(
            instrument,
            symbol,
            raw_price,
            payload.get('securities') if isinstance(payload, dict) else None,
        )
        return PriceQuote(
            instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
            symbol=symbol,
            price=price,
            price_currency=price_currency,
            source=self.source,
        )

    def get_historical_price(self, instrument, on_date):
        prices = self.get_historical_prices(instrument, on_date, on_date)
        normalized_date = _normalize_price_date(on_date)
        try:
            return prices[normalized_date]
        except KeyError as exc:
            raise PriceProviderError(f'MOEX не вернул историческую цену {instrument.ticker} за {normalized_date.isoformat()}.') from exc

    def get_historical_prices(self, instrument, date_from, date_to):
        symbol = self._moex_symbol(instrument)
        start_date = _normalize_price_date(date_from)
        end_date = _normalize_price_date(date_to)
        if not symbol:
            raise PriceProviderError('У инструмента MOEX не указан provider_symbol или ticker.')
        market, board = self._market_and_board_for(instrument)
        if start_date is None or end_date is None:
            raise PriceProviderError('Не указан период исторических цен MOEX.')
        if start_date > end_date:
            raise PriceProviderError('Дата начала исторических цен больше даты окончания.')

        query = urlparse.urlencode({
            'from': start_date.isoformat(),
            'till': end_date.isoformat(),
            'interval': 24,
            'iss.meta': 'off',
            'candles.columns': 'begin,close',
        })
        url = f'{self.base_url}/engines/stock/markets/{market}/boards/{board}/securities/{urlparse.quote(symbol)}/candles.json?{query}'
        payload = self._read_json(url, symbol)
        candles = payload.get('candles') if isinstance(payload, dict) else None
        rows = self._table_rows(candles)
        security_details = self._security_details_for_symbol(symbol) if self._is_bond(instrument) else None
        quotes = {}
        for row in rows:
            row_date = _parse_moex_datetime_date(row.get('begin'))
            if row_date is None or row_date < start_date or row_date > end_date:
                continue
            raw_price = self._parse_positive_decimal(row.get('close'), symbol)
            price, price_currency = self._normalize_moex_price(
                instrument,
                symbol,
                raw_price,
                security_details=security_details,
            )
            quotes[row_date] = PriceQuote(
                instrument_id=str(instrument.id) if getattr(instrument, 'id', None) else None,
                symbol=symbol,
                price=price,
                price_currency=price_currency,
                source=self.source,
            )
        if not quotes:
            raise PriceProviderError(f'MOEX не вернул исторические цены {symbol} за период.')
        return quotes

    def _read_json(self, url, symbol):
        request = urlrequest.Request(
            url,
            headers={'User-Agent': 'MoneyInvestmentMoexPriceProvider/1.0'},
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise PriceProviderError(f'Не удалось получить цену MOEX {symbol}.') from exc

    def _table_rows(self, table):
        if not isinstance(table, dict):
            return []
        columns = table.get('columns')
        data = table.get('data')
        if not isinstance(columns, list) or not isinstance(data, list):
            return []
        return [
            {column: values[index] if index < len(values) else None for index, column in enumerate(columns)}
            for values in data
            if isinstance(values, list)
        ]

    def _first_table_row(self, table):
        rows = self._table_rows(table)
        if not rows:
            raise PriceProviderError('MOEX не вернул строку с ценой.')
        return rows[0]

    def _first_positive_decimal(self, row, fields, symbol):
        for field in fields:
            value = row.get(field)
            if value in (None, '', 'N/D'):
                continue
            try:
                price = self._parse_positive_decimal(value, symbol)
            except PriceProviderError:
                continue
            return price
        raise PriceProviderError(f'MOEX не вернул положительную цену {symbol}.')

    def _parse_positive_decimal(self, value, symbol):
        try:
            price = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise PriceProviderError(f'MOEX вернул некорректную цену {symbol}.') from exc
        if price <= 0:
            raise PriceProviderError(f'MOEX вернул неположительную цену {symbol}.')
        return price

    def _moex_symbol(self, instrument):
        return (instrument.provider_symbol or instrument.ticker or '').strip().upper()

    def _market_and_board_for(self, instrument):
        instrument_type = (getattr(instrument, 'type', '') or '').strip().lower()
        default_market = self.DEFAULT_MARKETS.get(instrument_type, 'shares')
        if self.board:
            return default_market, self.board
        symbol = self._moex_symbol(instrument)
        if symbol:
            try:
                return self._primary_market_and_board_for_symbol(symbol)
            except PriceProviderError:
                pass
        return default_market, self.DEFAULT_BOARDS.get(instrument_type, self.default_board)

    def _primary_market_and_board_for_symbol(self, symbol):
        query = urlparse.urlencode({
            'iss.meta': 'off',
            'iss.only': 'boards',
            'boards.columns': 'boardid,is_traded,is_primary,currencyid,market',
        })
        url = f'{self.base_url}/securities/{urlparse.quote(symbol)}.json?{query}'
        payload = self._read_json(url, symbol)
        boards = payload.get('boards') if isinstance(payload, dict) else None
        rows = self._table_rows(boards)
        if not rows:
            raise PriceProviderError(f'MOEX не вернул boards для {symbol}.')
        candidates = [row for row in rows if str(row.get('is_traded')) == '1' and (row.get('market') or '').lower() == 'bonds']
        if not candidates:
            candidates = [row for row in rows if str(row.get('is_traded')) == '1']
        primary = next((row for row in candidates if str(row.get('is_primary')) == '1'), None)
        selected = primary or candidates[0] if candidates else None
        board = (selected or {}).get('boardid')
        if not board:
            raise PriceProviderError(f'MOEX не вернул primary board для {symbol}.')
        market = ((selected or {}).get('market') or 'shares')
        return str(market).strip().lower(), str(board).strip().upper()

    def _normalize_moex_price(self, instrument, symbol, raw_price, securities_table=None, security_details=None):
        if not self._is_bond(instrument):
            return raw_price, 'RUB'
        details = security_details or self._first_security_details(securities_table) or self._security_details_for_symbol(symbol)
        facevalue = self._parse_positive_decimal(details.get('FACEVALUE'), symbol)
        faceunit = (details.get('FACEUNIT') or 'RUB').strip().upper()
        return (raw_price * facevalue / Decimal('100')), faceunit

    def _security_details_for_symbol(self, symbol):
        query = urlparse.urlencode({
            'iss.meta': 'off',
            'iss.only': 'description',
        })
        url = f'{self.base_url}/securities/{urlparse.quote(symbol)}.json?{query}'
        payload = self._read_json(url, symbol)
        description = payload.get('description') if isinstance(payload, dict) else None
        rows = self._table_rows(description)
        return {str(row.get('name')).upper(): row.get('value') for row in rows if row.get('name')}

    def _first_security_details(self, securities_table):
        rows = self._table_rows(securities_table)
        return rows[0] if rows else None

    def _is_bond(self, instrument):
        return (getattr(instrument, 'type', '') or '').strip().lower() == 'bond'


class CompositePriceProvider(BasePriceProvider):
    source = 'auto'
    supports_historical_range = True

    def __init__(self, *, crypto_provider=None, stock_provider=None, moex_provider=None):
        self.crypto_provider = crypto_provider or CoinGeckoPriceProvider()
        self.stock_provider = stock_provider or StooqPriceProvider()
        self.moex_provider = moex_provider or MoexPriceProvider()

    def _provider_for(self, instrument):
        instrument_type = getattr(instrument, 'type', 'crypto')
        if self._looks_like_moex_symbol(instrument):
            return self.moex_provider
        if instrument_type in {'stock', 'bond'}:
            quote_currency = (getattr(instrument, 'quote_currency', None) or 'USD').strip().upper()
            if quote_currency == 'RUB' or instrument_type == 'bond':
                return self.moex_provider
            return self.stock_provider
        return self.crypto_provider

    def _looks_like_moex_symbol(self, instrument):
        symbol = (getattr(instrument, 'provider_symbol', None) or getattr(instrument, 'ticker', '') or '').strip().upper()
        return symbol.startswith('RU') and len(symbol) == 12

    def get_price(self, instrument):
        return self._provider_for(instrument).get_price(instrument)

    def get_historical_price(self, instrument, on_date):
        return self._provider_for(instrument).get_historical_price(instrument, on_date)

    def get_historical_prices(self, instrument, date_from, date_to):
        provider = self._provider_for(instrument)
        return provider.get_historical_prices(instrument, date_from, date_to)


def _parse_stooq_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _parse_moex_datetime_date(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.strptime(text[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


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
    provider_name = (name or getattr(settings, 'INVESTMENT_PRICE_PROVIDER', 'auto')).strip().lower()
    if provider_name == 'auto':
        return CompositePriceProvider()
    if provider_name == 'coingecko':
        return CompositePriceProvider(crypto_provider=CoinGeckoPriceProvider())
    if provider_name == 'stooq':
        return StooqPriceProvider()
    if provider_name == 'moex':
        return MoexPriceProvider()
    if provider_name == 'static':
        return StaticPriceProvider({})
    if provider_name in {'disabled', 'manual'}:
        raise PriceProviderError('Автоматический price provider отключен.')
    raise PriceProviderError(f'Неизвестный price provider: {provider_name}.')
