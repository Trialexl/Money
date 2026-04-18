# Django ЛК - Система управления личными финансами

Веб-приложение для управления личными финансами с REST API, построенное на Django и Django REST Framework.
Frontend может жить отдельно: backend уже оформлен как самостоятельный API-слой.

## Описание

Система позволяет вести учет доходов и расходов, управлять кошельками, планировать бюджет и настраивать автоматические платежи. Поддерживает как частных лиц, так и компании.

Правила паритета с выгрузкой 1С и принятые архитектурные решения описаны в [docs/domain_parity.md](docs/domain_parity.md).
Контракт синхронизации с расширением 1С описан в [docs/1c_extension_sync.md](docs/1c_extension_sync.md).
Контракт AI-ввода операций из текста и скриншотов описан в [docs/ai_operations.md](docs/ai_operations.md).
Пошаговый handoff для отдельного frontend и Telegram-интеграции описан в [docs/frontend_handoff.md](docs/frontend_handoff.md).
Пошаговый deployment через Docker с обязательным HTTPS описан в [docs/docker_https_deploy.md](docs/docker_https_deploy.md).
Готовые примеры reverse proxy лежат в [deploy/Caddyfile.example](deploy/Caddyfile.example) и [deploy/nginx.api.example.com.conf.example](deploy/nginx.api.example.com.conf.example).

## Основные возможности

### 📁 Справочники
- **Кошельки** - управление различными источниками средств
- **Статьи движения средств** - категории доходов и расходов  
- **Проекты** - группировка операций по проектам
- **Автоматическая генерация кодов** - уникальные коды (CFI001, WLT001, PRJ001, etc.)

### 📊 Финансовые операции
- **Приходы** - учет поступлений денежных средств
- **Расходы** - учет трат с возможностью включения в бюджет
- **Переводы** - перемещение средств между кошельками
- **Бюджеты** - планирование доходов и расходов
- **Автоплатежи** - настройка регулярных операций
- **Автоматическая генерация номеров** - уникальные номера документов (RCP001, EXP001, TRF001, etc.)

### 📈 Аналитика
- Регистры движения денежных средств
- Бюджетные отчеты по доходам и расходам
- Графики планирования операций
- Балансы кошельков в реальном времени
- Агрегированные отчеты по статьям и проектам

### 👥 Пользователи
- Кастомная модель пользователя
- Поддержка компаний и частных лиц
- Реквизиты контрагента из 1С: `full_name`, `status`, `tax_id`, `is_active`
- Для синхронизации из 1С пароль может не передаваться: тогда создается unusable password
- JWT аутентификация

### 🤖 AI-ввод операций
- AI-ввод через текст или банковский скриншот
- Создание `Receipt`, `Expenditure`, `Transfer`
- Запрос остатков по одному кошельку или по всем кошелькам
- Единый backend pipeline для web и Telegram
- Провайдер по умолчанию: `OpenRouter`
- Распознавание кошельков и статей по alias
- Для Telegram есть авто-привязка по совпадению username и сценарий уточняющих ответов

## Технический стек

- **Backend**: Django 4.1.2
- **API**: Django REST Framework 3.14.0
- **База данных**: PostgreSQL 14
- **Аутентификация**: JWT (Simple JWT)
- **Интеграция 1С**: DRF Token Authentication для расширения обмена
- **CORS**: django-cors-headers
- **LLM**: OpenRouter с Gemini-моделью по умолчанию и rule-based fallback для dev/test
- **Контейнеризация**: Docker + Docker Compose

## Требования

- Docker и Docker Compose
- Или: Python 3.8+, PostgreSQL 14+

## Быстрый старт с Docker

### 1. Клонирование репозитория
```bash
git clone https://github.com/Trialexl/djangolk
cd djangolk
```

### 2. Подготовка `.env`
```bash
cp env.example .env
```

### 3. Запуск с Docker Compose
```bash
docker-compose up --build
```

**Доступ к приложению:**
- **API**: `http://127.0.0.1:18000/api/v1/`
- **Админка**: `http://127.0.0.1:18000/admin/`
- **Веб-интерфейс**: `http://127.0.0.1:18000/web/`
- **OpenAPI schema**: `http://127.0.0.1:18000/api/schema/`
- **Swagger UI**: `http://127.0.0.1:18000/api/docs/`

По умолчанию `docker-compose.yml` теперь:
- публикует `web` только на `127.0.0.1:${WEB_PORT:-18000}`
- не публикует `db` наружу вообще

Это сделано под серверный сценарий, где уже заняты стандартные порты и снаружи должен стоять HTTPS reverse proxy.

**Автоматически создается суперпользователь:**
- Логин: `admin`
- Пароль: `admin123`

## Локальная установка

### 1. Настройка PostgreSQL
```bash
# Создайте базу данных
createdb djangolk
```

### 2. Настройка переменных окружения
```bash
# Скопируйте пример файла
cp env.example .env

# Отредактируйте .env файл с вашими настройками
```

Для AI-ввода операций используются дополнительные переменные:
- `AI_DEFAULT_PROVIDER=openrouter`
- `AI_OPENROUTER_API_KEY=...`
- `AI_OPENROUTER_MODEL=google/gemini-2.5-flash`
- `AI_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions`
- `AI_OPENROUTER_SITE_URL=...`
- `AI_OPENROUTER_APP_NAME=djangolk`
- `AI_ALLOW_RULE_BASED_FALLBACK=True`
- `AI_TELEGRAM_BOT_SECRET=...`
- `AI_TELEGRAM_BOT_TOKEN=...`
- `AI_TELEGRAM_API_BASE_URL=https://api.telegram.org`
- `AI_DUPLICATE_WINDOW_SECONDS=600`

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Миграция базы данных
```bash
python manage.py migrate
```

### 5. Создание суперпользователя
```bash
python manage.py createsuperuser
```

### 6. Запуск сервера разработки
```bash
python manage.py runserver
```

## API Endpoints

### Аутентификация
- `POST /api/v1/auth/token/` - получение JWT токена
- `POST /api/v1/auth/refresh/` - обновление токена
- `POST /api/v1/auth/logout/` - выход из системы

Для расширения 1С используется отдельный механизм:
- `Authorization: Token <token>` - DRF token authentication

### Пользователи
- `GET/POST /api/v1/users/` - управление пользователями (только админ)
- `GET/POST /api/v1/profile/` - профиль текущего пользователя

Для обмена с 1С:
- `is_active=false` используется как деактивация контрагента без hard delete
- `password` в `/api/v1/users/` опционален для интеграционного payload из 1С

Для обычного пользовательского API:
- `id` не передается при создании
- `number` и `code` тоже не передаются при создании
- эти значения генерируются backend-ом и приходят только в ответе

### Справочники
- `GET/POST/PUT/DELETE /api/v1/cash-flow-items/` - статьи движения средств
- `GET/POST/PUT/DELETE /api/v1/wallets/` - кошельки
- `GET/POST/PUT/DELETE /api/v1/projects/` - проекты

### Финансовые операции
- `GET/POST/PUT/DELETE /api/v1/receipts/` - приходы
- `GET/POST/PUT/DELETE /api/v1/expenditures/` - расходы
- `GET/POST/PUT/DELETE /api/v1/transfers/` - переводы
- `GET/POST/PUT/DELETE /api/v1/budgets/` - бюджеты
- `GET/POST/PUT/DELETE /api/v1/auto-payments/` - автоплатежи

Для обычных create-запросов frontend не должен спрашивать у пользователя:
- `id`
- `number`
- `code`

В OpenAPI это отражается через отдельные request-компоненты:
- `WalletRequest`, `CashFlowItemRequest`, `ProjectRequest`
- `ReceiptRequest`, `ExpenditureRequest`, `TransferRequest`, `BudgetRequest`, `AutoPaymentRequest`
- для PATCH используются `Patched*Request`

### Графики планирования
- `GET/POST/PUT/DELETE /api/v1/expenditure-graphics/` - графики расходов
- `GET/POST/PUT/DELETE /api/v1/transfer-graphics/` - графики переводов
- `GET/POST/PUT/DELETE /api/v1/budget-graphics/` - графики бюджетов
- `GET/POST/PUT/DELETE /api/v1/auto-payment-graphics/` - графики автоплатежей

Все документы с графиком (`expenditures`, `transfers`, `budgets`, `auto-payments`) в API-ответах содержат поле `graphic_contract`.
Оно явно фиксирует:
- роль шапки документа
- роль строк графика
- какой источник используется для регистров
- допустимо ли прямое редактирование строк
- каким endpoint лучше пользоваться: `replace-graphics` или `generate-graphics`

### Кастомные endpoints
- `GET /api/v1/cash-flow-items/hierarchy/` - иерархическая структура статей
- `GET /api/v1/wallets/{id}/balance/` - баланс кошелька
- `GET /api/v1/wallets/balances/` - балансы всех кошельков
- `PUT /api/v1/expenditures/{id}/replace-graphics/` - атомарная замена графика расхода
- `PUT /api/v1/transfers/{id}/replace-graphics/` - атомарная замена графика перевода
- `PUT /api/v1/budgets/{id}/replace-graphics/` - атомарная замена графика бюджета без пересчета шапки
- `POST /api/v1/budgets/{id}/generate-graphics/` - автогенерация графика бюджета
- `PUT /api/v1/auto-payments/{id}/replace-graphics/` - атомарная замена графика автоплатежа без пересчета шапки
- `POST /api/v1/auto-payments/{id}/generate-graphics/` - автогенерация графика автоплатежа
- `GET /api/v1/dashboard/overview/` - сводный dashboard по мотивам 1С
- `POST /api/v1/ai/execute/` - AI-ввод операции или запроса на остаток для аутентифицированного web/API-пользователя
- `POST /api/v1/ai/telegram-link-token/` - одноразовый код привязки Telegram-бота к текущему пользователю
- `POST /api/v1/ai/telegram-webhook/` - webhook для Telegram-бота
- `GET /api/v1/onec-sync/outbox/` - исходящая очередь измененных объектов для 1С
- `POST /api/v1/onec-sync/outbox/ack/` - подтверждение обработки записей очереди

### Отчеты
- `GET /api/v1/reports/cash-flow/` - отчет по движению денежных средств
- `GET /api/v1/reports/budget-expense/` - отчет по бюджетированию расходов
- `GET /api/v1/reports/budget-income/` - отчет по бюджетированию доходов

### Query параметры фильтрации
- `?include_in_budget=true/false` - фильтр расходов по включению в бюджет
- `?type=income/expense` - фильтр бюджетов по типу (доход/расход)
- `?is_transfer=true/false` - фильтр автоплатежей по типу операции
- `?document={uuid}` - фильтр графиков по документу
- `?date=` - дата dashboard
- `?hide_hidden_wallets=true/false` - учитывать скрытые кошельки в dashboard
- `?date_from=&date_to=` - период отчетов
- `?wallet=` - фильтр отчета ДДС по кошельку
- `?cash_flow_item=` - фильтр отчетов по статье
- `?project=` - фильтр бюджетных отчетов по проекту
- `?limit_by_today=true/false` - не включать в отчет фактические будущие движения

### Канонические поля auto-payments
- backend использует `date_start` как дату первого автоплатежа
- backend использует `amount_month` как количество месяцев графика
- alias-поля `next_date` и `period_days` backend не поддерживает и в контракт не входят

### Служебные
Обратная синхронизация `Django -> 1С` тоже описана там же; backend отдает outbox изменений, который 1С может опрашивать по token auth.

AI-ввод операций и Telegram webhook подробно описаны в [docs/ai_operations.md](docs/ai_operations.md).
Там же зафиксированы одноразовая привязка Telegram через `/link CODE`, команды `/unlink` и `/cancel`, аудит AI-решений и защита от дублей.

## Примеры использования API

### Аутентификация
```bash
# Получение токена
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# Использование токена
curl -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  http://localhost:8000/api/v1/wallets/
```

### Фильтрация данных
```bash
# Только расходы, включенные в бюджет
GET /api/v1/expenditures/?include_in_budget=true

# Только бюджеты доходов
GET /api/v1/budgets/?type=income

# Автоплатежи-переводы
GET /api/v1/auto-payments/?is_transfer=true

# Графики для конкретного документа
GET /api/v1/budget-graphics/?document=uuid-here
```

### Кастомные endpoints
```bash
# Получить иерархию статей движения средств
GET /api/v1/cash-flow-items/hierarchy/

# Получить баланс кошелька
GET /api/v1/wallets/uuid-here/balance/

# Получить dashboard
GET /api/v1/dashboard/overview/?date=2024-03-15T12:00:00Z

# Сгенерировать график бюджета
POST /api/v1/budgets/{uuid}/generate-graphics/

# Атомарно заменить график расхода
PUT /api/v1/expenditures/{uuid}/replace-graphics/

# Атомарно заменить график перевода
PUT /api/v1/transfers/{uuid}/replace-graphics/
``` 

### AI-ввод операций
```bash
# Распознать текстовую команду и создать перевод
curl -X POST http://localhost:8000/api/v1/ai/execute/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "text=перевод сбербанк альфа 20000"

# Запросить остаток по кошельку
curl -X POST http://localhost:8000/api/v1/ai/execute/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "text=какой остаток на сбербанке"

# Передать банковский скриншот
curl -X POST http://localhost:8000/api/v1/ai/execute/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "image=@/path/to/bank-screenshot.png"
```

На текущем этапе:
- text intents уже работают для `Receipt`, `Expenditure`, `Transfer` и запросов остатков
- если обязательных данных не хватает, API возвращает `needs_confirmation`
- image pipeline заведен через `OpenRouter` с Gemini-моделью, но качество распознавания зависит от prompt и доступности `AI_OPENROUTER_API_KEY`
- rule-based fallback предназначен для локальной разработки и тестов, а не для продового OCR

Правило владения шапкой и графиком:
- `expenditures` и `transfers`: шапка хранит факт, график корректирует бюджетное распределение
- `budgets` и `auto-payments`: шапка хранит шаблон генерации, график управляет расписанием регистров
- прямое редактирование строк графика допустимо, но не обязано пересчитывать поля шапки
- для точной внешней синхронизации всего графика используйте document-level `replace-graphics`
- когда нужно пересчитать строки из полей шапки, используйте `generate-graphics` для плановых документов

### Отчеты
```bash
# Отчет по движению денежных средств
GET /api/v1/reports/cash-flow/?date_from=2024-03-01T00:00:00Z&date_to=2024-03-31T23:59:59Z

# Отчет по бюджетированию расходов
GET /api/v1/reports/budget-expense/?date_from=2024-03-01T00:00:00Z&date_to=2024-03-31T23:59:59Z

# Отчет по бюджетированию доходов
GET /api/v1/reports/budget-income/?date_from=2024-03-01T00:00:00Z&date_to=2024-03-31T23:59:59Z
```

### Права доступа
- **Админы**: полный доступ ко всем операциям
- **Пользователи**: только чтение справочников, полный доступ к своим данным
- **Анонимные**: доступ запрещен

## Архитектура URL маршрутов

### Основные маршруты
```
/                       -> Редирект на админку
/admin/                 -> Django административная панель
/web/                   -> HTML интерфейс (опционально)
/api/v1/                -> REST API версии 1
```

### Структура API v1
```
/api/v1/auth/           -> Аутентификация (JWT)
/api/v1/users/          -> Управление пользователями
/api/v1/profile/        -> Профиль текущего пользователя

/api/v1/cash-flow-items/    -> Статьи движения средств
/api/v1/wallets/            -> Кошельки  
/api/v1/projects/           -> Проекты

/api/v1/receipts/           -> Приходы
/api/v1/expenditures/       -> Расходы
/api/v1/transfers/          -> Переводы
/api/v1/budgets/            -> Бюджеты
/api/v1/auto-payments/      -> Автоплатежи

/api/v1/*-graphics/         -> Графики планирования
```

### Примеры использования API

#### Аутентификация
```bash
# Получение JWT токена
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'

# Использование токена
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/profile/
```

#### Создание справочников (автогенерация кодов)
```bash
# Создание статьи движения средств (код генерируется автоматически)
curl -X POST http://localhost:8000/api/v1/cash-flow-items/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"name": "Зарплата"}'
# Ответ: {"code": "CFI001", "name": "Зарплата", ...}

# Создание кошелька (код генерируется автоматически)
curl -X POST http://localhost:8000/api/v1/wallets/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"name": "Основной счет"}'
# Ответ: {"code": "WLT001", "name": "Основной счет", ...}
```

#### Создание документов (автогенерация номеров)
```bash
# Создание прихода (номер генерируется автоматически)
curl -X POST http://localhost:8000/api/v1/receipts/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"amount": 50000, "comment": "Зарплата"}'
# Ответ: {"number": "RCP001", "amount": "50000.00", ...}

# Создание расхода (номер генерируется автоматически)
curl -X POST http://localhost:8000/api/v1/expenditures/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"amount": 1500, "comment": "Продукты"}'
# Ответ: {"number": "EXP001", "amount": "1500.00", ...}
```

#### Получение баланса кошелька
```bash
# Баланс конкретного кошелька
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/wallets/{id}/balance/

# Балансы всех кошельков
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/wallets/balances/
```

#### Фильтрация и поиск
```bash
# Фильтрация по типу
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/v1/cash-flow-items/?type=income"

# Фильтрация по периоду
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/v1/receipts/?date_from=2024-01-01&date_to=2024-01-31"
```

#### Регистры и отчеты
```bash
# Регистр движения средств
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/flow-of-funds/

# Сводка по движению средств
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/v1/flow-of-funds/summary/
```

## Структура проекта

```
djangolk/
├── lk/                     # Основные настройки Django
│   ├── settings.py         # Конфигурация проекта
│   ├── urls.py             # Главные URL маршруты
│   └── api_urls.py         # Центральные API маршруты
├── money/                  # Приложение управления финансами
│   ├── models.py           # Модели данных с FinancialOperationMixin
│   ├── views.py            # API ViewSets с расширенной функциональностью
│   ├── permissions.py      # Кастомные permissions
│   ├── web_views.py        # HTML представления
│   ├── serializers.py      # Сериализаторы DRF
│   ├── urls.py             # Обратная совместимость
│   ├── api_urls.py         # API маршруты (новые)
│   ├── web_urls.py         # HTML маршруты
│   ├── migrations/         # Миграции БД
│   └── templates/          # HTML шаблоны
├── users/                  # Приложение пользователей
│   ├── models.py           # Кастомная модель пользователя
│   ├── views.py            # API views пользователей
│   ├── urls.py             # Обратная совместимость
│   └── api_urls.py         # API маршруты пользователей
├── Dockerfile              # Контейнеризация
├── docker-compose.yml      # Оркестрация сервисов
├── docker-entrypoint.sh    # Инициализация контейнера
├── env.example             # Пример переменных окружения
├── task.md                 # Задачи по улучшению проекта
├── manage.py               # Django управление
└── requirements.txt        # Зависимости Python
```

## Особенности реализации

### 🏗️ Архитектурные решения
- **UUID первичные ключи** для всех моделей
- **Архитектура с миксинами** - управление регистрами через `FinancialOperationMixin`
- **Явное управление регистрами** - вместо сигналов используются методы моделей
- **Разделение HTML и API** - отдельные модули для веб-интерфейса и REST API
- **Kebab-case именование** endpoints для консистентности
- **Кастомные permissions** - гранулярное управление доступом (IsAdminOrReadOnly, IsOwnerOrAdmin)
- **Query фильтрация** - расширенные возможности поиска и фильтрации данных
- **Автоматическая генерация** - уникальные коды справочников и номера документов

### 📊 Бизнес-логика
- **Мягкое удаление** - записи помечаются как удаленные, но не удаляются физически
- **Иерархические справочники** - статьи движения средств поддерживают вложенность
- **Автоматические регистры** - при сохранении операций обновляются регистры движения средств и бюджетов
- **Система нумерации** - автоматическая генерация уникальных кодов и номеров:
  - Справочники: CFI001, WLT001, PRJ001 (CashFlowItem, Wallet, Project)
  - Документы: RCP001, EXP001, TRF001, BGT001, AUT001 (Receipt, Expenditure, Transfer, Budget, AutoPayment)

### 🐳 DevOps
- **Контейнеризация** - полная поддержка Docker с автоматической настройкой
- **Переменные окружения** - безопасная конфигурация через .env файлы
- **Автоматическая инициализация** - создание суперпользователя при первом запуске

## Переменные окружения

Основные переменные для конфигурации:

```env
# Django
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_HOST=localhost
DB_NAME=djangolk
DB_USER=postgres
DB_PASSWORD=postgres
DB_PORT=5432

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:8080,http://localhost:3000
```

## Команды Docker

```bash
# Запуск в фоне
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down

# Пересборка
docker-compose up --build

# Подключение к контейнеру
docker-compose exec web bash
```

## Безопасность

✅ **Улучшения безопасности:**
- SECRET_KEY загружается из переменных окружения
- Настройки базы данных через переменные окружения
- DEBUG контролируется переменной окружения
- JWT аутентификация для API доступа
- Разделение административных и пользовательских endpoints

## Последние обновления

### v2.1 - REST API Enhancement ⚡
- 🛡️ **Кастомные permissions**: IsAdminOrReadOnly, IsOwnerOrAdmin, IsReadOnlyOrAdmin
- 🔍 **Query фильтрация**: include_in_budget, type, is_transfer, document
- 🎯 **Custom actions**: /hierarchy/, /balance/ endpoints
- 🔄 **Мягкое удаление**: perform_destroy с автоочисткой регистров
- ✅ **Валидация**: perform_create с бизнес-правилами
- 📊 **Улучшенная фильтрация**: автоматическое исключение deleted=False

### v2.0 - Архитектурные улучшения ✨
- 🔄 **Рефакторинг маршрутов**: Четкое разделение HTML и API
- 🏗️ **Миксин для регистров**: Замена post_save сигналов на явные методы
- 🐳 **Docker контейнеризация**: Полная поддержка Docker Compose
- 🗄️ **PostgreSQL**: Переход с SQLite на производственную БД
- 📝 **Kebab-case API**: Современное именование endpoints
- ⚙️ **Переменные окружения**: Безопасная конфигурация

## Лицензия

Проект разработан для личного использования.
