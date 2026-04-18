# Локальное тестирование Django ЛК без Docker

## 🚀 Быстрая настройка для тестирования

### 1. Установка PostgreSQL

#### Windows:
```bash
# Скачайте PostgreSQL с официального сайта
# https://www.postgresql.org/download/windows/

# Или через Chocolatey:
choco install postgresql

# Или через winget:
winget install PostgreSQL.PostgreSQL

# После установки добавьте в PATH (обычно):
# C:\Program Files\PostgreSQL\15\bin
# Или найдите где установлен PostgreSQL и добавьте папку bin в PATH
```

#### macOS:
```bash
# Через Homebrew:
brew install postgresql
brew services start postgresql
```

#### Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### 2. Создание базы данных

```bash
# Подключитесь к PostgreSQL
psql -U postgres

# Если psql не найден, попробуйте полный путь (Windows):
# "C:\Program Files\PostgreSQL\15\bin\psql.exe" -U postgres

# В psql консоли:
CREATE DATABASE djangolk;
CREATE USER djangolk_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE djangolk TO djangolk_user;
\q
```

**Альтернатива для Windows без установки PostgreSQL:**
```bash
# Используйте Docker для быстрого старта с PostgreSQL:
docker run --name postgres-test -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:14

# Подключение к контейнеру:
docker exec -it postgres-test psql -U postgres
```

### 3. Настройка Python окружения

```bash
# Создайте виртуальное окружение
python -m venv venv

# Активируйте его
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Установите зависимости
pip install -r requirements.txt
```

### 4. Настройка переменных окружения

Создайте файл `.env` в корне проекта:

```env
# Django Settings
SECRET_KEY=your-very-secret-key-for-development-only
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database
DB_HOST=localhost
DB_NAME=djangolk
DB_USER=djangolk_user
DB_PASSWORD=your_password
DB_PORT=5432

# CORS
CORS_ALLOWED_ORIGINS=http://localhost:8080,http://localhost:3000
```

### 5. Применение миграций

```bash
# Проверьте подключение к БД
python manage.py check

# Примените миграции
python manage.py migrate

# Создайте суперпользователя
python manage.py createsuperuser
```

### 6. Запуск сервера

```bash
python manage.py runserver
```

## 🧪 Тестирование API

### Базовая проверка
```bash
# Проверка работы сервера
curl http://127.0.0.1:8000/

# Должен вернуть редирект на админку
```

### Тестирование аутентификации

```bash
# Получение JWT токена
curl -X POST http://127.0.0.1:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_admin_password"}'

# Ответ:
# {
#   "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
#   "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
# }
```

### Тестирование API endpoints

```bash
# Сохраните токен из предыдущего запроса
TOKEN="your_access_token_here"

# Тестирование справочников
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/wallets/

curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/cash-flow-items/

curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/projects/

# Тестирование финансовых операций
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/receipts/

curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/expenditures/
```

### Тестирование новой функциональности

```bash
# Тестирование фильтрации
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/expenditures/?include_in_budget=true"

curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/v1/budgets/?type=income"

# Тестирование кастомных endpoints
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/cash-flow-items/hierarchy/

# Создание тестовых данных через POST
curl -X POST http://127.0.0.1:8000/api/v1/wallets/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "CASH",
    "name": "Наличные",
    "deleted": false,
    "hidden": false
  }'
```

## 🐍 Интерактивное тестирование через Django shell

```bash
python manage.py shell
```

```python
# В Django shell:
from money.models import *
from users.models import CustomUser

# Создание тестовых данных
user = CustomUser.objects.create_user('testuser', 'test@example.com', 'password')

# Создание кошелька
wallet = Wallet.objects.create(
    code='TEST001',
    name='Тестовый кошелек',
    deleted=False,
    hidden=False
)

# Создание статьи движения средств
cash_flow = CashFlowItem.objects.create(
    code='INCOME001',
    name='Зарплата',
    deleted=False,
    include_in_budget=True
)

# Создание прихода
receipt = Receipt.objects.create(
    number='R001',
    amount=50000.00,
    comment='Зарплата за январь',
    wallet=wallet,
    cash_flow_item=cash_flow
)

# Проверка автоматического создания регистров
from money.models import FlowOfFunds
print(f"Создано записей в FlowOfFunds: {FlowOfFunds.objects.count()}")

# Тестирование миксина
receipt.update_registers()
print(f"После update_registers: {FlowOfFunds.objects.count()}")
```

## 🔧 Отладка и решение проблем

### Проблемы с подключением к БД

```bash
# Проверка подключения к PostgreSQL
psql -h localhost -U djangolk_user -d djangolk

# Если не подключается, проверьте:
# 1. Запущен ли PostgreSQL
sudo systemctl status postgresql  # Linux
brew services list | grep postgres  # macOS

# 2. Правильные ли настройки в .env
cat .env
```

### Проблемы с миграциями

```bash
# Откат миграций
python manage.py migrate money zero
python manage.py migrate users zero

# Повторное применение
python manage.py migrate

# Проверка статуса миграций
python manage.py showmigrations
```

### Проблемы с зависимостями

```bash
# Обновление pip
python -m pip install --upgrade pip

# Переустановка зависимостей
pip uninstall -r requirements.txt -y
pip install -r requirements.txt

# Для Windows может потребоваться:
pip install psycopg --force-reinstall
# Или альтернативно:
pip install psycopg[binary] --force-reinstall
```

## 📱 Тестирование через веб-интерфейс

### Django Admin
```
http://127.0.0.1:8000/admin/
```

### Browsable API (DRF)
```
http://127.0.0.1:8000/api/v1/
http://127.0.0.1:8000/api/v1/wallets/
http://127.0.0.1:8000/api/v1/expenditures/
```

### HTML интерфейс
```
http://127.0.0.1:8000/web/
http://127.0.0.1:8000/web/wallets/
```

## 🔍 Логирование и мониторинг

```python
# В settings.py можно добавить для отладки:
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'money': {
            'handlers': ['console'],
            'level': 'DEBUG',
        },
    },
}
```

## ✅ Чек-лист для тестирования

- [ ] PostgreSQL установлен и запущен
- [ ] База данных создана
- [ ] Виртуальное окружение активировано
- [ ] Зависимости установлены
- [ ] .env файл настроен
- [ ] Миграции применены
- [ ] Суперпользователь создан
- [ ] Сервер запускается без ошибок
- [ ] JWT аутентификация работает
- [ ] CRUD операции через API работают
- [ ] Фильтрация работает
- [ ] Кастомные endpoints доступны
- [ ] Миксин FinancialOperationMixin работает корректно
- [ ] Мягкое удаление работает
- [ ] Регистры обновляются автоматически

Теперь у вас есть полностью работающее локальное окружение для тестирования! 🎉
