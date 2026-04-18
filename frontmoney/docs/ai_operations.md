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
- `unknown`

## Текущий pipeline

1. Endpoint принимает `text` и/или `image`.
2. `money.ai_service.AiOperationService` собирает контекст:
   - список кошельков
   - список статей движения средств
   - alias кошельков и статей
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

## Формат ответа

Основные статусы ответа:

- `created`
- `preview`
- `needs_confirmation`
- `balance`
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

## Текущее поведение по обязательным полям

- `Receipt`: нужен `wallet` и `cash_flow_item`
- `Expenditure`: нужен `wallet` и `cash_flow_item`
- `Transfer`: нужны `wallet_from` и `wallet_to`

Если обязательное поле не распознано уверенно, документ не создается автоматически.

## Ограничения текущего этапа

- alias для `Wallet` и `CashFlowItem` уже заведены в отдельные модели и участвуют в matching
- `rule_based` provider не умеет распознавать изображения
- Telegram endpoint уже умеет скачивать `message.photo` через Telegram Bot API и передавать изображение в AI pipeline; web по-прежнему принимает бинарное изображение напрямую
- для скриншотов нет отдельного OCR-слоя: разбор делегируется multimodal OpenRouter/Gemini, но backend уже умеет принимать `merchant`, `description`, `bank_name`, `occurred_at` и `operation_sign` из structured ответа
- автоподбор `CashFlowItem` пока базовый: для текстового rule-based ввода он опирается на alias и текстовую подсказку, для LLM-сценария зависит от подсказки provider'а
- защита от дублей работает в два слоя:
  - точный fingerprint входа
  - семантический fingerprint операции
- по реальным банковским скриншотам еще нужна дополнительная калибровка prompt/schema на реальных примерах банков
- бот пока не отправляет интерактивные кнопки; подтверждение работает текстом и номером варианта

## Что планируется дальше

- расширять prompt и JSON schema под реальные банковские скриншоты разных банков
- при желании вынести привязку Telegram в отдельный пользовательский flow в web-интерфейсе
- усилить дедупликацию по merchant/date/amount для похожих, но не идентичных скриншотов
- добавить более богатый preview и интерактивный UX подтверждения
