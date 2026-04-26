import base64
import json
import mimetypes
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib import error, request

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import CashFlowItem, Expenditure, FlowOfFunds, Receipt, Transfer, Wallet, ZERO_AMOUNT


INTENT_CREATE_RECEIPT = 'create_receipt'
INTENT_CREATE_EXPENDITURE = 'create_expenditure'
INTENT_CREATE_TRANSFER = 'create_transfer'
INTENT_GET_WALLET_BALANCE = 'get_wallet_balance'
INTENT_GET_ALL_WALLET_BALANCES = 'get_all_wallet_balances'
INTENT_HELP_CAPABILITIES = 'help_capabilities'
INTENT_UNKNOWN = 'unknown'
INTENT_CREATE_MULTIPLE_OPERATIONS = 'create_multiple_operations'

SUPPORTED_INTENTS = {
    INTENT_CREATE_RECEIPT,
    INTENT_CREATE_EXPENDITURE,
    INTENT_CREATE_TRANSFER,
    INTENT_GET_WALLET_BALANCE,
    INTENT_GET_ALL_WALLET_BALANCES,
    INTENT_HELP_CAPABILITIES,
    INTENT_UNKNOWN,
}

TRANSCRIPTION_MAX_BYTES = 25 * 1024 * 1024


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
    raw_value = (
        str(value)
        .strip()
        .replace('\xa0', ' ')
        .replace('−', '-')
        .replace('–', '-')
        .replace('—', '-')
    )
    number_match = re.search(r'[-+]?\d[\d\s]*(?:[.,]\d{1,2})?', raw_value)
    if not number_match:
        return None
    normalized = number_match.group(0).replace(' ', '').replace(',', '.')
    try:
        return Decimal(normalized).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


def _extract_amount_from_text(text):
    if not text:
        return None

    candidates = []
    for match in re.finditer(r'[-+−–—]?\s*\d[\d\s]*(?:[.,]\d{1,2})?', str(text)):
        amount = _parse_amount(match.group(0))
        if amount is not None:
            candidates.append(amount)

    if not candidates:
        return None

    return max(candidates, key=lambda value: abs(value))


def _collect_fallback_text(*parts):
    chunks = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            chunks.extend(str(item).strip() for item in part if str(item).strip())
            continue
        text = str(part).strip()
        if text:
            chunks.append(text)
    return ' '.join(chunks)


def _normalize_operation_amount(amount, *, intent, operation_sign):
    if amount is None:
        return None
    if intent in {INTENT_CREATE_RECEIPT, INTENT_CREATE_EXPENDITURE, INTENT_CREATE_TRANSFER}:
        return abs(amount)
    if operation_sign in {'incoming', 'outgoing', 'transfer'}:
        return abs(amount)
    return amount


def _detect_assistant_meta_intent(text):
    normalized = _normalize_text(text)
    if not normalized:
        return None

    help_prefixes = ('/start', '/help')
    help_phrases = (
        'что ты умеешь',
        'что умеешь',
        'что ты можешь',
        'что можешь',
        'какие команды',
        'помощь',
        'help',
        'как пользоваться',
        'как работать',
        'что можно сделать',
    )
    greeting_phrases = {
        'привет',
        'здравствуйте',
        'добрый день',
        'добрый вечер',
        'доброе утро',
    }

    if normalized.startswith(help_prefixes):
        return {
            'intent': INTENT_HELP_CAPABILITIES,
            'confidence': 1.0,
            'comment': text,
        }

    if any(phrase in normalized for phrase in help_phrases):
        return {
            'intent': INTENT_HELP_CAPABILITIES,
            'confidence': 0.99,
            'comment': text,
        }

    if normalized in greeting_phrases:
        return {
            'intent': INTENT_HELP_CAPABILITIES,
            'confidence': 0.8,
            'comment': text,
        }

    return None


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


def _default_audio_filename(mime_type):
    normalized_mime_type = (mime_type or '').split(';', 1)[0].strip().lower()
    extension = mimetypes.guess_extension(normalized_mime_type) if normalized_mime_type else None
    if not extension:
        extension = '.ogg'
    return f'telegram-voice{extension}'


def _build_multipart_form_data(*, fields, files):
    boundary = f'----MoneyBoundary{uuid.uuid4().hex}'
    chunks = []

    for field_name, value in fields.items():
        if value in (None, ''):
            continue
        chunks.extend([
            f'--{boundary}\r\n'.encode('utf-8'),
            f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode('utf-8'),
            str(value).encode('utf-8'),
            b'\r\n',
        ])

    for file_info in files:
        chunks.extend([
            f'--{boundary}\r\n'.encode('utf-8'),
            (
                f'Content-Disposition: form-data; name="{file_info["field_name"]}"; '
                f'filename="{file_info["file_name"]}"\r\n'
            ).encode('utf-8'),
            f'Content-Type: {file_info["content_type"]}\r\n\r\n'.encode('utf-8'),
            file_info['content'],
            b'\r\n',
        ])

    chunks.append(f'--{boundary}--\r\n'.encode('utf-8'))
    return boundary, b''.join(chunks)


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
        force_all_operations = bool((context or {}).get('force_all_operations'))
        image_instruction = (
            'и извлеки все видимые денежные операции из скриншота. '
            if force_all_operations
            else 'и извлеки наиболее вероятную одну операцию из скриншота. '
        )
        force_note = (
            'Это режим обязательного полного разбора истории: не возвращай только одну операцию, '
            'если на изображении видно несколько списаний или поступлений. '
            if force_all_operations
            else ''
        )
        return (
            'Ты помощник по личным финансам. '
            'Верни только JSON без пояснений. '
            'Определи intent из списка: '
            'create_receipt, create_expenditure, create_transfer, '
            'get_wallet_balance, get_all_wallet_balances, help_capabilities, unknown. '
            'Если передано изображение, считай, что это банковский скриншот операции или истории операций, '
            f'{image_instruction}'
            'Если на изображении список или история операций, выбери одну самую вероятную строку операции: '
            'обычно верхнюю или последнюю видимую покупку с суммой, торговой точкой и датой. '
            'Игнорируй кнопки интерфейса, баннеры, баланс, поисковую строку и декоративные элементы. '
            'Категорию операции вроде "Продукты", "Транспорт", "Фастфуд" используй как description или cash_flow_item_hint. '
            'Если на изображении видно несколько денежных операций, верни их все в массиве operations. '
            'Каждый элемент operations должен описывать одну денежную операцию. '
            'Игнорируй бонусные баллы, кешбэк в баллах, награды, счетчики и нефинансовые элементы. '
            f'{force_note}'
            'Используй только доступные кошельки и статьи. '
            'Кошельки и статьи ниже являются справочниками системы: '
            'если в тексте есть совпадение по имени, коду или алиасу, обязательно верни это совпадение в соответствующем hint-поле. '
            'Не оставляй wallet_hint, wallet_from_hint, wallet_to_hint и cash_flow_item_hint пустыми, '
            'если в тексте есть разумное совпадение с переданными справочниками. '
            'Сумму ищи во всем тексте, а не только в конце строки. '
            'Если в тексте есть кошелек и сумма, но формулировка свободная, всё равно определи наиболее вероятный intent операции. '
            'Для расходов ищи статью по словам покупки, описанию, merchant и комментарию. '
            'Для кошелька используй wallet_hint, для банка можешь дополнительно заполнить bank_name, но wallet_hint важнее. '
            'Если пользователь спрашивает о возможностях помощника, просит помощь, примеры команд или здоровается, '
            'верни intent=help_capabilities. '
            'Если уверенности нет, ставь intent=unknown или оставляй поля null. '
            'Схема JSON: '
            '{"intent": "...", "confidence": 0.0, "amount": "0.00" | null, '
            '"wallet_hint": null, "wallet_from_hint": null, "wallet_to_hint": null, '
            '"cash_flow_item_hint": null, "merchant": null, "bank_name": null, '
            '"description": null, "occurred_at": null, "operation_sign": null, '
            '"comment": null, "include_in_budget": false, '
            '"operations": [{"intent": "...", "amount": "0.00", "merchant": "..."}] | null}. '
            'operation_sign может быть incoming, outgoing, transfer или null. '
            'amount возвращай числом без знака валюты и без символа ₽, а направление отражай в operation_sign. '
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


class OpenAiTranscriptionService:
    def __init__(self, *, api_key, model_name, base_url, language=None, prompt=''):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.language = language
        self.prompt = prompt

    def transcribe(self, *, audio_bytes, audio_mime_type=None, file_name=None):
        if not audio_bytes:
            raise ValueError('Пустое голосовое сообщение.')
        if len(audio_bytes) > TRANSCRIPTION_MAX_BYTES:
            raise ValueError('Голосовое сообщение слишком большое для распознавания.')

        boundary, body = _build_multipart_form_data(
            fields={
                'model': self.model_name,
                'response_format': 'json',
                'language': self.language,
                'prompt': self.prompt,
            },
            files=[
                {
                    'field_name': 'file',
                    'file_name': file_name or _default_audio_filename(audio_mime_type),
                    'content_type': audio_mime_type or 'audio/ogg',
                    'content': audio_bytes,
                }
            ],
        )

        http_request = request.Request(
            self.base_url,
            data=body,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            },
            method='POST',
        )

        try:
            with request.urlopen(http_request, timeout=60) as response:
                raw = json.loads(response.read().decode('utf-8'))
        except error.HTTPError as exc:
            error_body = exc.read().decode('utf-8', errors='ignore')
            raise ValueError(f'OpenAI transcription failed: {error_body or exc.reason}') from exc
        except error.URLError as exc:
            raise ValueError(f'OpenAI transcription failed: {exc.reason}') from exc

        transcript = ((raw or {}).get('text') or '').strip()
        if not transcript:
            raise ValueError('OpenAI transcription response does not contain text.')

        return transcript


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

        meta_intent = _detect_assistant_meta_intent(text)
        if meta_intent is not None:
            return meta_intent

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


def _get_transcription_service():
    api_key = getattr(settings, 'AI_OPENAI_API_KEY', '')
    if not api_key:
        raise ValueError('Голосовые пока недоступны: не настроен AI_OPENAI_API_KEY.')

    return OpenAiTranscriptionService(
        api_key=api_key,
        model_name=getattr(settings, 'AI_OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe'),
        base_url=getattr(
            settings,
            'AI_OPENAI_TRANSCRIBE_BASE_URL',
            'https://api.openai.com/v1/audio/transcriptions',
        ),
        language=getattr(settings, 'AI_OPENAI_TRANSCRIBE_LANGUAGE', 'ru'),
        prompt=getattr(settings, 'AI_OPENAI_TRANSCRIBE_PROMPT', ''),
    )


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
        balance = _wallet_balance(wallet, at_time=at_time)
        if balance == ZERO_AMOUNT:
            continue
        rows.append({
            'wallet_id': str(wallet.id),
            'wallet_name': wallet.name,
            'balance': _serialize_decimal(balance),
        })
    return rows


class AiOperationService:
    def transcribe_audio(self, *, audio_bytes, audio_mime_type=None, file_name=None):
        transcription_service = _get_transcription_service()
        return transcription_service.transcribe(
            audio_bytes=audio_bytes,
            audio_mime_type=audio_mime_type,
            file_name=file_name,
        )

    def detect_meta_intent(self, text):
        return _detect_assistant_meta_intent(text)

    def build_help_result(self, *, provider_name, source='web', include_telegram_link_hint=False):
        lines = [
            'Я умею:',
            '- создавать приход, расход и перевод по тексту;',
            '- показывать остаток по одному кошельку или по всем кошелькам;',
            '- разбирать банковские скриншоты и предлагать документ;',
            '- принимать голосовые сообщения в Telegram и распознавать их как обычный текст;',
            '- задавать уточняющие вопросы, если не хватает суммы, кошелька или статьи.',
            'Примеры:',
            'приход сбер зарплата 15000',
            'расход втб еда 2500',
            'перевод сбер альфа 12000',
            'остатки по кошелькам',
        ]
        if include_telegram_link_hint:
            lines.append('Если Telegram еще не привязан, сгенерируйте код в web API и отправьте команду /link CODE.')
        return {
            'status': 'info',
            'intent': INTENT_HELP_CAPABILITIES,
            'provider': provider_name,
            'confidence': 1.0,
            'reply_text': '\n'.join(lines),
            'parsed': {
                'intent': INTENT_HELP_CAPABILITIES,
                'confidence': 1.0,
                'comment': 'help',
                'raw': {'source': source},
            },
        }

    def build_context(self):
        return {
            'wallets': _wallet_context(),
            'cash_flow_items': _cash_flow_item_context(),
        }

    def _is_batch_provider_payload(self, parsed):
        return isinstance(parsed, dict) and isinstance(parsed.get('operations'), list) and len(parsed.get('operations') or []) > 1

    def _is_batch_normalized(self, normalized):
        return isinstance(normalized, dict) and bool(normalized.get('batch')) and isinstance(normalized.get('items'), list)

    def _batch_intent(self, items):
        intents = [item.get('intent') for item in items if isinstance(item, dict) and item.get('intent')]
        unique_intents = list(dict.fromkeys(intents))
        if len(unique_intents) == 1:
            return unique_intents[0]
        return INTENT_CREATE_MULTIPLE_OPERATIONS

    def _merge_batch_options(self, options_list):
        merged = {}
        index_by_key = {}
        next_index = 1

        for options in options_list:
            if not isinstance(options, dict):
                continue
            for field_name, option_list in options.items():
                if not isinstance(option_list, list):
                    continue
                target = merged.setdefault(field_name, [])
                for option in option_list:
                    if not isinstance(option, dict):
                        continue
                    dedupe_key = (
                        option.get('kind') or field_name,
                        option.get('id') or option.get('label') or option.get('index'),
                    )
                    if dedupe_key in index_by_key:
                        continue
                    normalized_option = dict(option)
                    normalized_option['index'] = next_index
                    target.append(normalized_option)
                    index_by_key[dedupe_key] = next_index
                    next_index += 1

        return merged

    def _normalize_parsed_batch(self, parsed, *, explicit_wallet_id=None, source_text=None, context=None):
        context = context or self.build_context()
        batch_raw = dict(parsed)
        operations = batch_raw.pop('operations', []) or []
        normalized_items = []

        for item_raw in operations:
            if not isinstance(item_raw, dict):
                continue
            merged_raw = dict(batch_raw)
            merged_raw.update(item_raw)
            item_source_text = _collect_fallback_text(
                item_raw.get('comment'),
                item_raw.get('merchant'),
                item_raw.get('description'),
                item_raw.get('bank_name') or batch_raw.get('bank_name'),
                item_raw.get('wallet_hint') or batch_raw.get('wallet_hint'),
                item_raw.get('wallet_from_hint') or batch_raw.get('wallet_from_hint'),
                item_raw.get('wallet_to_hint') or batch_raw.get('wallet_to_hint'),
                item_raw.get('cash_flow_item_hint') or batch_raw.get('cash_flow_item_hint'),
            )
            normalized_items.append(
                self._normalize_parsed(
                    merged_raw,
                    explicit_wallet_id=explicit_wallet_id,
                    source_text=item_source_text or source_text,
                    context=context,
                )
            )

        return {
            'batch': True,
            'intent': self._batch_intent(normalized_items),
            'confidence': float(parsed.get('confidence') or 0.0),
            'items': normalized_items,
            'raw': parsed,
        }

    def serialize_normalized_batch(self, normalized):
        return {
            'batch': True,
            'intent': normalized.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
            'confidence': float(normalized.get('confidence') or 0.0),
            'items': [
                self.serialize_normalized(item)
                for item in normalized.get('items', [])
                if isinstance(item, dict)
            ],
            'raw': normalized.get('raw', {}),
        }

    def deserialize_normalized_batch(self, payload):
        return {
            'batch': True,
            'intent': payload.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
            'confidence': float(payload.get('confidence') or 0.0),
            'items': [
                self.deserialize_normalized(item)
                for item in payload.get('items', [])
                if isinstance(item, dict)
            ],
            'raw': payload.get('raw', {}),
        }

    def apply_confirmation_answer_to_batch(self, *, normalized, answer_text, missing_fields, options_payload=None):
        updated_items = []
        for item in normalized.get('items', []):
            if not isinstance(item, dict):
                continue
            updated_items.append(
                self.apply_confirmation_answer(
                    normalized=item,
                    answer_text=answer_text,
                    missing_fields=missing_fields,
                    options_payload=options_payload,
                )
            )

        return {
            'batch': True,
            'intent': self._batch_intent(updated_items),
            'confidence': float(normalized.get('confidence') or 0.0),
            'items': updated_items,
            'raw': normalized.get('raw', {}),
        }

    def _build_batch_preview(self, item_results):
        previews = [result.get('preview') or {} for result in item_results]
        return {
            'count': len(previews),
            'items': previews,
        }

    def _build_batch_created_reply(self, created_results):
        count = len(created_results)
        lines = [f'Создано документов: {count}.']
        preview_lines = []
        for result in created_results[:10]:
            preview = result.get('preview') or {}
            amount = preview.get('amount') or '0.00'
            comment = preview.get('comment') or 'Без комментария'
            model_name = preview.get('model') or result.get('created_object', {}).get('model') or 'Document'
            preview_lines.append(f'- {model_name}: {amount} | {comment}')
        lines.extend(preview_lines)
        if count > len(preview_lines):
            lines.append(f'И еще {count - len(preview_lines)} документ(ов).')
        return '\n'.join(lines)

    def _build_batch_confirmation_reply(self, count):
        return f'Недостаточно данных для автоматического создания {count} документов.'

    def _create_multiple_financial_documents(self, normalized, *, provider_name, dry_run):
        item_results = [
            self._create_financial_document(item, provider_name=provider_name, dry_run=True)
            for item in normalized.get('items', [])
            if isinstance(item, dict)
        ]

        normalized_items = [result.get('parsed') or {} for result in item_results]
        batch_parsed = {
            'batch': True,
            'intent': self._batch_intent(normalized_items),
            'confidence': float(normalized.get('confidence') or 0.0),
            'items': normalized_items,
            'raw': normalized.get('raw', {}),
        }

        missing_fields = []
        options = []
        for result in item_results:
            if result.get('status') != 'needs_confirmation':
                continue
            for field_name in result.get('missing_fields') or []:
                if field_name not in missing_fields:
                    missing_fields.append(field_name)
            options.append(result.get('options') or {})

        merged_options = self._merge_batch_options(options)
        preview = self._build_batch_preview(item_results)

        if missing_fields:
            return {
                'status': 'needs_confirmation',
                'intent': batch_parsed['intent'],
                'provider': provider_name,
                'confidence': batch_parsed['confidence'],
                'reply_text': self._build_confirmation_reply(
                    self._build_batch_confirmation_reply(len(item_results)),
                    merged_options,
                    missing_fields,
                ),
                'missing_fields': missing_fields,
                'options': merged_options,
                'preview': preview,
                'parsed': batch_parsed,
            }

        if dry_run:
            return {
                'status': 'preview',
                'intent': batch_parsed['intent'],
                'provider': provider_name,
                'confidence': batch_parsed['confidence'],
                'reply_text': f'Распознано {len(item_results)} операций. Документы не созданы, потому что включен dry_run.',
                'preview': preview,
                'parsed': batch_parsed,
            }

        created_results = []
        with transaction.atomic():
            for item in normalized_items:
                created_results.append(
                    self._create_financial_document(item, provider_name=provider_name, dry_run=False)
                )

        created_objects = [result['created_object'] for result in created_results if result.get('created_object')]
        return {
            'status': 'created',
            'intent': batch_parsed['intent'],
            'provider': provider_name,
            'confidence': batch_parsed['confidence'],
            'reply_text': self._build_batch_created_reply(created_results),
            'created_object': created_objects[0] if len(created_objects) == 1 else None,
            'created_objects': created_objects,
            'preview': preview,
            'parsed': batch_parsed,
        }

    def _retry_image_as_batch(self, *, provider, text, image_bytes, image_mime_type, context):
        retry_context = dict(context)
        retry_context['force_all_operations'] = True
        return provider.parse(
            text=text,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            context=retry_context,
        )

    def process(self, *, text=None, image_bytes=None, image_mime_type=None, wallet_id=None, dry_run=False, source='web'):
        context = self.build_context()
        parsed = None
        provider_name = 'rule_based'
        if not image_bytes:
            parsed = self.detect_meta_intent(text)
        if parsed is None:
            provider, provider_name = _get_intent_provider()
            parsed = provider.parse(
                text=text,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                context=context,
            )
            if image_bytes and provider_name != 'rule_based' and not self._is_batch_provider_payload(parsed):
                retry_parsed = self._retry_image_as_batch(
                    provider=provider,
                    text=text,
                    image_bytes=image_bytes,
                    image_mime_type=image_mime_type,
                    context=context,
                )
                if self._is_batch_provider_payload(retry_parsed):
                    parsed = retry_parsed
        if self._is_batch_provider_payload(parsed):
            normalized_batch = self._normalize_parsed_batch(
                parsed,
                explicit_wallet_id=wallet_id,
                source_text=text,
                context=context,
            )
            return self._create_multiple_financial_documents(
                normalized_batch,
                provider_name=provider_name,
                dry_run=dry_run,
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

        if intent == INTENT_HELP_CAPABILITIES:
            return self.build_help_result(provider_name=provider_name, source=source)

        if intent == INTENT_UNKNOWN:
            return self._needs_confirmation(
                normalized,
                provider_name,
                missing_fields=['intent'],
                reply_text='Не удалось уверенно определить команду. Нужна формулировка точнее.',
            )

        return self._create_financial_document(normalized, provider_name=provider_name, dry_run=dry_run)

    def create_from_normalized(self, *, normalized, provider_name):
        if self._is_batch_normalized(normalized):
            return self._create_multiple_financial_documents(normalized, provider_name=provider_name, dry_run=False)
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
        if self._is_batch_normalized(normalized_payload):
            normalized = self.deserialize_normalized_batch(normalized_payload)
            normalized = self.apply_confirmation_answer_to_batch(
                normalized=normalized,
                answer_text=answer_text,
                missing_fields=missing_fields,
                options_payload=options_payload,
            )
            return self._create_multiple_financial_documents(normalized, provider_name=provider_name, dry_run=dry_run)

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

        fallback_text = _collect_fallback_text(
            source_text,
            parsed.get('amount'),
            parsed.get('wallet_hint'),
            parsed.get('wallet_from_hint'),
            parsed.get('wallet_to_hint'),
            parsed.get('cash_flow_item_hint'),
            parsed.get('merchant'),
            parsed.get('bank_name'),
            parsed.get('description'),
            parsed.get('comment'),
        )

        cash_flow_item = _match_cash_flow_item_by_hint(parsed.get('cash_flow_item_hint'))
        if cash_flow_item is None:
            for fallback_hint in (parsed.get('merchant'), parsed.get('description'), parsed.get('comment')):
                cash_flow_item = _match_cash_flow_item_by_hint(fallback_hint)
                if cash_flow_item is not None:
                    break
        if cash_flow_item is None and fallback_text:
            extracted_hint = _extract_cash_flow_item_hint(fallback_text, wallets)
            if extracted_hint:
                cash_flow_item = _match_cash_flow_item_by_hint(extracted_hint)

        wallet_hint = parsed.get('wallet_hint') or parsed.get('bank_name')
        wallet = Wallet.objects.filter(pk=explicit_wallet_id).first() if explicit_wallet_id else None
        if wallet is None:
            wallet = _match_wallet_by_hint(wallet_hint)
        if wallet is None and fallback_text:
            wallet = _match_wallet_by_hint(fallback_text)

        comment_parts = [
            parsed.get('comment'),
            parsed.get('merchant'),
            parsed.get('description'),
        ]
        comment = ' | '.join(part.strip() for part in comment_parts if part and str(part).strip())
        if not comment and source_text:
            comment = source_text.strip()

        amount = _parse_amount(parsed.get('amount'))
        if amount is None:
            amount = _extract_amount_from_text(fallback_text)
        amount = _normalize_operation_amount(
            amount,
            intent=intent,
            operation_sign=operation_sign,
        )

        return {
            'intent': intent,
            'confidence': float(parsed.get('confidence') or 0.0),
            'amount': amount,
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
            return 'Кошельки с ненулевым остатком не найдены.'
        lines = ['Остатки по кошелькам:']
        for row in balances:
            lines.append(f'- {row["wallet_name"]}: {row["balance"]}')
        return '\n'.join(lines)

    def _build_confirmation_reply(self, reply_text, options, missing_fields=None):
        missing_fields = missing_fields or []
        if not options and not missing_fields:
            return reply_text
        lines = [reply_text]
        humanized_missing_fields = {
            'amount': 'сумма',
            'wallet': 'кошелек',
            'cash_flow_item': 'статья движения',
            'wallet_from': 'кошелек списания',
            'wallet_to': 'кошелек зачисления',
            'binding': 'привязка Telegram',
            'intent': 'тип команды',
        }
        if missing_fields:
            labels = [humanized_missing_fields.get(field, field) for field in missing_fields]
            lines.append(f'Не хватает: {", ".join(labels)}.')
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
            'reply_text': self._build_confirmation_reply(reply_text, options, missing_fields),
            'missing_fields': missing_fields,
            'options': options,
            'preview': preview or {},
            'parsed': normalized,
        }
