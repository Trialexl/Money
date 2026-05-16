# AI-ввод операций

## Назначение

AI-сервис дает единый вход для естественного ввода финансовых действий:

- текстовые команды
- банковские скриншоты
- запросы на остатки

Сервис должен одинаково обслуживать web-клиент и Telegram-бота.

## Текущий API

### Web/API

- `POST /api/v1/ai/execute/`

Endpoint требует обычную аутентификацию пользователя Django.

Поддерживаемые поля:

- `text`
- `image`
- `wallet`
- `dry_run`

### Telegram

- `POST /api/v1/ai/telegram-webhook/`
- `POST /api/v1/ai/telegram-link-token/`

Поддерживается входящий Telegram `update` с:

- `message.text`
- `message.caption`
- `message.photo`
- `message.voice`
- `message.audio`

Если настроен `AI_TELEGRAM_BOT_SECRET`, backend проверяет заголовок:

- `X-Telegram-Bot-Api-Secret-Token`

Для разбора реальных картинок из Telegram нужны:

- `AI_TELEGRAM_BOT_TOKEN`
- `AI_TELEGRAM_API_BASE_URL`

Backend использует их, чтобы:

1. вызвать `getFile`
2. получить `file_path`
3. скачать изображение
4. передать bytes в тот же AI pipeline, что и web upload
5. отправить пользователю ответ через `sendMessage`

### Привязка Telegram к Django user

Для Telegram backend хранит отдельную привязку пользователя.

Рабочая схема:

- при первом сообщении создается `TelegramUserBinding`
- основной способ привязки: web/API-пользователь вызывает `POST /api/v1/ai/telegram-link-token/` и получает одноразовый код на 15 минут
- в Telegram пользователь отправляет `/link CODE`
- после этого `TelegramUserBinding.user` закрепляется за нужным `CustomUser`
- `/unlink` снимает привязку
- если `telegram username` совпадает с `CustomUser.username`, backend все еще умеет авто-привязать пользователя как fallback
- если привязки нет, webhook отвечает, что аккаунт не привязан и просит выполнить `/link CODE`

### Уточняющие сценарии

Для Telegram backend хранит активное `AiPendingConfirmation`.

Если команда распознана не полностью, например не хватает статьи или кошелька, бот:

- возвращает `needs_confirmation`
- сохраняет нормализованный draft операции
- на следующее сообщение пытается заполнить недостающие поля и завершить создание документа
- если есть несколько кандидатов, отдает нумерованный список вариантов
- пользователь может ответить номером варианта, текстом или `/cancel`
- история уточнений сохраняется в `confirmation_history`
- для batch-распознавания скриншота с несколькими строками backend сохраняет контекст изображения и при уточнении заново просит LLM вернуть итоговую структуру с учетом ответа пользователя
- если все поля собраны, бот показывает финальный preview и не создает документы до подтверждения `Создать` или `да`
- Telegram дополнительно отправляет reply keyboard: кнопки вариантов, `Создать` и `/cancel`

## Провайдеры

По умолчанию используется `OpenRouter` с Gemini-моделью.

Настройки:

- `AI_DEFAULT_PROVIDER`
- `AI_OPENROUTER_API_KEY`
- `AI_OPENROUTER_MODEL`
- `AI_OPENROUTER_BASE_URL`
- `AI_OPENROUTER_SITE_URL`
- `AI_OPENROUTER_APP_NAME`
- `AI_ALLOW_RULE_BASED_FALLBACK`
- `AI_DUPLICATE_WINDOW_SECONDS`

Сейчас реализованы два провайдера:

- `openrouter` для production-like сценария
- `rule_based` как локальный fallback для разработки и тестов

Если выбран `openrouter`, но `AI_OPENROUTER_API_KEY` не задан, и включен `AI_ALLOW_RULE_BASED_FALLBACK=True`, backend автоматически переключается на `rule_based`.

## Поддерживаемые intent'ы

- `create_receipt`
- `create_expenditure`
- `create_transfer`
- `get_wallet_balance`
- `get_all_wallet_balances`
- `get_month_expenses_by_item`
- `get_portfolio_overview`
- `get_instrument_position`
- `get_investment_rebalance`
- `create_investment_buy`
- `create_investment_sell`
- `unknown`

## Текущий pipeline

1. Endpoint принимает `text` и/или `image`.
2. `money.ai_service.AiOperationService` собирает контекст:
   - список кошельков
   - список статей движения средств
   - alias кошельков и статей
   - список инвестиционных инструментов и счетов для investment intent'ов
3. Выбранный provider возвращает структурированный JSON.
4. Backend нормализует распознанные данные:
   - тип операции
   - сумму
   - кошелек
   - кошелек-источник и кошелек-назначение
   - статью
   - merchant / описание / дату операции
5. Если данных хватает, создается документ Django:
   - `Receipt`
   - `Expenditure`
   - `Transfer`
   - `InvestmentOperation` для инвестиционных buy/sell intent'ов после финального подтверждения
6. До фактического создания backend проверяет семантический дубль операции в окне `AI_DUPLICATE_WINDOW_SECONDS`.
7. Если intent относится к остаткам, вместо документа возвращается balance response.
8. Если данных не хватает, backend возвращает `needs_confirmation`.
9. Каждый проход пишет аудит в `AiAuditLog`:
   - сырое распознавание provider'а
   - нормализованный payload
   - финальный ответ backend
   - подтвержденные пользователем поля

## Примеры текстового ввода

- `приход сбербанк 10000`
- `расход сбербанк 2500`
- `перевод сбербанк альфа 20000`
- `какой остаток на сбербанке`
- `остатки по кошелькам`
- `расходы апрель`
- `расходы апрель май`
- `портфель`
- `сколько btc`
- `купил btc 0.1 по 100000`

## Формат ответа

Основные статусы ответа:

- `created`
- `preview`
- `needs_confirmation`
- `balance`
- `info`
- `duplicate`

В ответе могут приходить:

- `intent`
- `provider`
- `confidence`
- `reply_text`
- `created_object`
- `preview`
- `balances`
- `missing_fields`
- `options`
- `parsed`
- `reply_parse_mode`

## Текущее поведение по обязательным полям

- `Receipt`: нужен `wallet` и `cash_flow_item`
- `Expenditure`: нужен `wallet` и `cash_flow_item`
- `Transfer`: нужны `wallet_from` и `wallet_to`
- `InvestmentOperation buy/sell`: нужны инвестиционный счет, инструмент, количество и цена или сумма в USD

Если обязательное поле не распознано уверенно, документ не создается автоматически.

## Ограничения текущего этапа

- alias для `Wallet` и `CashFlowItem` уже заведены в отдельные модели и участвуют в matching
- `rule_based` provider не умеет распознавать изображения
- Telegram endpoint уже умеет скачивать `message.photo`, `message.voice` и `message.audio` через Telegram Bot API; изображения идут в AI pipeline, аудио сначала транскрибируется
- backend уже сам отправляет `reply_text` обратно в Telegram через `sendMessage`
- для Telegram-ответов поддерживается `parse_mode=HTML`, если результат содержит `reply_parse_mode`
- для скриншотов нет отдельного OCR-слоя: разбор делегируется multimodal OpenRouter/Gemini, но backend уже умеет принимать `merchant`, `description`, `bank_name`, `occurred_at` и `operation_sign` из structured ответа
- автоподбор `CashFlowItem` использует alias/подсказки и переданный LLM контекст статей; при сомнении backend запрашивает уточнение
- защита от дублей работает в два слоя:
  - точный fingerprint входа
  - семантический fingerprint операции
- инвестиционные команды не меняют денежные кошельки и не попадают в 1С sync
- по реальным банковским скриншотам еще нужна дополнительная калибровка prompt/schema на реальных примерах банков
- Telegram reply keyboard не заменяет серверную проверку: создание все равно проходит через pending confirmation и финальный preview

## Что планируется дальше

- расширять prompt и JSON schema под реальные банковские скриншоты разных банков
- при желании вынести привязку Telegram в отдельный пользовательский flow в web-интерфейсе
- усилить дедупликацию по merchant/date/amount для похожих, но не идентичных скриншотов
- улучшать preview и набор быстрых кнопок под реальные пользовательские сценарии
