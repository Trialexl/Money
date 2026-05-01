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

from .models import BudgetExpense, CashFlowItem, Expenditure, FlowOfFunds, Receipt, Transfer, Wallet, ZERO_AMOUNT


INTENT_CREATE_RECEIPT = 'create_receipt'
INTENT_CREATE_EXPENDITURE = 'create_expenditure'
INTENT_CREATE_TRANSFER = 'create_transfer'
INTENT_GET_WALLET_BALANCE = 'get_wallet_balance'
INTENT_GET_ALL_WALLET_BALANCES = 'get_all_wallet_balances'
INTENT_GET_MONTH_EXPENSES_BY_ITEM = 'get_month_expenses_by_item'
INTENT_HELP_CAPABILITIES = 'help_capabilities'
INTENT_UNKNOWN = 'unknown'
INTENT_CREATE_MULTIPLE_OPERATIONS = 'create_multiple_operations'
FINAL_CONFIRMATION_FIELD = 'final_confirmation'
EXPENSE_ACTUAL_DOCUMENT_TYPES = (1, 2, 4)
BUDGET_DOCUMENT_TYPE = 5

SUPPORTED_INTENTS = {
    INTENT_CREATE_RECEIPT,
    INTENT_CREATE_EXPENDITURE,
    INTENT_CREATE_TRANSFER,
    INTENT_GET_WALLET_BALANCE,
    INTENT_GET_ALL_WALLET_BALANCES,
    INTENT_GET_MONTH_EXPENSES_BY_ITEM,
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


def _match_text_variants(value):
    normalized = _normalize_text(value)
    if not normalized:
        return []

    loose = re.sub(r'[^0-9a-zа-я]+', ' ', normalized, flags=re.IGNORECASE)
    loose = re.sub(r'\s+', ' ', loose).strip()
    compact = loose.replace(' ', '')

    variants = []
    for variant in (normalized, loose, compact):
        if variant and variant not in variants:
            variants.append(variant)
    return variants


def _score_hint_against_pattern(hint, pattern):
    best_score = 0
    for hint_variant in _match_text_variants(hint):
        for pattern_variant in _match_text_variants(pattern):
            if hint_variant == pattern_variant:
                best_score = max(best_score, 1000 + len(pattern_variant))
            elif hint_variant.endswith(f' {pattern_variant}') or hint_variant.startswith(f'{pattern_variant} '):
                best_score = max(best_score, 900 + len(pattern_variant))
            elif pattern_variant in hint_variant:
                best_score = max(best_score, 700 + len(pattern_variant))
            elif hint_variant in pattern_variant:
                best_score = max(best_score, 500 + len(hint_variant))
    return best_score


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


def _detect_month_expenses_by_item_intent(text):
    normalized = _normalize_text(text)
    if not normalized:
        return None

    has_expense_word = any(
        token in normalized
        for token in (
            'расходы',
            'траты',
            'затраты',
            'списания',
            'потрачено',
            'потратил',
        )
    )
    has_item_grouping = any(
        token in normalized
        for token in (
            'по статьям',
            'по статья',
            'по категориям',
            'по категория',
            'статьи расходов',
            'категории расходов',
        )
    )
    has_budget_context = 'бюджет' in normalized or 'отклонен' in normalized or 'перерасход' in normalized

    if has_expense_word and (has_item_grouping or has_budget_context):
        return {
            'intent': INTENT_GET_MONTH_EXPENSES_BY_ITEM,
            'confidence': 0.98,
            'comment': text,
        }

    return None


def _serialize_decimal(value):
    if value is None:
        return None
    parsed_value = _parse_amount(value)
    if parsed_value is None:
        return None
    return f'{parsed_value.quantize(Decimal("0.01")):.2f}'


def _is_affirmative_confirmation(text):
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return normalized in {
        'да',
        'ага',
        'ок',
        'okay',
        'ok',
        'yes',
        'подтверждаю',
        'подтвердить',
        'создать',
        'создавай',
        'подтверди',
        '1',
    }


def _contains_batch_exclusion_instruction(text):
    normalized = _normalize_text(text)
    if not normalized:
        return False

    patterns = (
        r'\bне\s+(?:заноси|заносить|вноси|вносить|добавляй|добавлять|создавай|создавать|учитывай|учитывать)\b',
        r'\b(?:исключи|игнорируй|пропусти|убери|удали)\b',
        r'\b(?:не\s+нужно|не\s+надо)\s+(?:заносить|вносить|добавлять|создавать|учитывать)\b',
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def _extract_batch_target_indexes(text):
    normalized = _normalize_text(text)
    if not normalized or not re.search(r'\b(?:строк|операц|пункт|запис)\w*', normalized):
        return []

    indexes = []
    for match in re.finditer(r'(?<!\d)(\d{1,2})(?!\d)', normalized):
        index = int(match.group(1))
        if index not in indexes:
            indexes.append(index)
    return indexes


def _strip_batch_target_instruction(text):
    normalized = _normalize_text(text)
    if not normalized:
        return ''

    cleaned = re.sub(r'\b(?:строк[ауеи]?|операци[яюи]|пункт(?:а|у)?|запис[ьи])\b', ' ', normalized)
    cleaned = re.sub(r'(?<!\d)\d{1,2}(?:[- ]?(?:я|й|ю))?(?!\d)', ' ', cleaned)
    cleaned = re.sub(
        r'\b(?:сделай|сделать|измени|изменить|поменяй|поменять|замени|заменить|'
        r'поставь|поставить|укажи|указать|пусть|будет|это|как)\b',
        ' ',
        cleaned,
    )
    cleaned = re.sub(r'\b(?:в|на|по|статью|статья|категорию|категория)\b', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


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


def _normalize_image_occurred_at(dt, *, raw=None, source_text=None):
    return timezone.now()


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

    candidates = list(Wallet.objects.filter(deleted=False).prefetch_related('aliases'))
    scored_candidates = []
    for wallet in candidates:
        patterns = [wallet.name, wallet.code]
        patterns.extend(alias.alias for alias in wallet.aliases.all())
        score = max((_score_hint_against_pattern(hint, pattern) for pattern in patterns if pattern), default=0)
        if score > 0:
            scored_candidates.append((score, wallet.name, wallet))

    scored_candidates.sort(key=lambda item: (-item[0], item[1]))
    return [wallet for _, _, wallet in scored_candidates[:limit]]


def _match_wallet_by_hint(hint):
    candidates = _wallet_candidates_by_hint(hint)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    top_score = max((_score_hint_against_pattern(hint, pattern) for pattern in [candidates[0].name, candidates[0].code, *[alias.alias for alias in candidates[0].aliases.all()]] if pattern), default=0)
    second_score = max((_score_hint_against_pattern(hint, pattern) for pattern in [candidates[1].name, candidates[1].code, *[alias.alias for alias in candidates[1].aliases.all()]] if pattern), default=0)
    if top_score > second_score:
        return candidates[0]
    return None


def _wallet_confirmation_candidates(hint, limit=6):
    candidates = _wallet_candidates_by_hint(hint, limit=limit)
    if candidates:
        return candidates
    return list(Wallet.objects.filter(deleted=False).order_by('name')[:limit])


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


def _cash_flow_item_confirmation_candidates(hint, limit=6):
    candidates = _cash_flow_item_candidates_by_hint(hint, limit=limit)
    if candidates:
        return candidates
    return list(CashFlowItem.objects.filter(deleted=False).order_by('name')[:limit])


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

        return self._request_json(content)

    def resolve_confirmation(
        self,
        *,
        current_payload,
        missing_fields,
        answer_text,
        context=None,
        options_payload=None,
        confirmation_history=None,
    ):
        prompt = self._build_confirmation_prompt(
            current_payload=current_payload,
            missing_fields=missing_fields,
            answer_text=answer_text,
            context=context or {},
            options_payload=options_payload or {},
            confirmation_history=confirmation_history or [],
        )
        return self._request_json([{'type': 'text', 'text': prompt}])

    def revise_batch_confirmation(
        self,
        *,
        current_payload,
        answer_text,
        context=None,
        options_payload=None,
        confirmation_history=None,
        image_bytes=None,
        image_mime_type=None,
    ):
        prompt = self._build_batch_confirmation_prompt(
            current_payload=current_payload,
            answer_text=answer_text,
            context=context or {},
            options_payload=options_payload or {},
            confirmation_history=confirmation_history or [],
        )
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
        return self._request_json(content)

    def _request_json(self, content):
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
            'get_wallet_balance, get_all_wallet_balances, get_month_expenses_by_item, '
            'help_capabilities, unknown. '
            'Если передано изображение, считай, что это банковский скриншот операции или истории операций, '
            f'{image_instruction}'
            'Если на изображении список или история операций, выбери одну самую вероятную строку операции: '
            'обычно верхнюю или последнюю видимую покупку с суммой, торговой точкой и датой. '
            'Игнорируй кнопки интерфейса, баннеры, баланс, поисковую строку и декоративные элементы. '
            'Категорию операции вроде "Продукты", "Транспорт", "Фастфуд" используй как description или cash_flow_item_hint. '
            'Если на изображении видно несколько денежных операций, верни их все в массиве operations. '
            'Каждый элемент operations должен описывать одну денежную операцию. '
            'Если текст пользователя содержит указания по строкам списка, например "3 пропусти", "2 продукты", '
            '"1 не заноси", примени их сразу при формировании итогового массива operations. '
            'Для каждой операции из списка укажи source_index: номер строки на исходном скриншоте сверху вниз, начиная с 1. '
            'Если строка была исключена по указанию пользователя, просто не включай ее в operations. '
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
            'Если пользователь спрашивает расходы, траты или списания текущего месяца по статьям/категориям '
            'или просит отклонение от бюджета, верни intent=get_month_expenses_by_item. '
            'Если уверенности нет, ставь intent=unknown или оставляй поля null. '
            'Схема JSON: '
            '{"intent": "...", "confidence": 0.0, "amount": "0.00" | null, '
            '"wallet_hint": null, "wallet_from_hint": null, "wallet_to_hint": null, '
            '"cash_flow_item_hint": null, "merchant": null, "bank_name": null, '
            '"description": null, "occurred_at": null, "operation_sign": null, '
            '"comment": null, "include_in_budget": false, '
            '"operations": [{"source_index": 1, "intent": "...", "amount": "0.00", "merchant": "..."}] | null}. '
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

    def _build_confirmation_prompt(
        self,
        *,
        current_payload,
        missing_fields,
        answer_text,
        context,
        options_payload,
        confirmation_history,
    ):
        return (
            'Ты уточняешь недостающие поля уже распознанной финансовой операции. '
            'Верни только JSON без пояснений. '
            'Не создавай новую операцию и не переписывай уже заполненные поля без необходимости. '
            'Используй ответ пользователя, историю предыдущих ответов и текущую структуру операции. '
            'Если нужно выбрать кошелек или статью, выбирай только из переданных справочников. '
            'Если уверен в выборе сущности, возвращай именно *_id. '
            'Если уверенности нет, оставляй поле null. '
            'Схема JSON: '
            '{"intent": null, "amount": null, "wallet_id": null, "wallet_from_id": null, '
            '"wallet_to_id": null, "cash_flow_item_id": null, "wallet_hint": null, '
            '"wallet_from_hint": null, "wallet_to_hint": null, "cash_flow_item_hint": null, "comment": null}. '
            'Для ответов с опечатками или лишними словами всё равно попытайся выбрать наиболее вероятный кошелек/статью '
            'из справочника. '
            f'Текущая структура: {json.dumps(current_payload or {}, ensure_ascii=False)}. '
            f'Не хватает полей: {json.dumps(missing_fields or [], ensure_ascii=False)}. '
            f'История ответов пользователя: {json.dumps(confirmation_history or [], ensure_ascii=False)}. '
            f'Текущий ответ пользователя: {answer_text or ""}. '
            f'Подсказки-варианты: {json.dumps(options_payload or {}, ensure_ascii=False)}. '
            f'Доступные кошельки: {json.dumps(context.get("wallets", []), ensure_ascii=False)}. '
            f'Доступные статьи: {json.dumps(context.get("cash_flow_items", []), ensure_ascii=False)}.'
        )

    def _build_batch_confirmation_prompt(
        self,
        *,
        current_payload,
        answer_text,
        context,
        options_payload,
        confirmation_history,
    ):
        return (
            'Ты уточняешь список финансовых операций, ранее распознанных с одного скриншота. '
            'Верни только JSON без пояснений. '
            'Перечитай изображение и текстовые указания пользователя, затем верни полный актуальный список операций, '
            'которые нужно создать после этого ответа пользователя. '
            'Не возвращай patch, команды update/exclude или diff. Возвращай только итоговый список операций целиком. '
            'Если пользователь просит пропустить строку, просто не включай ее в operations. '
            'Если пользователь уточняет статью или кошелек для конкретной строки, примени это только к нужной строке. '
            'Если пользователь уточняет кошелек или статью без номера строки, примени уточнение ко всем строкам, '
            'для которых это подходит и которые еще не заполнены. '
            'Сохраняй исходные номера строк source_index из текущего черновика. Не перенумеровывай. '
            'Используй только доступные кошельки и статьи из справочников. '
            'Если уверен, возвращай wallet_id / wallet_from_id / wallet_to_id / cash_flow_item_id. '
            'Если id определить нельзя, верни соответствующий hint по точному имени из справочника. '
            'Если какое-то поле после ответа пользователя все еще неизвестно, оставь его null. '
            'Схема JSON: '
            '{"intent":"create_multiple_operations","confidence":0.0,"operations":['
            '{"source_index":1,"intent":"create_expenditure","amount":"0.00","wallet_id":null,'
            '"wallet_hint":null,"wallet_from_id":null,"wallet_from_hint":null,'
            '"wallet_to_id":null,"wallet_to_hint":null,"cash_flow_item_id":null,'
            '"cash_flow_item_hint":null,"merchant":null,"bank_name":null,"description":null,'
            '"occurred_at":null,"operation_sign":null,"comment":null,"include_in_budget":false}'
            ']}. '
            'Не добавляй новых строк, которых нет на скриншоте. '
            'Текущий черновик операций: '
            f'{json.dumps(current_payload or {}, ensure_ascii=False)}. '
            'История ответов пользователя: '
            f'{json.dumps(confirmation_history or [], ensure_ascii=False)}. '
            'Текущий ответ пользователя: '
            f'{answer_text or ""}. '
            'Подсказки-варианты: '
            f'{json.dumps(options_payload or {}, ensure_ascii=False)}. '
            'Доступные кошельки: '
            f'{json.dumps(context.get("wallets", []), ensure_ascii=False)}. '
            'Доступные статьи: '
            f'{json.dumps(context.get("cash_flow_items", []), ensure_ascii=False)}.'
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

        month_expenses_intent = _detect_month_expenses_by_item_intent(text)
        if month_expenses_intent is not None:
            return month_expenses_intent

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

    def resolve_confirmation(
        self,
        *,
        current_payload,
        missing_fields,
        answer_text,
        context=None,
        options_payload=None,
        confirmation_history=None,
    ):
        return {}

    def revise_batch_confirmation(
        self,
        *,
        current_payload,
        answer_text,
        context=None,
        options_payload=None,
        confirmation_history=None,
        image_bytes=None,
        image_mime_type=None,
    ):
        return None


def _get_intent_provider(provider_name=None):
    provider_name = provider_name or getattr(settings, 'AI_DEFAULT_PROVIDER', 'openrouter')
    if provider_name == 'rule_based':
        return RuleBasedIntentProvider(), provider_name

    if provider_name in {'openrouter', 'gemini'}:
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


def _current_month_bounds(*, at_time=None):
    selected_at = timezone.localtime(at_time or timezone.now())
    month_start = selected_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    return month_start, next_month_start


def _format_month_label(month_start):
    month_names = {
        1: 'январь',
        2: 'февраль',
        3: 'март',
        4: 'апрель',
        5: 'май',
        6: 'июнь',
        7: 'июль',
        8: 'август',
        9: 'сентябрь',
        10: 'октябрь',
        11: 'ноябрь',
        12: 'декабрь',
    }
    return f'{month_names.get(month_start.month, month_start.strftime("%m"))} {month_start.year}'


def _month_expenses_by_item(*, at_time=None):
    month_start, next_month_start = _current_month_bounds(at_time=at_time)
    base_queryset = BudgetExpense.objects.filter(
        period__gte=month_start,
        period__lt=next_month_start,
        project__isnull=True,
        cash_flow_item__isnull=False,
    )
    actual_totals = {
        row['cash_flow_item_id']: {
            'cash_flow_item_id': str(row['cash_flow_item_id']),
            'cash_flow_item_name': row['cash_flow_item__name'] or 'Без статьи',
            'actual': (row['actual'] or ZERO_AMOUNT).quantize(Decimal('0.01')),
        }
        for row in base_queryset.filter(type_of_document__in=EXPENSE_ACTUAL_DOCUMENT_TYPES)
        .values('cash_flow_item_id', 'cash_flow_item__name')
        .annotate(actual=Sum('amount'))
    }
    budget_totals = {
        row['cash_flow_item_id']: (row['planned'] or ZERO_AMOUNT).quantize(Decimal('0.01'))
        for row in base_queryset.filter(type_of_document=BUDGET_DOCUMENT_TYPE)
        .values('cash_flow_item_id')
        .annotate(planned=Sum('amount'))
    }

    rows = []
    total_actual = ZERO_AMOUNT
    total_budget = ZERO_AMOUNT
    for item_id, row in actual_totals.items():
        actual = row['actual']
        planned = budget_totals.get(item_id)
        total_actual += actual
        if planned is not None:
            total_budget += planned
        deviation = actual - planned if planned is not None else None
        rows.append({
            'cash_flow_item_id': row['cash_flow_item_id'],
            'cash_flow_item_name': row['cash_flow_item_name'],
            'actual': _serialize_decimal(actual),
            'budget': _serialize_decimal(planned) if planned is not None and planned > ZERO_AMOUNT else None,
            'deviation': _serialize_decimal(deviation) if deviation is not None else None,
            'overrun': _serialize_decimal(max(deviation, ZERO_AMOUNT)) if deviation is not None else None,
            'remaining': _serialize_decimal(max(planned - actual, ZERO_AMOUNT)) if planned is not None else None,
        })

    rows.sort(key=lambda item: (-Decimal(item['actual']), item['cash_flow_item_name']))
    total_deviation = total_actual - total_budget if total_budget > ZERO_AMOUNT else None
    return {
        'period_start': month_start.isoformat(),
        'period_end': next_month_start.isoformat(),
        'period_label': _format_month_label(month_start),
        'items': rows,
        'total_actual': _serialize_decimal(total_actual),
        'total_budget': _serialize_decimal(total_budget) if total_budget > ZERO_AMOUNT else None,
        'total_deviation': _serialize_decimal(total_deviation) if total_deviation is not None else None,
        'total_overrun': _serialize_decimal(max(total_deviation, ZERO_AMOUNT)) if total_deviation is not None else None,
        'total_remaining': _serialize_decimal(max(total_budget - total_actual, ZERO_AMOUNT)) if total_deviation is not None else None,
    }


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
            '- показывать расходы текущего месяца по статьям и отклонение от бюджета;',
            '- разбирать банковские скриншоты и предлагать документ;',
            '- принимать голосовые сообщения в Telegram и распознавать их как обычный текст;',
            '- задавать уточняющие вопросы, если не хватает суммы, кошелька или статьи.',
            'Примеры:',
            'приход сбер зарплата 15000',
            'расход втб еда 2500',
            'перевод сбер альфа 12000',
            'остатки по кошелькам',
            'расходы по статьям',
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

    def _normalize_parsed_batch(self, parsed, *, explicit_wallet_id=None, source_text=None, context=None, image_based=False):
        context = context or self.build_context()
        batch_raw = dict(parsed)
        operations = batch_raw.pop('operations', []) or []
        normalized_items = []

        for fallback_index, item_raw in enumerate(operations, start=1):
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
                    image_based=image_based,
                )
            )
            normalized_items[-1]['source_index'] = int(item_raw.get('source_index') or fallback_index)

        return {
            'batch': True,
            'intent': self._batch_intent(normalized_items),
            'confidence': float(parsed.get('confidence') or 0.0),
            'image_based': bool(image_based),
            'items': normalized_items,
            'raw': parsed,
        }

    def serialize_normalized_batch(self, normalized):
        return {
            'batch': True,
            'intent': normalized.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
            'confidence': float(normalized.get('confidence') or 0.0),
            'image_based': bool(normalized.get('image_based')),
            'items': [
                self.serialize_normalized(item)
                for item in normalized.get('items', [])
                if isinstance(item, dict)
            ],
            'raw': normalized.get('raw', {}),
        }

    def _resolve_confirmation_with_provider(
        self,
        *,
        normalized_payload,
        missing_fields,
        answer_text,
        provider_name,
        options_payload=None,
        confirmation_history=None,
    ):
        provider, actual_provider_name = _get_intent_provider(
            provider_name if provider_name in {'openrouter', 'gemini', 'rule_based'} else None
        )
        if actual_provider_name == 'rule_based':
            return {}

        try:
            patch = provider.resolve_confirmation(
                current_payload=normalized_payload,
                missing_fields=missing_fields,
                answer_text=answer_text,
                context=self.build_context(),
                options_payload=options_payload or {},
                confirmation_history=confirmation_history or [],
            )
        except Exception:
            return {}

        return patch if isinstance(patch, dict) else {}

    def _decode_pending_image_context(self, pending_context):
        if not isinstance(pending_context, dict):
            return None, None, ''

        image_base64 = pending_context.get('image_base64') or ''
        if not image_base64:
            return None, None, pending_context.get('source_text', '') or ''

        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception:
            return None, None, pending_context.get('source_text', '') or ''

        return (
            image_bytes,
            pending_context.get('image_mime_type') or 'image/jpeg',
            pending_context.get('source_text', '') or '',
        )

    def _resolve_batch_confirmation_with_provider(
        self,
        *,
        normalized_payload,
        answer_text,
        provider_name,
        options_payload=None,
        confirmation_history=None,
        pending_context=None,
    ):
        image_bytes, image_mime_type, source_text = self._decode_pending_image_context(pending_context)
        if not image_bytes:
            return None

        provider, actual_provider_name = _get_intent_provider(
            provider_name if provider_name in {'openrouter', 'gemini', 'rule_based'} else None
        )
        if actual_provider_name == 'rule_based':
            return None

        try:
            revised = provider.revise_batch_confirmation(
                current_payload=normalized_payload,
                answer_text=answer_text,
                context=self.build_context(),
                options_payload=options_payload or {},
                confirmation_history=confirmation_history or [],
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
        except Exception:
            return None

        if not isinstance(revised, dict) or not isinstance(revised.get('operations'), list):
            return None

        normalized = self._normalize_parsed_batch(
            revised,
            source_text=source_text,
            context=self.build_context(),
            image_based=True,
        )
        return {
            'provider_name': actual_provider_name,
            'normalized': normalized,
        }

    def apply_confirmation_patch(self, *, normalized, patch):
        updated = dict(normalized)
        raw = dict(updated.get('raw') or {})

        if patch.get('intent'):
            updated['intent'] = patch.get('intent')
            raw['intent'] = patch.get('intent')

        patch_amount = _parse_amount(patch.get('amount'))
        if patch_amount is not None:
            updated['amount'] = patch_amount

        wallet = None
        if patch.get('wallet_id'):
            wallet = Wallet.objects.filter(pk=patch.get('wallet_id')).first()
        elif patch.get('wallet_hint'):
            wallet = _match_wallet_by_hint(patch.get('wallet_hint'))
            raw['wallet_hint'] = patch.get('wallet_hint')
        if wallet is not None:
            updated['wallet'] = wallet

        wallet_from = None
        if patch.get('wallet_from_id'):
            wallet_from = Wallet.objects.filter(pk=patch.get('wallet_from_id')).first()
        elif patch.get('wallet_from_hint'):
            wallet_from = _match_wallet_by_hint(patch.get('wallet_from_hint'))
            raw['wallet_from_hint'] = patch.get('wallet_from_hint')
        if wallet_from is not None:
            updated['wallet_from'] = wallet_from

        wallet_to = None
        if patch.get('wallet_to_id'):
            wallet_to = Wallet.objects.filter(pk=patch.get('wallet_to_id')).first()
        elif patch.get('wallet_to_hint'):
            wallet_to = _match_wallet_by_hint(patch.get('wallet_to_hint'))
            raw['wallet_to_hint'] = patch.get('wallet_to_hint')
        if wallet_to is not None:
            updated['wallet_to'] = wallet_to

        cash_flow_item = None
        if patch.get('cash_flow_item_id'):
            cash_flow_item = CashFlowItem.objects.filter(pk=patch.get('cash_flow_item_id')).first()
        elif patch.get('cash_flow_item_hint'):
            cash_flow_item = _match_cash_flow_item_by_hint(patch.get('cash_flow_item_hint'))
            raw['cash_flow_item_hint'] = patch.get('cash_flow_item_hint')
        if cash_flow_item is not None:
            updated['cash_flow_item'] = cash_flow_item

        if patch.get('comment'):
            updated['comment'] = patch.get('comment')

        updated['raw'] = raw
        return updated

    def apply_confirmation_patch_to_batch(self, *, normalized, patch):
        return {
            'batch': True,
            'intent': normalized.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
            'confidence': float(normalized.get('confidence') or 0.0),
            'image_based': bool(normalized.get('image_based')),
            'items': [
                self.apply_confirmation_patch(normalized=item, patch=patch)
                for item in normalized.get('items', [])
                if isinstance(item, dict)
            ],
            'raw': normalized.get('raw', {}),
        }

    def _extract_batch_item_patch_directives(self, *, answer_text, wallets):
        segments = [segment.strip() for segment in re.split(r'[\r\n]+', answer_text or '') if segment.strip()]
        if not segments:
            return [], answer_text or ''

        directives = []
        remaining_segments = []
        for segment in segments:
            indexes = _extract_batch_target_indexes(segment)
            if not indexes or _contains_batch_exclusion_instruction(segment):
                remaining_segments.append(segment)
                continue

            hint = _strip_batch_target_instruction(segment)
            if not hint:
                remaining_segments.append(segment)
                continue

            cash_flow_item = _match_cash_flow_item_by_hint(hint)
            if cash_flow_item is None:
                extracted_hint = _extract_cash_flow_item_hint(hint, wallets)
                if extracted_hint:
                    cash_flow_item = _match_cash_flow_item_by_hint(extracted_hint)
                    if cash_flow_item is not None:
                        hint = extracted_hint

            if cash_flow_item is None:
                remaining_segments.append(segment)
                continue

            directives.append({
                'indexes': indexes,
                'patch': {
                    'cash_flow_item_id': str(cash_flow_item.id),
                    'cash_flow_item_hint': hint,
                },
            })

            preserved_tokens = []
            for wallet_name in _wallet_mentions(segment, wallets):
                if wallet_name not in preserved_tokens:
                    preserved_tokens.append(wallet_name)
            if preserved_tokens:
                remaining_segments.append(' '.join(preserved_tokens))

        return directives, '\n'.join(remaining_segments)

    def apply_batch_item_patch_directives(self, *, normalized, directives):
        if not directives:
            return normalized

        updated_items = []
        for index, item in enumerate(normalized.get('items', []), start=1):
            if not isinstance(item, dict):
                continue
            updated_item = item
            for directive in directives:
                if index in directive.get('indexes', []):
                    updated_item = self.apply_confirmation_patch(
                        normalized=updated_item,
                        patch=directive.get('patch') or {},
                    )
            updated_items.append(updated_item)

        return {
            'batch': True,
            'intent': self._batch_intent(updated_items),
            'confidence': float(normalized.get('confidence') or 0.0),
            'image_based': bool(normalized.get('image_based')),
            'items': updated_items,
            'raw': normalized.get('raw', {}),
        }

    def _batch_exclusion_score(self, *, answer_text, item, index):
        normalized_answer = _normalize_text(answer_text)
        if not normalized_answer:
            return 0

        score = 0

        index_matches = {
            int(match)
            for match in re.findall(r'(?<!\d)(\d{1,2})(?!\d)', normalized_answer)
        }
        if index in index_matches:
            score = max(score, 1000)

        intent_aliases = {
            INTENT_CREATE_RECEIPT: ('приход', 'доход', 'поступление'),
            INTENT_CREATE_EXPENDITURE: ('расход', 'трата', 'покупка', 'списание'),
            INTENT_CREATE_TRANSFER: ('перевод', 'сбп', 'между счетами', 'между кошельками'),
        }
        for alias in intent_aliases.get(item.get('intent'), ()):
            if _score_hint_against_pattern(normalized_answer, alias) >= 700:
                score = max(score, 900 + len(alias))

        parsed_amount = _extract_amount_from_text(answer_text)
        item_amount = item.get('amount')
        if parsed_amount is not None and item_amount is not None and abs(parsed_amount) == abs(item_amount):
            score = max(score, 850)

        raw = item.get('raw') or {}
        text_hints = [
            raw.get('merchant'),
            raw.get('description'),
            raw.get('comment'),
            raw.get('bank_name'),
            getattr(item.get('cash_flow_item'), 'name', None),
            getattr(item.get('wallet'), 'name', None),
            getattr(item.get('wallet_from'), 'name', None),
            getattr(item.get('wallet_to'), 'name', None),
        ]
        for hint in text_hints:
            if not hint:
                continue
            hint_score = _score_hint_against_pattern(normalized_answer, hint)
            if hint_score >= 700:
                score = max(score, 700 + min(len(_normalize_text(hint)), 50))

        return score

    def apply_batch_answer_directives(self, *, normalized, answer_text):
        if not self._is_batch_normalized(normalized) or not _contains_batch_exclusion_instruction(answer_text):
            return normalized, []

        items = [
            item for item in normalized.get('items', [])
            if isinstance(item, dict)
        ]
        if not items:
            return normalized, []

        scored_items = []
        for index, item in enumerate(items, start=1):
            score = self._batch_exclusion_score(answer_text=answer_text, item=item, index=index)
            if score > 0:
                scored_items.append((index, score))

        if not scored_items:
            return normalized, []

        max_score = max(score for _, score in scored_items)
        excluded_indexes = [
            index for index, score in scored_items
            if score == max_score
        ]
        if not excluded_indexes:
            return normalized, []

        updated_items = [
            item for index, item in enumerate(items, start=1)
            if index not in excluded_indexes
        ]
        updated = dict(normalized)
        updated['items'] = updated_items
        updated['intent'] = self._batch_intent(updated_items)
        return updated, excluded_indexes

    def _build_empty_batch_result(self, *, provider_name, normalized, excluded_indexes):
        excluded_count = len(excluded_indexes)
        return {
            'status': 'info',
            'intent': normalized.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
            'provider': provider_name,
            'confidence': float(normalized.get('confidence') or 0.0),
            'reply_text': (
                f'Исключил {excluded_count} операцию. Нечего создавать.'
                if excluded_count == 1
                else f'Исключил {excluded_count} операций. Нечего создавать.'
            ),
            'parsed': normalized,
        }

    def _build_preview_for_item(self, normalized):
        intent = normalized.get('intent')
        amount = normalized.get('amount')
        preview = {
            'model': {
                INTENT_CREATE_RECEIPT: 'Receipt',
                INTENT_CREATE_EXPENDITURE: 'Expenditure',
                INTENT_CREATE_TRANSFER: 'Transfer',
            }.get(intent, 'Document'),
            'amount': _serialize_decimal(amount),
            'comment': normalized.get('comment', ''),
            'date': normalized.get('occurred_at').isoformat() if normalized.get('occurred_at') else None,
            'source_index': normalized.get('source_index'),
        }
        if normalized.get('wallet'):
            preview['wallet_name'] = normalized['wallet'].name
        if normalized.get('wallet_from'):
            preview['wallet_out_name'] = normalized['wallet_from'].name
        if normalized.get('wallet_to'):
            preview['wallet_in_name'] = normalized['wallet_to'].name
        if normalized.get('cash_flow_item'):
            preview['cash_flow_item_name'] = normalized['cash_flow_item'].name
        return preview

    def _build_final_confirmation_reply(self, preview):
        lines = ['Проверь, что будет создано:']
        if preview.get('count') and isinstance(preview.get('items'), list):
            for fallback_index, item in enumerate(preview.get('items') or [], start=1):
                lines.append(
                    self._build_final_confirmation_line(
                        item,
                        index=item.get('source_index') or fallback_index,
                    )
                )
        else:
            lines.append(self._build_final_confirmation_line(preview))
        lines.append('Если всё верно, ответь: да или создать.')
        lines.append('Если нужно исправить данные или исключить операцию, напиши уточнение или /cancel.')
        return '\n'.join(lines)

    def _build_final_confirmation_line(self, item, *, index=None):
        parts = []
        model_name = (item or {}).get('model') or 'Document'
        amount = (item or {}).get('amount') or '0.00'
        operation_icon = {
            'Receipt': '🟢',
            'Expenditure': '🔴',
            'Transfer': '🔄',
        }.get(model_name, '•')
        parts.append(f'{operation_icon} {amount}')
        if item.get('wallet_name'):
            parts.append(f'👛 {item["wallet_name"]}')
        if item.get('wallet_out_name') and item.get('wallet_in_name'):
            parts.append(f'👛 {item["wallet_out_name"]} -> {item["wallet_in_name"]}')
        if item.get('cash_flow_item_name'):
            parts.append(f'🏷 {item["cash_flow_item_name"]}')
        prefix = f'{index}. ' if index is not None else '- '
        return prefix + ' | '.join(parts)

    def _final_confirmation_result(self, *, parsed, provider_name, preview, confidence):
        return {
            'status': 'needs_confirmation',
            'intent': parsed.get('intent', INTENT_UNKNOWN),
            'provider': provider_name,
            'confidence': confidence,
            'reply_text': self._build_final_confirmation_reply(preview or {}),
            'missing_fields': [FINAL_CONFIRMATION_FIELD],
            'options': {},
            'preview': preview or {},
            'parsed': parsed,
        }

    def deserialize_normalized_batch(self, payload):
        return {
            'batch': True,
            'intent': payload.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
            'confidence': float(payload.get('confidence') or 0.0),
            'image_based': bool(payload.get('image_based')),
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
            'image_based': bool(normalized.get('image_based')),
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
            preview = result.get('preview') or self._build_preview_for_item(result.get('parsed') or {})
            amount = preview.get('amount') or '0.00'
            comment = preview.get('comment') or 'Без комментария'
            preview_lines.append(self._build_final_confirmation_line(preview))
        lines.extend(preview_lines)
        if count > len(preview_lines):
            lines.append(f'И еще {count - len(preview_lines)} документ(ов).')
        return '\n'.join(lines)

    def _build_batch_confirmation_reply(self, count):
        return f'Недостаточно данных для автоматического создания {count} документов.'

    def _humanize_missing_field(self, field_name):
        return {
            'amount': 'сумма',
            'wallet': 'кошелек',
            'cash_flow_item': 'статья движения',
            'wallet_from': 'кошелек списания',
            'wallet_to': 'кошелек зачисления',
            FINAL_CONFIRMATION_FIELD: 'подтверждение создания',
            'binding': 'привязка Telegram',
            'intent': 'тип команды',
        }.get(field_name, field_name)

    def _build_batch_missing_fields_by_item(self, item_results):
        details = []
        for fallback_index, result in enumerate(item_results, start=1):
            if result.get('status') != 'needs_confirmation':
                continue
            item_missing_fields = result.get('missing_fields') or []
            if not item_missing_fields:
                continue
            parsed = result.get('parsed') or {}
            details.append({
                'index': parsed.get('source_index') or fallback_index,
                'missing_fields': item_missing_fields,
            })
        return details

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
            'image_based': bool(normalized.get('image_based')),
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

        missing_fields_by_item = self._build_batch_missing_fields_by_item(item_results)
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
                    missing_fields_by_item=missing_fields_by_item,
                ),
                'missing_fields': missing_fields,
                'missing_fields_by_item': missing_fields_by_item,
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
        if parsed is None and not image_bytes:
            parsed = _detect_month_expenses_by_item_intent(text)
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
                image_based=bool(image_bytes),
            )
            batch_directives, batch_answer_text = self._extract_batch_item_patch_directives(
                answer_text=text,
                wallets=context.get('wallets', []),
            )
            normalized_batch = self.apply_batch_item_patch_directives(
                normalized=normalized_batch,
                directives=batch_directives,
            )
            normalized_batch, excluded_indexes = self.apply_batch_answer_directives(
                normalized=normalized_batch,
                answer_text=batch_answer_text,
            )
            if not normalized_batch.get('items'):
                return self._build_empty_batch_result(
                    provider_name=provider_name,
                    normalized=normalized_batch,
                    excluded_indexes=excluded_indexes,
                )
            result = self._create_multiple_financial_documents(
                normalized_batch,
                provider_name=provider_name,
                dry_run=dry_run,
            )
            if source == 'telegram' and bool(image_bytes) and dry_run and result.get('status') == 'preview':
                return self._final_confirmation_result(
                    parsed=result['parsed'],
                    provider_name=provider_name,
                    preview=result.get('preview') or {},
                    confidence=float(result.get('confidence') or 0.0),
                )
            return result
        normalized = self._normalize_parsed(
            parsed,
            explicit_wallet_id=wallet_id,
            source_text=text,
            context=context,
            image_based=bool(image_bytes),
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

        if intent == INTENT_GET_MONTH_EXPENSES_BY_ITEM:
            summary = _month_expenses_by_item(at_time=timezone.now())
            return {
                'status': 'info',
                'intent': intent,
                'provider': provider_name,
                'confidence': normalized['confidence'],
                'reply_text': self._build_month_expenses_by_item_reply(summary),
                'expense_summary': summary,
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

        result = self._create_financial_document(normalized, provider_name=provider_name, dry_run=dry_run)
        if source == 'telegram' and bool(image_bytes) and dry_run and result.get('status') == 'preview':
            return self._final_confirmation_result(
                parsed=result['parsed'],
                provider_name=provider_name,
                preview=result.get('preview') or {},
                confidence=float(result.get('confidence') or 0.0),
            )
        return result

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
        confirmation_history=None,
        pending_context=None,
        source='web',
    ):
        if missing_fields == [FINAL_CONFIRMATION_FIELD]:
            if self._is_batch_normalized(normalized_payload):
                if not _is_affirmative_confirmation(answer_text):
                    revised = self._resolve_batch_confirmation_with_provider(
                        normalized_payload=normalized_payload,
                        answer_text=answer_text,
                        provider_name=provider_name,
                        options_payload=options_payload,
                        confirmation_history=confirmation_history,
                        pending_context=pending_context,
                    )
                    if revised:
                        result = self._create_multiple_financial_documents(
                            revised['normalized'],
                            provider_name=revised['provider_name'],
                            dry_run=dry_run,
                        )
                        if source == 'telegram' and revised['normalized'].get('image_based') and dry_run and result.get('status') == 'preview':
                            return self._final_confirmation_result(
                                parsed=result['parsed'],
                                provider_name=revised['provider_name'],
                                preview=result.get('preview') or {},
                                confidence=float(result.get('confidence') or 0.0),
                            )
                        return result

                normalized = self.deserialize_normalized_batch(normalized_payload)
                batch_directives, batch_answer_text = self._extract_batch_item_patch_directives(
                    answer_text=answer_text,
                    wallets=self.build_context()['wallets'],
                )
                normalized = self.apply_batch_item_patch_directives(
                    normalized=normalized,
                    directives=batch_directives,
                )
                normalized, excluded_indexes = self.apply_batch_answer_directives(
                    normalized=normalized,
                    answer_text=batch_answer_text,
                )
                if batch_directives or excluded_indexes:
                    if not normalized.get('items'):
                        return self._build_empty_batch_result(
                            provider_name=provider_name,
                            normalized=normalized,
                            excluded_indexes=excluded_indexes,
                        )
                    return self._final_confirmation_result(
                        parsed=normalized,
                        provider_name=provider_name,
                        preview=self._build_batch_preview([
                            {'preview': self._build_preview_for_item(item)}
                            for item in normalized.get('items', [])
                            if isinstance(item, dict)
                        ]),
                        confidence=float(normalized.get('confidence') or 0.0),
                    )

            if _is_affirmative_confirmation(answer_text):
                if self._is_batch_normalized(normalized_payload):
                    normalized = self.deserialize_normalized_batch(normalized_payload)
                    return {
                        'status': 'preview',
                        'intent': normalized.get('intent', INTENT_CREATE_MULTIPLE_OPERATIONS),
                        'provider': provider_name,
                        'confidence': float(normalized.get('confidence') or 0.0),
                        'reply_text': 'Подтверждение получено. Создаю документы.',
                        'preview': self._build_batch_preview([
                            {'preview': self._build_preview_for_item(item)}
                            for item in normalized.get('items', [])
                            if isinstance(item, dict)
                        ]),
                        'parsed': normalized,
                    }
                normalized = self.deserialize_normalized(normalized_payload)
                return {
                    'status': 'preview',
                    'intent': normalized.get('intent', INTENT_UNKNOWN),
                    'provider': provider_name,
                    'confidence': float(normalized.get('confidence') or 0.0),
                    'reply_text': 'Подтверждение получено. Создаю документ.',
                    'preview': self._build_preview_for_item(normalized),
                    'parsed': normalized,
                }

            if self._is_batch_normalized(normalized_payload):
                normalized = self.deserialize_normalized_batch(normalized_payload)
                return self._final_confirmation_result(
                    parsed=normalized,
                    provider_name=provider_name,
                    preview=self._build_batch_preview([
                        {'preview': self._build_preview_for_item(item)}
                        for item in normalized.get('items', [])
                        if isinstance(item, dict)
                    ]),
                    confidence=float(normalized.get('confidence') or 0.0),
                )

            normalized = self.deserialize_normalized(normalized_payload)
            return self._final_confirmation_result(
                parsed=normalized,
                provider_name=provider_name,
                preview=self._build_preview_for_item(normalized),
                confidence=float(normalized.get('confidence') or 0.0),
            )

        if self._is_batch_normalized(normalized_payload):
            revised = self._resolve_batch_confirmation_with_provider(
                normalized_payload=normalized_payload,
                answer_text=answer_text,
                provider_name=provider_name,
                options_payload=options_payload,
                confirmation_history=confirmation_history,
                pending_context=pending_context,
            )
            if revised:
                result = self._create_multiple_financial_documents(
                    revised['normalized'],
                    provider_name=revised['provider_name'],
                    dry_run=dry_run,
                )
                if source == 'telegram' and revised['normalized'].get('image_based') and dry_run and result.get('status') == 'preview':
                    return self._final_confirmation_result(
                        parsed=result['parsed'],
                        provider_name=revised['provider_name'],
                        preview=result.get('preview') or {},
                        confidence=float(result.get('confidence') or 0.0),
                    )
                return result

            normalized = self.deserialize_normalized_batch(normalized_payload)
            batch_directives, batch_answer_text = self._extract_batch_item_patch_directives(
                answer_text=answer_text,
                wallets=self.build_context()['wallets'],
            )
            normalized = self.apply_batch_item_patch_directives(
                normalized=normalized,
                directives=batch_directives,
            )
            normalized, excluded_indexes = self.apply_batch_answer_directives(
                normalized=normalized,
                answer_text=batch_answer_text,
            )
            if not normalized.get('items'):
                return self._build_empty_batch_result(
                    provider_name=provider_name,
                    normalized=normalized,
                    excluded_indexes=excluded_indexes,
                )
            patch = self._resolve_confirmation_with_provider(
                normalized_payload=self.serialize_normalized_batch(normalized),
                missing_fields=missing_fields,
                answer_text=batch_answer_text,
                provider_name=provider_name,
                options_payload=options_payload,
                confirmation_history=confirmation_history,
            )
            if patch:
                normalized = self.apply_confirmation_patch_to_batch(normalized=normalized, patch=patch)
            normalized = self.apply_confirmation_answer_to_batch(
                normalized=normalized,
                answer_text=batch_answer_text,
                missing_fields=missing_fields,
                options_payload=options_payload,
            )
            result = self._create_multiple_financial_documents(normalized, provider_name=provider_name, dry_run=dry_run)
            if source == 'telegram' and normalized.get('image_based') and dry_run and result.get('status') == 'preview':
                return self._final_confirmation_result(
                    parsed=result['parsed'],
                    provider_name=provider_name,
                    preview=result.get('preview') or {},
                    confidence=float(result.get('confidence') or 0.0),
                )
            return result

        normalized = self.deserialize_normalized(normalized_payload)
        patch = self._resolve_confirmation_with_provider(
            normalized_payload=normalized_payload,
            missing_fields=missing_fields,
            answer_text=answer_text,
            provider_name=provider_name,
            options_payload=options_payload,
            confirmation_history=confirmation_history,
        )
        if patch:
            normalized = self.apply_confirmation_patch(normalized=normalized, patch=patch)
        normalized = self.apply_confirmation_answer(
            normalized=normalized,
            answer_text=answer_text,
            missing_fields=missing_fields,
            options_payload=options_payload,
        )
        result = self._create_financial_document(normalized, provider_name=provider_name, dry_run=dry_run)
        if source == 'telegram' and normalized.get('image_based') and dry_run and result.get('status') == 'preview':
            return self._final_confirmation_result(
                parsed=result['parsed'],
                provider_name=provider_name,
                preview=result.get('preview') or {},
                confidence=float(result.get('confidence') or 0.0),
            )
        return result

    def _normalize_parsed(self, parsed, explicit_wallet_id=None, source_text=None, context=None, image_based=False):
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

        cash_flow_item = CashFlowItem.objects.filter(pk=parsed.get('cash_flow_item_id')).first()
        if cash_flow_item is None:
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

        occurred_at = _parse_datetime_value(parsed.get('occurred_at'))
        if image_based:
            occurred_at = _normalize_image_occurred_at(
                occurred_at,
                raw=parsed,
                source_text=source_text,
            )

        return {
            'intent': intent,
            'confidence': float(parsed.get('confidence') or 0.0),
            'image_based': bool(image_based),
            'amount': amount,
            'wallet': Wallet.objects.filter(pk=parsed.get('wallet_id')).first() or wallet,
            'wallet_from': (
                Wallet.objects.filter(pk=parsed.get('wallet_from_id')).first()
                or _match_wallet_by_hint(parsed.get('wallet_from_hint') or parsed.get('bank_name'))
            ),
            'wallet_to': Wallet.objects.filter(pk=parsed.get('wallet_to_id')).first() or _match_wallet_by_hint(parsed.get('wallet_to_hint')),
            'cash_flow_item': cash_flow_item,
            'comment': comment,
            'include_in_budget': bool(parsed.get('include_in_budget', False)),
            'occurred_at': occurred_at,
            'operation_sign': operation_sign,
            'source_index': parsed.get('source_index'),
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

        occurred_at = normalized.get('occurred_at')
        if occurred_at and hasattr(occurred_at, 'isoformat'):
            occurred_at_value = occurred_at.isoformat()
        else:
            occurred_at_value = occurred_at

        return {
            'intent': normalized.get('intent', INTENT_UNKNOWN),
            'confidence': float(normalized.get('confidence') or 0.0),
            'image_based': bool(normalized.get('image_based')),
            'amount': _serialize_decimal(normalized.get('amount')),
            'wallet_id': (
                str(normalized['wallet'].id)
                if normalized.get('wallet')
                else normalized.get('wallet_id')
            ),
            'wallet_from_id': (
                str(normalized['wallet_from'].id)
                if normalized.get('wallet_from')
                else normalized.get('wallet_from_id')
            ),
            'wallet_to_id': (
                str(normalized['wallet_to'].id)
                if normalized.get('wallet_to')
                else normalized.get('wallet_to_id')
            ),
            'cash_flow_item_id': (
                str(normalized['cash_flow_item'].id)
                if normalized.get('cash_flow_item')
                else normalized.get('cash_flow_item_id')
            ),
            'comment': normalized.get('comment', ''),
            'include_in_budget': bool(normalized.get('include_in_budget', False)),
            'occurred_at': occurred_at_value,
            'operation_sign': normalized.get('operation_sign'),
            'source_index': normalized.get('source_index'),
            'raw': normalized.get('raw', fallback_raw),
        }

    def deserialize_normalized(self, payload):
        return {
            'intent': payload.get('intent', INTENT_UNKNOWN),
            'confidence': float(payload.get('confidence') or 0.0),
            'image_based': bool(payload.get('image_based')),
            'amount': _parse_amount(payload.get('amount')),
            'wallet': Wallet.objects.filter(pk=payload.get('wallet_id')).first(),
            'wallet_from': Wallet.objects.filter(pk=payload.get('wallet_from_id')).first(),
            'wallet_to': Wallet.objects.filter(pk=payload.get('wallet_to_id')).first(),
            'cash_flow_item': CashFlowItem.objects.filter(pk=payload.get('cash_flow_item_id')).first(),
            'comment': payload.get('comment', ''),
            'include_in_budget': bool(payload.get('include_in_budget', False)),
            'occurred_at': _parse_datetime_value(payload.get('occurred_at')),
            'operation_sign': payload.get('operation_sign'),
            'source_index': payload.get('source_index'),
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
            elif wallet_mentions:
                updated['wallet'] = _match_wallet_by_hint(wallet_mentions[0])
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
                    _wallet_confirmation_candidates(normalized['raw'].get('wallet_hint') or normalized['raw'].get('bank_name')),
                    kind='wallet',
                )
            if normalized['cash_flow_item'] is None:
                missing_fields.append('cash_flow_item')
                options['cash_flow_item'] = _serialize_options(
                    _cash_flow_item_confirmation_candidates(
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
                    _wallet_confirmation_candidates(normalized['raw'].get('wallet_hint') or normalized['raw'].get('bank_name')),
                    kind='wallet',
                )
            if normalized['cash_flow_item'] is None:
                missing_fields.append('cash_flow_item')
                options['cash_flow_item'] = _serialize_options(
                    _cash_flow_item_confirmation_candidates(
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
                    _wallet_confirmation_candidates(normalized['raw'].get('wallet_from_hint') or normalized['raw'].get('bank_name')),
                    kind='wallet',
                )
            if normalized['wallet_to'] is None:
                missing_fields.append('wallet_to')
                options['wallet_to'] = _serialize_options(
                    _wallet_confirmation_candidates(normalized['raw'].get('wallet_to_hint')),
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

    def _build_month_expenses_by_item_reply(self, summary):
        rows = summary.get('items') or []
        if not rows:
            return f'Расходов за {summary.get("period_label", "текущий месяц")} по статьям не найдено.'

        lines = [f'Расходы за {summary["period_label"]} по статьям:']
        visible_rows = rows[:15]
        for row in visible_rows:
            line = f'- {row["cash_flow_item_name"]}: {row["actual"]}'
            if row.get('budget'):
                line += f' | бюджет {row["budget"]}'
                if Decimal(row.get('overrun') or '0.00') > ZERO_AMOUNT:
                    line += f' | перерасход {row["overrun"]}'
                elif Decimal(row.get('remaining') or '0.00') > ZERO_AMOUNT:
                    line += f' | остаток {row["remaining"]}'
                else:
                    line += ' | в рамках бюджета'
            else:
                line += ' | бюджета нет'
            lines.append(line)

        if len(rows) > len(visible_rows):
            lines.append(f'И еще {len(rows) - len(visible_rows)} статей.')

        lines.append(f'Итого расход: {summary["total_actual"]}')
        if summary.get('total_budget'):
            total_deviation = Decimal(summary.get('total_deviation') or '0.00')
            if total_deviation > ZERO_AMOUNT:
                lines.append(f'Итого бюджет: {summary["total_budget"]} | перерасход {summary["total_overrun"]}')
            elif total_deviation < ZERO_AMOUNT:
                lines.append(f'Итого бюджет: {summary["total_budget"]} | остаток {summary["total_remaining"]}')
            else:
                lines.append(f'Итого бюджет: {summary["total_budget"]} | в рамках бюджета')
        return '\n'.join(lines)

    def _build_confirmation_reply(self, reply_text, options, missing_fields=None, missing_fields_by_item=None):
        missing_fields = missing_fields or []
        missing_fields_by_item = missing_fields_by_item or []
        if not options and not missing_fields:
            return reply_text
        lines = [reply_text]
        if missing_fields_by_item:
            lines.append('Не хватает по строкам:')
            for item in missing_fields_by_item:
                labels = [self._humanize_missing_field(field) for field in item.get('missing_fields') or []]
                if not labels:
                    continue
                lines.append(f'Строка {item["index"]}: {", ".join(labels)}.')
        elif missing_fields:
            labels = [self._humanize_missing_field(field) for field in missing_fields]
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
