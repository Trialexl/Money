# Docker deployment с HTTPS для Telegram и AI

Этот документ описывает минимальный рабочий deployment backend на сервере так, чтобы:

- Django работал в Docker
- API был доступен извне по `https`
- Telegram webhook реально доходил до backend
- AI и Telegram bot работали вместе

## Важное ограничение текущего репозитория

Текущий `docker-compose.yml` поднимает только:

- `db`
- `web`

и сам по себе **не поднимает HTTPS**.

Значит для реального сервера обязательно нужен внешний reverse proxy с TLS, например:

- Caddy
- Nginx
- Traefik

Telegram webhook без публичного `https` URL работать не будет.

## Что должно быть на сервере

Нужно:

- Linux сервер с публичным IP
- домен, указывающий на этот сервер
- открытые порты `80` и `443`
- установленный Docker и Docker Compose

Пример:

- backend API домен: `api.example.com`
- frontend домен: `app.example.com`

## 1. Подготовить `.env`

На сервере в проекте должен быть заполнен `.env`.

Минимально важно:

```env
SECRET_KEY=replace-with-strong-secret
DEBUG=False
ALLOWED_HOSTS=api.example.com

WEB_BIND_HOST=127.0.0.1
WEB_PORT=18000

DB_HOST=db
DB_NAME=djangolk
DB_USER=postgres
DB_PASSWORD=strong-postgres-password
DB_PORT=5432

CORS_ALLOWED_ORIGINS=https://app.example.com

AI_DEFAULT_PROVIDER=openrouter
AI_OPENROUTER_API_KEY=...
AI_OPENROUTER_MODEL=google/gemini-2.5-flash
AI_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions
AI_OPENROUTER_SITE_URL=https://api.example.com
AI_OPENROUTER_APP_NAME=djangolk
AI_ALLOW_RULE_BASED_FALLBACK=True

AI_TELEGRAM_BOT_TOKEN=...
AI_TELEGRAM_BOT_SECRET=choose-your-own-secret-string
AI_TELEGRAM_API_BASE_URL=https://api.telegram.org
AI_DUPLICATE_WINDOW_SECONDS=600
```

## 2. Важные замечания по секретам

- `AI_TELEGRAM_BOT_SECRET` не выдается Telegram, его нужно придумать самому
- `AI_TELEGRAM_BOT_TOKEN` выдается `@BotFather`
- если bot token когда-либо утекал, его нужно перевыпустить
- если `.env` с реальными ключами попадал в git, ключи нужно считать скомпрометированными

## 3. Запустить Docker stack

Минимальный запуск:

```bash
docker compose up -d --build db web
```

Проверка:

```bash
docker compose ps
docker compose logs -f web
```

Ожидаемо:

- контейнер `db` в статусе `healthy`
- контейнер `web` в статусе `Up`
- в логах нет `SystemCheckError`
- `db` не опубликован наружу на host port
- `web` опубликован только на `127.0.0.1:${WEB_PORT}`

## 3.1. Что изменено специально для prod-сервера

В текущем compose:

- PostgreSQL **не публикуется** на host вообще
- API публикуется только на loopback:
  - `127.0.0.1:${WEB_PORT:-18000} -> 8000`

Это сделано специально для сервера, где уже есть:

- другое веб-приложение
- другой PostgreSQL

Такой контракт решает обе проблемы:

- нет конфликта по `5432`, потому что контейнерный `db` не торчит наружу
- нет конфликта по стандартному `8000`, потому что backend сидит на смещенном локальном порту
- прямой доступ к Django извне не нужен, потому что наружу смотрит только reverse proxy с HTTPS

## 4. Прокинуть HTTPS через reverse proxy

Сам backend внутри Docker слушает порт `8000`.
Reverse proxy должен принимать внешний `https` и проксировать на:

- `http://127.0.0.1:${WEB_PORT}`

или на опубликованный docker-порт сервиса `web`.

### Важное правило

Снаружи должен открываться именно такой URL:

- `https://api.example.com/api/v1/ai/telegram-webhook/`

### Пример через Caddy

Готовый пример лежит в:

- [deploy/Caddyfile.example](/Users/alexseyalfimov/git/djangolk/deploy/Caddyfile.example)

Это не часть текущего `docker-compose.yml`, но это самый простой способ получить рабочий HTTPS.

Пример `Caddyfile`:

```caddy
api.example.com {
    reverse_proxy 127.0.0.1:18000
}
```

После этого Caddy сам поднимет TLS, если:

- домен уже указывает на сервер
- порты `80/443` доступны извне

### Пример через Nginx

Если на сервере уже стоит Nginx и через него работает другое приложение, добавь отдельный `server_name` для API.

Готовый пример лежит в:

- [deploy/nginx.api.example.com.conf.example](/Users/alexseyalfimov/git/djangolk/deploy/nginx.api.example.com.conf.example)

Смысл тот же:

- старое приложение продолжает жить на своем `server_name`
- этот backend получает свой отдельный домен, например `api.example.com`
- Nginx проксирует его на `127.0.0.1:18000`

## 5. Проверить backend после HTTPS

Снаружи должны открываться:

- `https://api.example.com/api/schema/`
- `https://api.example.com/api/docs/`
- `https://api.example.com/admin/`

Минимальная проверка:

```bash
curl -I https://api.example.com/api/schema/
```

Ожидается `200 OK`.

## 6. Зарегистрировать Telegram webhook

После того как внешний `https` уже работает, нужно зарегистрировать webhook в Telegram.

Пример:

```bash
curl -X POST "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.example.com/api/v1/ai/telegram-webhook/",
    "secret_token": "AI_TELEGRAM_BOT_SECRET_FROM_ENV"
  }'
```

Важно:

- `secret_token` должен точно совпадать со значением `AI_TELEGRAM_BOT_SECRET` в `.env`
- URL должен быть публичным и доступным по `https`

Проверка:

```bash
curl "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

## 7. Что должно работать после этого

Если все настроено правильно, то бот:

- принимает обычный текст
- принимает `caption`
- принимает `photo`
- скачивает изображение через Telegram Bot API
- прогоняет его через AI pipeline
- сам отправляет ответ обратно в чат через `sendMessage`

## 8. Как привязать Telegram к пользователю приложения

Есть два пути:

### Вариант 1. Авто-привязка

Если:

- `telegram username`
- и `CustomUser.username`

совпадают, backend может привязать пользователя автоматически.

### Вариант 2. Явная привязка

Через web/API нужно вызвать:

- `POST /api/v1/ai/telegram-link-token/`

Полученный код пользователь отправляет боту:

```text
/link CODE
```

Также поддерживаются:

- `/unlink`
- `/cancel`

## 9. Что Telegram не простит

Webhook не будет работать, если:

- указан `localhost`
- используется `http`, а не `https`
- `AI_TELEGRAM_BOT_SECRET` не совпадает с `secret_token`
- backend недоступен извне
- сервер отдает `500` на `/api/v1/ai/telegram-webhook/`

## 10. Минимальный smoke test после deployment

1. Открыть `https://api.example.com/api/docs/`
2. Проверить `https://api.example.com/api/schema/`
3. Вызвать `getWebhookInfo`
4. Написать боту `/link CODE`
5. Отправить:
   - `остатки по кошелькам`
   - `расход сбер еда 2500`
6. Отправить фото банковского скриншота

Если все хорошо, backend:

- примет update
- обработает его
- вернет ответ в Telegram чат

## 11. Что в текущем compose еще остается “не production-grade”

Текущий compose в репозитории практичен для запуска, но в нем есть вещи, которые лучше доработать отдельно:

- сервис `web` сейчас запускает Django `runserver`
- HTTPS не встроен в compose
- секреты и домены пока ожидаются из `.env`

То есть для рабочего сервера схема такая:

1. Docker поднимает `db + web`
2. внешний reverse proxy дает `https`
3. Telegram webhook указывает на внешний `https` URL

## 12. Короткий чеклист “чтобы точно работало”

1. Домен указывает на сервер.
2. На сервере заполнен `.env`.
3. `docker compose up -d --build db web` прошел без ошибок.
4. `docker compose ps` показывает `db healthy` и `web Up`.
5. `db` не опубликован наружу.
6. Reverse proxy смотрит на `127.0.0.1:18000`.
7. Снаружи открывается `https://api.example.com/api/schema/`.
8. Telegram webhook зарегистрирован на внешний `https` URL.

## 13. Пошаговый deployment под сервер с уже существующим приложением

Ниже сценарий именно под твой случай:

- на сервере уже есть другое веб-приложение
- на сервере уже есть PostgreSQL
- этот backend нужно поднять отдельно и без конфликтов по портам

### Шаг 1. Скопировать проект на сервер

```bash
git clone https://github.com/Trialexl/djangolk
cd djangolk
cp env.example .env
```

### Шаг 2. Заполнить `.env`

Минимально поменять:

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS=api.example.com`
- `CORS_ALLOWED_ORIGINS=https://app.example.com`
- `WEB_BIND_HOST=127.0.0.1`
- `WEB_PORT=18000`
- `DB_PASSWORD`
- все `AI_*` секреты

Важно:

- `WEB_PORT` можно выбрать любой свободный локальный порт, не обязательно `18000`
- внешний PostgreSQL на сервере можно игнорировать, потому что compose поднимет свою внутреннюю БД

### Шаг 3. Поднять контейнеры

```bash
docker compose up -d --build db web
docker compose ps
docker compose logs -f web
```

Проверка:

- `db` healthy
- `web` Up
- в логах нет падения Django

### Шаг 4. Проверить изнутри сервера

```bash
curl http://127.0.0.1:18000/api/schema/
```

Если `WEB_PORT` другой, используй его.

На этом этапе backend еще не доступен извне, и это нормально.

### Шаг 5. Подключить reverse proxy

Вариант A, если используешь Caddy:

1. Взять [deploy/Caddyfile.example](/Users/alexseyalfimov/git/djangolk/deploy/Caddyfile.example)
2. Поменять `api.example.com` на реальный домен
3. При необходимости поменять `18000` на свой `WEB_PORT`
4. Перезагрузить Caddy

Вариант B, если используешь Nginx:

1. Взять [deploy/nginx.api.example.com.conf.example](/Users/alexseyalfimov/git/djangolk/deploy/nginx.api.example.com.conf.example)
2. Поменять `api.example.com` на реальный домен
3. При необходимости поменять `18000` на свой `WEB_PORT`
4. Подключить конфиг в `sites-enabled`
5. Проверить `nginx -t`
6. Перезагрузить Nginx

### Шаг 6. Проверить внешний HTTPS

После подключения proxy снаружи должны открываться:

- `https://api.example.com/api/schema/`
- `https://api.example.com/api/docs/`
- `https://api.example.com/admin/`

### Шаг 7. Подключить Telegram webhook

Только после рабочего HTTPS:

```bash
curl -X POST "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://api.example.com/api/v1/ai/telegram-webhook/",
    "secret_token": "AI_TELEGRAM_BOT_SECRET_FROM_ENV"
  }'
```

### Шаг 8. Что важно перепроверить после релиза

- другое приложение на сервере продолжает отвечать как раньше
- новый backend доступен только через свой домен
- `docker compose ps` не показывает published port для `db`
- `ss -ltnp` или `netstat -ltnp` показывает, что backend торчит только на `127.0.0.1:${WEB_PORT}`
- Telegram webhook не возвращает ошибку
2. Порты `80/443` открыты.
3. `web` контейнер поднят без ошибок.
4. Reverse proxy отдает `https://api.example.com`.
5. `/api/schema/` открывается снаружи.
6. `AI_TELEGRAM_BOT_TOKEN` задан.
7. `AI_TELEGRAM_BOT_SECRET` задан.
8. `setWebhook` вызван с тем же `secret_token`.
9. Бот отвечает в Telegram чат на тестовое сообщение.
