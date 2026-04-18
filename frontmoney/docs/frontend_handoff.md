# Handoff для отдельного frontend и Telegram

Этот документ нужен для отдельного frontend-репозитория и для эксплуатации Telegram-бота.
Он отвечает на два вопроса:

- что уже готово на стороне backend
- что и в каком порядке нужно подключить снаружи

## Что уже реализовано в backend

Backend уже умеет:

- JWT-аутентификацию для web/frontend
- полный CRUD по финансовым сущностям
- dashboard и отчеты
- AI endpoint для текста и изображения
- Telegram webhook
- привязку Telegram к пользователю по одноразовому коду
- уточняющие сценарии `needs_confirmation`
- дедупликацию повторных AI-команд
- аудит AI-решений

## Что важно знать frontend-команде

- frontend лежит отдельно и не обязан знать ничего про 1С
- основной контракт для frontend: обычный JWT REST API
- для AI web-ввода используется `POST /api/v1/ai/execute/`
- для Telegram клиентского UI используется `POST /api/v1/ai/telegram-link-token/`
- сам Telegram webhook должен ходить в `POST /api/v1/ai/telegram-webhook/`

## Минимальный запуск backend для AI

Нужно задать:

- `AI_DEFAULT_PROVIDER=openrouter`
- `AI_OPENROUTER_API_KEY`
- `AI_OPENROUTER_MODEL=google/gemini-2.5-flash`
- `AI_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions`
- `AI_OPENROUTER_SITE_URL`
- `AI_OPENROUTER_APP_NAME`
- `AI_ALLOW_RULE_BASED_FALLBACK=True`

Для Telegram дополнительно:

- `AI_TELEGRAM_BOT_SECRET`
- `AI_TELEGRAM_BOT_TOKEN`
- `AI_TELEGRAM_API_BASE_URL=https://api.telegram.org`

## Web frontend: базовый flow

### 1. Логин

Frontend получает JWT через:

- `POST /api/v1/auth/token/`

### 2. AI-ввод текстом

Запрос:

```http
POST /api/v1/ai/execute/
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "text": "расход сбер еда 2500"
}
```

### 3. AI-ввод картинкой

Запрос:

```http
POST /api/v1/ai/execute/
Authorization: Bearer <access_token>
Content-Type: multipart/form-data
```

Поля:

- `image`
- опционально `text`
- опционально `wallet`
- опционально `dry_run`

### 4. Обработка статусов ответа

Frontend обязательно должен различать:

- `created`
- `needs_confirmation`
- `preview`
- `balance`
- `duplicate`

Практический смысл:

- `created`: операция создана, можно показать success и обновить список
- `needs_confirmation`: нужно показать `reply_text`, `missing_fields`, `options`
- `preview`: backend распознал операцию, но создание еще не выполнено из-за `dry_run=true`
- `balance`: это не операция, а ответ по остаткам
- `duplicate`: повторный ввод, второй документ создавать не надо

## Backend-managed поля

Для обычного frontend API пользователь не должен вводить:

- `id`
- `number`
- `code`

Backend генерирует их сам при создании записи и возвращает уже в response payload.

Исключение:

- интеграционный `Token` auth для 1С все еще может передавать свои технические `id/number/code`, потому что это часть sync-контракта

## Канонический REST-контракт для frontend

Фронту стоит опираться на такие правила:

- в OpenAPI используются отдельные request/response components
- для create нужно смотреть на `*Request`, для patch на `Patched*Request`, а не на response-компонент сущности
- `GET /api/v1/wallets/{id}/balance/` возвращает не `Wallet`, а отдельный payload баланса кошелька
- `GET /api/v1/wallets/balances/` возвращает коллекцию балансов и агрегаты, а не список `Wallet`
- list-фильтры у `expenditures`, `budgets`, `auto-payments` являются частью контракта и описаны в OpenAPI

Текущие фильтры:

- `GET /api/v1/expenditures/?include_in_budget=true|false`
- `GET /api/v1/budgets/?type=income|expense`
- `GET /api/v1/auto-payments/?is_transfer=true|false`

Для `auto-payments` канонические поля такие:

- `date_start`: дата первого автоплатежа
- `amount_month`: количество месяцев графика

Важно:

- `Wallet` в schema это response-компонент; для создания кошелька frontend должен смотреть на `WalletRequest`
- аналогично для документов: `ReceiptRequest`, `ExpenditureRequest`, `TransferRequest`, `BudgetRequest`, `AutoPaymentRequest`
- alias-поля `next_date` и `period_days` backend не поддерживает
- frontend не должен строиться на этих alias-именах и не должен ждать их в schema

## Telegram: рабочий flow

### 1. Привязка Telegram к пользователю

Web frontend инициирует привязку:

- вызывает `POST /api/v1/ai/telegram-link-token/`
- получает `code` и `expires_at`
- показывает пользователю инструкцию:
  - открыть бота
  - отправить `/link CODE`

### 2. Что делает backend после `/link`

Backend:

- находит `TelegramLinkToken`
- создает или обновляет `TelegramUserBinding`
- связывает его с `CustomUser`

### 3. Отвязка

В Telegram можно отправить:

- `/unlink`

### 4. Отмена незавершенной команды

В Telegram можно отправить:

- `/cancel`

Это закрывает активное `AiPendingConfirmation`.

### 5. Telegram photo flow

Если пользователь отправляет фото:

1. Telegram присылает в webhook `message.photo`
2. backend вызывает `getFile`
3. backend скачивает файл по `file_path`
4. backend передает bytes в AI pipeline

То есть Telegram photo и web upload теперь идут по одной и той же бизнес-логике.
После обработки backend сам отправляет ответ обратно в чат через `sendMessage`.

## Что должен уметь frontend поверх backend

На стороне отдельного frontend еще нужно сделать UI, backend это не покрывает:

- экран AI-ввода операции
- drag-and-drop или file input для банковского скриншота
- экран привязки Telegram
- нормальный UI для `needs_confirmation`
- UI для выбора одного из `options`
- обработку `duplicate` как неошибочного состояния
- preview/confirm UX, если frontend хочет использовать `dry_run=true`

## Чего backend пока не делает за frontend

- не рендерит отдельный SPA/UI для AI
- не рисует интерактивные кнопки выбора вариантов в Telegram
- не ведет отдельный “чатовый” UI для web

## Что уже задокументировано

- доменная модель и паритет с 1С:
  - [docs/domain_parity.md](/Users/alexseyalfimov/git/djangolk/docs/domain_parity.md)
- контракт обмена с расширением 1С:
  - [docs/1c_extension_sync.md](/Users/alexseyalfimov/git/djangolk/docs/1c_extension_sync.md)
- AI API и поведение backend:
  - [docs/ai_operations.md](/Users/alexseyalfimov/git/djangolk/docs/ai_operations.md)

## Что раньше было неочевидно и теперь зафиксировано здесь

- frontend может жить отдельно и работать только через JWT REST API
- Telegram-привязка делается через одноразовый код, а не через frontend session sharing
- Telegram photo уже поддержан, это не только `text/caption`
- для корректного UX нужно обрабатывать не только `created`, но и `needs_confirmation`, `balance`, `duplicate`
- `dry_run` можно использовать как основу для будущего preview UI

## Что еще остается вне backend

- собрать реальный frontend UX
- привязать Telegram webhook в инфраструктуре
- прогнать e2e на реальном bot token и реальном OpenRouter key
- довести prompt quality на реальных банковских скриншотах

## Чеклист на завтра для frontend

1. Поднять backend с заполненными AI env-переменными.
2. Проверить логин через JWT.
3. Проверить `POST /api/v1/ai/execute/` на текстовом вводе.
4. Проверить `POST /api/v1/ai/execute/` на image upload.
5. Сделать экран привязки Telegram через `telegram-link-token`.
6. На UI завести обработку `needs_confirmation` и `options`.
7. На UI завести обработку `duplicate` как мягкого ответа, а не ошибки.
8. После этого уже полировать UX и реальный prompt quality под конкретные банковские скриншоты.
