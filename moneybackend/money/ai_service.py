import base64
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib import error, request

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import CashFlowItem, Expenditure, FlowOfFunds, Receipt, Transfer, Wallet


INTENT_CREATE_RECEIPT = 'create_receipt'
INTENT_CREATE_EXPENDITURE = 'create_expenditure'
INTENT_CREATE_TRANSFER = 'create_transfer'
INTENT_GET_WALLET_BALANCE = 'get_wallet_balance'
INTENT_GET_ALL_WALLET_BALANCES = 'get_all_wallet_balances'
INTENT_UNKNOWN = 'unknown'

SUPPORTED_INTENTS = {
    INTENT_CREATE_RECEIPT,
    INTENT_CREATE_EXPENDITURE,
    INTENT_CREATE_TRANSFER,
    INTENT_GET_WALLET_BALANCE,
    INTENT_GET_ALL_WALLET_BALANCES,
    INTENT_UNKNOWN,
}


def _normalize_text(value):
    if not value:
        return ''
    normalized = value.strip().lower().replace('ё', 'е')
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def _extract_json_object(raw_text):
    if not raw_text:
        return {}

    text = raw_text.strip()
    fence_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        object_match = re.search(r'(\{.*\})', text, flags=re.DOTALL)
        if object_match:
            text = object_match.group(1)

    return json.loads(text)


def _parse_amount(value):
    if value in (None, ''):
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal('0.01'))
    normalized = str(value).replace(' ', '').replace(',', '.')
    try:
        return Decimal(normalized).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _extract_amount_from_text(text):
    normalized = _normalize_text(text)
    if not normalized:
        return None

    candidates = []
    for match in re.finditer(r'\d[\d\s]*(?:[.,]\d{1,2})?', normalized):
        amount = _parse_amount(match.group(0))
        if amount is not None:
            candidates.append(amount)

    if not candidates:
        return None

    return max(candidates, key=lambda value: abs(value))


def _serialize_decimal(value):
    if value is None:
        return None
    return f'{value.quantize(Decimal("0.01")):.2f}'


def _parse_datetime_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_datetime(str(value))
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _serialize_options(items, *, kind):
    return [
        {
            'index': index,
            'kind': kind,
            'id': str(item.id),
            'label': getattr(item, 'name', getattr(item, 'username', str(item))),
        }
        for index, item in enumerate(items, start=1)
    ]


def _wallet_context():
    return [
        {
            'id': str(wallet.id),
            'name': wallet.name,
            'code': wallet.code,
            'aliases': [alias.alias for alias in wallet.aliases.all()],
        }
        for wallet in Wallet.objects.filter(deleted=False).prefetch_related('aliases').order_by('name')
    ]


def _cash_flow_item_context():
    return [
        {
            'id': str(item.id),
            'name': item.name,
            'code': item.code,
            'aliases': [alias.alias for alias in item.aliases.all()],
        }
        for item in CashFlowItem.objects.filter(deleted=False).prefetch_related('aliases').order_by('name')
    ]


def _wallet_candidates_by_hint(hint, limit=5):
    if not hint:
        return []

    normalized_hint = _normalize_text(hint)
    candidates = list(Wallet.objects.filter(deleted=False).prefetch_related('aliases'))
    exact_matches = []
    partial_matches = []
    for wallet in candidates:
        patterns = {_normalize_text(wallet.name), _normalize_text(wallet.code)}
        patterns.update(_normalize_text(alias.alias) for alias in wallet.aliases.all())
        patterns.discard('')
        if normalized_hint in patterns:
            exact_matches.append(wallet)
        elif normalized_hint and any(
            normalized_hint in pattern or pattern in normalized_hint
            for pattern in patterns
        ):
            partial_matches.append(wallet)

    if exact_matches:
        return exact_matches[:limit]
    return partial_matches[:limit]


def _match_wallet_by_hint(hint):
    candidates = _wallet_candidates_by_hint(hint)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return None


def _cash_flow_item_candidates_by_hint(hint, limit=5):
    if not hint:
        return []

    normalized_hint = _normalize_text(hint)
    candidates = list(CashFlowItem.objects.filter(deleted=False).prefetch_related('aliases'))
    exact_matches = []
    partial_matches = []
    for item in candidates:
        patterns = {_normalize_text(item.name), _normalize_text(item.code)}
        patterns.update(_normalize_text(alias.alias) for alias in item.aliases.all())
        patterns.discard('')
        if normalized_hint in patterns:
            exact_matches.append(item)
        elif normalized_hint and any(
            normalized_hint in pattern or pattern in normalized_hint
            for pattern in patterns
        ):
            partial_matches.append(item)

    if exact_matches:
        return exact_matches[:limit]
    return partial_matches[:limit]


def _match_cash_flow_item_by_hint(hint):
    candidates = _cash_flow_item_candidates_by_hint(hint)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return None


def _wallet_mentions(text, wallets):
    normalized_text = _normalize_text(text)
    matches = []
    for wallet in wallets:
        patterns = [wallet.get('name'), wallet.get('code')]
        patterns.extend(wallet.get('aliases', []))
        for pattern in patterns:
            normalized_pattern = _normalize_text(pattern)
            if not normalized_pattern:
                continue
            position = normalized_text.find(normalized_pattern)
            if position >= 0:
                matches.append((position, wallet['name']))
                break
    matches.sort(key=lambda item: item[0])
    return [name for _, name in matches]


def _extract_cash_flow_item_hint(text, wallets):
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return None

    cleaned_text = normalized_text
    for token in ('приход', 'доход', 'расход', 'трата', 'перевод', 'остаток', 'остатки', 'баланс', 'балансы'):
        cleaned_text = cleaned_text.replace(token, ' ')

    amount_match = re.search(r'(\d[\d\s.,]*)$', cleaned_text)
    if amount_match:
        cleaned_text = cleaned_text[:amount_match.start()]

    for wallet in wallets:
        for pattern in [wallet.get('name'), wallet.get('code'), *wallet.get('aliases', [])]:
            normalized_pattern = _normalize_text(pattern)
            if normalized_pattern:
                cleaned_text = cleaned_text.replace(normalized_pattern, ' ')

    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    return cleaned_text or None


class OpenRouterIntentProvider:
    def __init__(self, api_key, model_name):
        self.api_key = api_key
        self.model_name = model_name

    def parse(self, *, text=None, image_bytes=None, image_mime_type=None, context=None):
        prompt = self._build_prompt(text=text, context=context or {})
        content = [{'type': 'text', 'text': prompt}]
        if image_bytes:
            content.append({
                'type': 'image_url',
                'image_url': {
                    'url': (
                        f'data:{image_mime_type or "image/png"};base64,'
                        f'{base64.b64encode(image_bytes).decode("ascii")}'
                    ),
                }
            })

        payload = {
            'model': self.model_name,
            'messages': [
                {
                    'role': 'user',
                    'content': content,
                }
            ],
            'response_format': {
                'type': 'json_object',
            },
            'temperature': 0.1,
            'provider': {
                'allow_fallbacks': True,
            },
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        site_url = getattr(settings, 'AI_OPENROUTER_SITE_URL', '')
        app_name = getattr(settings, 'AI_OPENROUTER_APP_NAME', '')
        base_url = getattr(
            settings,
            'AI_OPENROUTER_BASE_URL',
            'https://openrouter.ai/api/v1/chat/completions',
        )
        if site_url:
            headers['HTTP-Referer'] = site_url
        if app_name:
            headers['X-Title'] = app_name

        http_request = request.Request(
            base_url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST',
        )

        try:
            with request.urlopen(http_request, timeout=20) as response:
                raw = json.loads(response.read().decode('utf-8'))
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'OpenRouter request failed: {error_body or exc.reason}') from exc
        except error.URLError as exc:
            raise ValueError(f'OpenRouter request failed: {exc.reason}') from exc

        try:
            raw_text = raw['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError('OpenRouter response does not contain a chat message.') from exc

        return _extract_json_object(raw_text)

    def _build_prompt(self, *, text, context):
        return (
            'Ты помощник по личным финансам. '
            'Верни только JSON без пояснений. '
            'Определи intent из списка: '
            'create_receipt, create_expenditure, create_transfer, '
            'get_wallet_balance, get_all_wallet_balances, unknown. '
            'Если передано изображение, считай, что это банковский скриншот операции или истории операций, '
            'и извлеки наиболее вероятную одну операцию из скриншота. '
            'Используй только доступные кошельки и статьи. '
            'Кошельки и статьи ниже являются справочниками системы: '
            'если в тексте есть совпадение по имени, коду или алиасу, обязательно верни это совпадение в соответствующем hint-поле. '
            'Не оставляй wallet_hint, wallet_from_hint, wallet_to_hint и cash_flow_item_hint пустыми, '
            'если в тексте есть разумное совпадение с переданными справочниками. '
            'Сумму ищи во всем тексте, а не только в конце строки. '
            'Если в тексте есть кошелек и сумма, но формулировка свободная, всё равно определи наиболее вероятный intent операции. '
            'Для расходов ищи статью по словам покупки, описанию, merchant и комментарию. '
            'Для кошелька используй wallet_hint, для банка можешь дополнительно заполнить bank_name, но wallet_hint важнее. '
            'Если уверенности нет, ставь intent=unknown или оставляй поля null. '
            'Схема JSON: '
            '{"intent": "...", "confidence": 0.0, "amount": "0.00" | null, '
            '"wallet_hint": null, "wallet_from_hint": null, "wallet_to_hint": null, '
            '"cash_flow_item_hint": null, "merchant": null, "bank_name": null, '
            '"description": null, "occurred_at": null, "operation_sign": null, '
            '"comment": null, "include_in_budget": false}. '
            'operation_sign может быть incoming, outgoing, transfer или null. '
            'occurred_at возвращай в ISO 8601. '
            'Пример: если пользователь пишет "1719000 покупка машины с втб", '
            'а в доступных кошельках есть алиас "втб", то верни wallet_hint="ВТБ" или соответствующий алиас/имя кошелька, '
            'amount="1719000.00" и наиболее подходящую статью в cash_flow_item_hint, если она есть в справочнике. '
            f'Доступные кошельки: {json.dumps(context.get("wallets", []), ensure_ascii=False)}. '
            f'Доступные статьи: {json.dumps(context.get("cash_flow_items", []), ensure_ascii=False)}. '
            f'Текст пользователя: {text or ""}'
        )


class GeminiIntentProvider(OpenRouterIntentProvider):
    """
    Legacy alias: historical provider name `gemini` now routes through OpenRouter
    using a Gemini model instead of calling Google API directly.
    """

    def __init__(self, api_key, model_name):
        super().__init__(api_key=api_key, model_name=model_name)

    def parse(self, *, text=None, image_bytes=None, image_mime_type=None, context=None):
        return super().parse(
            text=text,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            context=context,
        )


class RuleBasedIntentProvider:
    def parse(self, *, text=None, image_bytes=None, image_mime_type=None, context=None):
        context = context or {}
        wallets = context.get('wallets', [])
        normalized_text = _normalize_text(text)
        if not normalized_text:
            return {
                'intent': INTENT_UNKNOWN,
                'confidence': 0.0,
                'comment': 'Пустой ввод.',
            }

        if image_bytes:
            return {
                'intent': INTENT_UNKNOWN,
                'confidence': 0.0,
                'comment': 'Rule-based provider не распознает изображения.',
            }

        amount = _extract_amount_from_text(text)
        wallet_mentions = _wallet_mentions(normalized_text, wallets)

        if 'остатки' in normalized_text or 'балансы' in normalized_text:
            return {
                'intent': INTENT_GET_ALL_WALLET_BALANCES,
                'confidence': 0.99,
                'comment': text,
            }

        if 'остаток' in normalized_text or 'баланс' in normalized_text:
            return {
                'intent': INTENT_GET_WALLET_BALANCE if wallet_mentions else INTENT_GET_ALL_WALLET_BALANCES,
                'confidence': 0.95,
                'wallet_hint': wallet_mentions[0] if wallet_mentions else None,
                'comment': text,
            }

        if normalized_text.startswith('перевод'):
            return {
                'intent': INTENT_CREATE_TRANSFER,
                'confidence': 0.92,
                'amount': _serialize_decimal(amount),
                'wallet_from_hint': wallet_mentions[0] if len(wallet_mentions) > 0 else None,
                'wallet_to_hint': wallet_mentions[1] if len(wallet_mentions) > 1 else None,
                'comment': text,
                'include_in_budget': False,
            }

        if normalized_text.startswith('приход') or normalized_text.startswith('доход'):
            return {
                'intent': INTENT_CREATE_RECEIPT,
                'confidence': 0.9,
                'amount': _serialize_decimal(amount),
                'wallet_hint': wallet_mentions[0] if wallet_mentions else None,
                'comment': text,
                'cash_flow_item_hint': _extract_cash_flow_item_hint(text, wallets),
            }

        if normalized_text.startswith('расход') or normalized_text.startswith('трата'):
            return {
                'intent': INTENT_CREATE_EXPENDITURE,
                'confidence': 0.9,
                'amount': _serialize_decimal(amount),
                'wallet_hint': wallet_mentions[0] if wallet_mentions else None,
                'comment': text,
                'cash_flow_item_hint': _extract_cash_flow_item_hint(text, wallets),
            }

        return {
            'intent': INTENT_UNKNOWN,
            'confidence': 0.0,
            'comment': text,
        }


def _get_intent_provider():
    provider_name = getattr(settings, 'AI_DEFAULT_PROVIDER', 'openrouter')
    if provider_name == 'rule_based':
        return RuleBasedIntentProvider(), provider_name

    if provider_name == 'openrouter':
        api_key = getattr(settings, 'AI_OPENROUTER_API_KEY', '')
        model_name = getattr(settings, 'AI_OPENROUTER_MODEL', 'google/gemini-2.5-flash')
        if api_key:
            return OpenRouterIntentProvider(api_key=api_key, model_name=model_name), provider_name

        if getattr(settings, 'AI_ALLOW_RULE_BASED_FALLBACK', True):
            return RuleBasedIntentProvider(), 'rule_based'
        raise ValueError(
            'OpenRouter provider selected, but AI_OPENROUTER_API_KEY is not configured.'
        )

    raise ValueError(f'Unknown AI provider: {provider_name}')


def _wallet_balance(wallet, *, at_time=None):
    at_time = at_time or timezone.now()
    balance = (
        FlowOfFunds.objects.filter(wallet=wallet, period__lte=at_time).aggregate(total=Sum('amount'))['total']
        or Decimal('0.00')
    )
    return balance.quantize(Decimal('0.01'))


def _all_wallet_balances(*, at_time=None):
    at_time = at_time or timezone.now()
    rows = []
    for wallet in Wallet.objects.filter(deleted=False).order_by('name'):
        rows.append({
            'wallet_id': str(wallet.id),
            'wallet_name': wallet.name,
            'balance': _serialize_decimal(_wallet_balance(wallet, at_time=at_time)),
        })
    return rows


class AiOperationService:
    def build_context(self):
        return {
            'wallets': _wallet_context(),
            'cash_flow_items': _cash_flow_item_context(),
        }

    def process(self, *, text=None, image_bytes=None, image_mime_type=None, wallet_id=None, dry_run=False, source='web'):
        provider, provider_name = _get_intent_provider()
        context = self.build_context()
        parsed = provider.parse(
            text=text,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            context=context,
        )
        normalized = self._normalize_parsed(
            parsed,
            explicit_wallet_id=wallet_id,
            source_text=text,
            context=context,
        )
        normalized['provider'] = provider_name
        normalized['source'] = source

        intent = normalized['intent']
        if intent == INTENT_GET_ALL_WALLET_BALANCES:
            balances = _all_wallet_balances(at_time=timezone.now())
            return {
                'status': 'balance',
                'intent': intent,
                'provider': provider_name,
                'confidence': normalized['confidence'],
                'reply_text': self._build_all_balances_reply(balances),
                'balances': balances,
                'parsed': normalized,
            }

        if intent == INTENT_GET_WALLET_BALANCE:
            wallet = normalized['wallet']
            if wallet is None:
                return self._needs_confirmation(
                    normalized,
                    provider_name,
                    missing_fields=['wallet'],
                    reply_text='Не удалось однозначно определить кошелек для запроса остатка.',
                )
            balance = _wallet_balance(wallet, at_time=timezone.now())
            return {
                'status': 'balance',
                'intent': intent,
                'provider': provider_name,
                'confidence': normalized['confidence'],
                'reply_text': f'Остаток по кошельку "{wallet.name}": {_serialize_decimal(balance)}',
                'balances': [{
                    'wallet_id': str(wallet.id),
                    'wallet_name': wallet.name,
                    'balance': _serialize_decimal(balance),
                }],
                'parsed': normalized,
            }

        if intent == INTENT_UNKNOWN:
            return self._needs_confirmation(
                normalized,
                provider_name,
                missing_fields=['intent'],
                reply_text='Не удалось уверенно определить команду. Нужна формулировка точнее.',
            )

        return self._create_financial_document(normalized, provider_name=provider_name, dry_run=dry_run)

    def create_from_normalized(self, *, normalized, provider_name):
        return self._create_financial_document(normalized, provider_name=provider_name, dry_run=False)

    def continue_confirmation(
        self,
        *,
        normalized_payload,
        missing_fields,
        answer_text,
        provider_name='confirmation',
        dry_run=False,
        options_payload=None,
    ):
        normalized = self.deserialize_normalized(normalized_payload)
        normalized = self.apply_confirmation_answer(
            normalized=normalized,
            answer_text=answer_text,
            missing_fields=missing_fields,
            options_payload=options_payload,
        )
        return self._create_financial_document(normalized, provider_name=provider_name, dry_run=dry_run)

    def _normalize_parsed(self, parsed, explicit_wallet_id=None, source_text=None, context=None):
        context = context or self.build_context()
        wallets = context.get('wallets', [])
        intent = parsed.get('intent') or INTENT_UNKNOWN
        if intent not in SUPPORTED_INTENTS:
            intent = INTENT_UNKNOWN
        operation_sign = parsed.get('operation_sign')
        if intent == INTENT_UNKNOWN and operation_sign == 'incoming':
            intent = INTENT_CREATE_RECEIPT
        elif intent == INTENT_UNKNOWN and operation_sign == 'outgoing':
            intent = INTENT_CREATE_EXPENDITURE
        elif intent == INTENT_UNKNOWN and operation_sign == 'transfer':
            intent = INTENT_CREATE_TRANSFER

        cash_flow_item = _match_cash_flow_item_by_hint(parsed.get('cash_flow_item_hint'))
        if cash_flow_item is None:
            for fallback_hint in (parsed.get('merchant'), parsed.get('description'), parsed.get('comment')):
                cash_flow_item = _match_cash_flow_item_by_hint(fallback_hint)
                if cash_flow_item is not None:
                    break
        if cash_flow_item is None and source_text:
            extracted_hint = _extract_cash_flow_item_hint(source_text, wallets)
            if extracted_hint:
                cash_flow_item = _match_cash_flow_item_by_hint(extracted_hint)

        wallet_hint = parsed.get('wallet_hint') or parsed.get('bank_name')
        wallet = Wallet.objects.filter(pk=explicit_wallet_id).first() if explicit_wallet_id else None
        if wallet is None:
            wallet = _match_wallet_by_hint(wallet_hint)
        if wallet is None and source_text:
            wallet = _match_wallet_by_hint(source_text)

        comment_parts = [
            parsed.get('comment'),
            parsed.get('merchant'),
            parsed.get('description'),
        ]
        comment = ' | '.join(part.strip() for part in comment_parts if part and str(part).strip())
        if not comment and source_text:
            comment = source_text.strip()

        return {
            'intent': intent,
            'confidence': float(parsed.get('confidence') or 0.0),
            'amount': _parse_amount(parsed.get('amount')) or _extract_amount_from_text(source_text),
            'wallet': wallet,
            'wallet_from': _match_wallet_by_hint(parsed.get('wallet_from_hint') or parsed.get('bank_name')),
            'wallet_to': _match_wallet_by_hint(parsed.get('wallet_to_hint')),
            'cash_flow_item': cash_flow_item,
            'comment': comment,
            'include_in_budget': bool(parsed.get('include_in_budget', False)),
            'occurred_at': _parse_datetime_value(parsed.get('occurred_at')),
            'operation_sign': operation_sign,
            'raw': parsed,
        }

    def serialize_normalized(self, normalized):
        fallback_raw = {}
        if (
            isinstance(normalized, dict)
            and 'raw' not in normalized
            and not any(key in normalized for key in ('wallet', 'wallet_from', 'wallet_to', 'cash_flow_item'))
        ):
            fallback_raw = normalized
        return {
            'intent': normalized.get('intent', INTENT_UNKNOWN),
            'confidence': float(normalized.get('confidence') or 0.0),
            'amount': _serialize_decimal(normalized.get('amount')),
            'wallet_id': str(normalized['wallet'].id) if normalized.get('wallet') else None,
            'wallet_from_id': str(normalized['wallet_from'].id) if normalized.get('wallet_from') else None,
            'wallet_to_id': str(normalized['wallet_to'].id) if normalized.get('wallet_to') else None,
            'cash_flow_item_id': (
                str(normalized['cash_flow_item'].id) if normalized.get('cash_flow_item') else None
            ),
            'comment': normalized.get('comment', ''),
            'include_in_budget': bool(normalized.get('include_in_budget', False)),
            'occurred_at': normalized.get('occurred_at').isoformat() if normalized.get('occurred_at') else None,
            'operation_sign': normalized.get('operation_sign'),
            'raw': normalized.get('raw', fallback_raw),
        }

    def deserialize_normalized(self, payload):
        return {
            'intent': payload.get('intent', INTENT_UNKNOWN),
            'confidence': float(payload.get('confidence') or 0.0),
            'amount': _parse_amount(payload.get('amount')),
            'wallet': Wallet.objects.filter(pk=payload.get('wallet_id')).first(),
            'wallet_from': Wallet.objects.filter(pk=payload.get('wallet_from_id')).first(),
            'wallet_to': Wallet.objects.filter(pk=payload.get('wallet_to_id')).first(),
            'cash_flow_item': CashFlowItem.objects.filter(pk=payload.get('cash_flow_item_id')).first(),
            'comment': payload.get('comment', ''),
            'include_in_budget': bool(payload.get('include_in_budget', False)),
            'occurred_at': _parse_datetime_value(payload.get('occurred_at')),
            'operation_sign': payload.get('operation_sign'),
            'raw': payload.get('raw', {}),
        }

    def apply_confirmation_answer(self, *, normalized, answer_text, missing_fields, options_payload=None):
        updated = dict(normalized)
        answer_text = answer_text or ''
        wallets = self.build_context()['wallets']
        wallet_mentions = _wallet_mentions(answer_text, wallets)
        parsed_amount = _extract_amount_from_text(answer_text)
        selected_option = None
        option_index_match = re.fullmatch(r'\s*(\d+)\s*', answer_text or '')
        if option_index_match and options_payload:
            selected_index = int(option_index_match.group(1))
            for option_list in options_payload.values():
                for option in option_list:
                    if option.get('index') == selected_index:
                        selected_option = option
                        break
                if selected_option:
                    break

        if 'amount' in missing_fields and parsed_amount is not None:
            updated['amount'] = parsed_amount

        if 'wallet' in missing_fields and updated.get('wallet') is None:
            if selected_option and selected_option.get('kind') == 'wallet':
                updated['wallet'] = Wallet.objects.filter(pk=selected_option.get('id')).first()
            else:
                updated['wallet'] = _match_wallet_by_hint(answer_text)

        if 'cash_flow_item' in missing_fields and updated.get('cash_flow_item') is None:
            if selected_option and selected_option.get('kind') == 'cash_flow_item':
                updated['cash_flow_item'] = CashFlowItem.objects.filter(pk=selected_option.get('id')).first()
            else:
                updated['cash_flow_item'] = _match_cash_flow_item_by_hint(answer_text)

        if 'wallet_from' in missing_fields and updated.get('wallet_from') is None:
            if selected_option and selected_option.get('kind') == 'wallet':
                updated['wallet_from'] = Wallet.objects.filter(pk=selected_option.get('id')).first()
            elif wallet_mentions:
                updated['wallet_from'] = _match_wallet_by_hint(wallet_mentions[0])
            else:
                updated['wallet_from'] = _match_wallet_by_hint(answer_text)

        if 'wallet_to' in missing_fields and updated.get('wallet_to') is None:
            if selected_option and selected_option.get('kind') == 'wallet':
                updated['wallet_to'] = Wallet.objects.filter(pk=selected_option.get('id')).first()
            elif len(wallet_mentions) > 1:
                updated['wallet_to'] = _match_wallet_by_hint(wallet_mentions[1])
            elif len(wallet_mentions) == 1 and 'wallet_from' not in missing_fields:
                updated['wallet_to'] = _match_wallet_by_hint(wallet_mentions[0])
            else:
                updated['wallet_to'] = _match_wallet_by_hint(answer_text)

        if updated['intent'] in {INTENT_CREATE_RECEIPT, INTENT_CREATE_EXPENDITURE} and not updated.get('cash_flow_item'):
            extracted_hint = _extract_cash_flow_item_hint(answer_text, wallets)
            if extracted_hint:
                updated['cash_flow_item'] = _match_cash_flow_item_by_hint(extracted_hint)

        updated['comment'] = updated.get('comment') or answer_text
        return updated

    def _create_financial_document(self, normalized, *, provider_name, dry_run):
        intent = normalized['intent']
        amount = normalized['amount']
        missing_fields = []
        model_class = None
        create_kwargs = {}
        options = {}

        if amount is None:
            missing_fields.append('amount')

        if intent == INTENT_CREATE_RECEIPT:
            model_class = Receipt
            if normalized['wallet'] is None:
                missing_fields.append('wallet')
                options['wallet'] = _serialize_options(
                    _wallet_candidates_by_hint(normalized['raw'].get('wallet_hint') or normalized['raw'].get('bank_name')),
                    kind='wallet',
                )
            if normalized['cash_flow_item'] is None:
                missing_fields.append('cash_flow_item')
                options['cash_flow_item'] = _serialize_options(
                    _cash_flow_item_candidates_by_hint(
                        normalized['raw'].get('cash_flow_item_hint')
                        or normalized['raw'].get('merchant')
                        or normalized['raw'].get('description')
                    ),
                    kind='cash_flow_item',
                )
            create_kwargs = {
                'wallet': normalized['wallet'],
                'cash_flow_item': normalized['cash_flow_item'],
                'amount': amount,
                'comment': normalized['comment'],
                'date': normalized['occurred_at'] or timezone.now(),
            }
        elif intent == INTENT_CREATE_EXPENDITURE:
            model_class = Expenditure
            if normalized['wallet'] is None:
                missing_fields.append('wallet')
                options['wallet'] = _serialize_options(
                    _wallet_candidates_by_hint(normalized['raw'].get('wallet_hint') or normalized['raw'].get('bank_name')),
                    kind='wallet',
                )
            if normalized['cash_flow_item'] is None:
                missing_fields.append('cash_flow_item')
                options['cash_flow_item'] = _serialize_options(
                    _cash_flow_item_candidates_by_hint(
                        normalized['raw'].get('cash_flow_item_hint')
                        or normalized['raw'].get('merchant')
                        or normalized['raw'].get('description')
                    ),
                    kind='cash_flow_item',
                )
            create_kwargs = {
                'wallet': normalized['wallet'],
                'cash_flow_item': normalized['cash_flow_item'],
                'amount': amount,
                'comment': normalized['comment'],
                'date': normalized['occurred_at'] or timezone.now(),
            }
        elif intent == INTENT_CREATE_TRANSFER:
            model_class = Transfer
            if normalized['wallet_from'] is None:
                missing_fields.append('wallet_from')
                options['wallet_from'] = _serialize_options(
                    _wallet_candidates_by_hint(normalized['raw'].get('wallet_from_hint') or normalized['raw'].get('bank_name')),
                    kind='wallet',
                )
            if normalized['wallet_to'] is None:
                missing_fields.append('wallet_to')
                options['wallet_to'] = _serialize_options(
                    _wallet_candidates_by_hint(normalized['raw'].get('wallet_to_hint')),
                    kind='wallet',
                )
            create_kwargs = {
                'wallet_out': normalized['wallet_from'],
                'wallet_in': normalized['wallet_to'],
                'amount': amount,
                'comment': normalized['comment'],
                'include_in_budget': normalized['include_in_budget'],
                'cash_flow_item': normalized['cash_flow_item'],
                'date': normalized['occurred_at'] or timezone.now(),
            }
        else:
            return self._needs_confirmation(
                normalized,
                provider_name,
                missing_fields=['intent'],
                reply_text='Intent пока не поддержан для создания документа.',
            )

        if missing_fields:
            return self._needs_confirmation(
                normalized,
                provider_name,
                missing_fields=missing_fields,
                reply_text='Недостаточно данных для автоматического создания документа.',
                options=options,
                preview=self._build_preview(model_class, create_kwargs),
            )

        if dry_run:
            return {
                'status': 'preview',
                'intent': intent,
                'provider': provider_name,
                'confidence': normalized['confidence'],
                'reply_text': 'Команда распознана. Документ не создан, потому что включен dry_run.',
                'preview': self._build_preview(model_class, create_kwargs),
                'parsed': normalized,
            }

        with transaction.atomic():
            document = model_class.objects.create(**create_kwargs)

        return {
            'status': 'created',
            'intent': intent,
            'provider': provider_name,
            'confidence': normalized['confidence'],
            'reply_text': self._build_created_reply(document),
            'created_object': {
                'model': model_class.__name__,
                'id': str(document.id),
                'number': document.number,
            },
            'parsed': normalized,
        }

    def _build_preview(self, model_class, create_kwargs):
        preview = {
            'model': model_class.__name__,
            'amount': _serialize_decimal(create_kwargs.get('amount')),
            'comment': create_kwargs.get('comment', ''),
            'date': create_kwargs.get('date').isoformat() if create_kwargs.get('date') else None,
        }
        for field_name in ('wallet', 'wallet_out', 'wallet_in', 'cash_flow_item'):
            value = create_kwargs.get(field_name)
            if value is not None:
                preview[field_name] = str(value.id)
                preview[f'{field_name}_name'] = getattr(value, 'name', getattr(value, 'username', None))
        return preview

    def _build_created_reply(self, document):
        if isinstance(document, Receipt):
            return f'Создан приход {document.number} на сумму {document.amount:.2f}.'
        if isinstance(document, Expenditure):
            return f'Создан расход {document.number} на сумму {document.amount:.2f}.'
        if isinstance(document, Transfer):
            return f'Создан перевод {document.number} на сумму {document.amount:.2f}.'
        return f'Создан документ {document.number}.'

    def _build_all_balances_reply(self, balances):
        if not balances:
            return 'Кошельки не найдены.'
        lines = ['Остатки по кошелькам:']
        for row in balances:
            lines.append(f'- {row["wallet_name"]}: {row["balance"]}')
        return '\n'.join(lines)

    def _build_confirmation_reply(self, reply_text, options):
        if not options:
            return reply_text
        lines = [reply_text]
        for field_name, option_list in options.items():
            if not option_list:
                continue
            lines.append(f'Варианты для {field_name}:')
            for option in option_list:
                lines.append(f'{option["index"]}. {option["label"]}')
        lines.append('Можно ответить номером варианта, текстом или /cancel.')
        return '\n'.join(lines)

    def _needs_confirmation(self, normalized, provider_name, *, missing_fields, reply_text, options=None, preview=None):
        options = options or {}
        return {
            'status': 'needs_confirmation',
            'intent': normalized['intent'],
            'provider': provider_name,
            'confidence': normalized['confidence'],
            'reply_text': self._build_confirmation_reply(reply_text, options),
            'missing_fields': missing_fields,
            'options': options,
            'preview': preview or {},
            'parsed': normalized,
        }
