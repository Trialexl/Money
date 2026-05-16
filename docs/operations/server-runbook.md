# Server Runbook

Инструкция для установки, обновления, регламентных заданий и backup production-сервера Money.

## 1. Установка на сервер

Требования:

- Linux-сервер с публичным IP.
- Домен указывает на сервер.
- Открыты порты `80` и `443`.
- Установлены `git`, Docker и Docker Compose plugin.

Проверка:

```bash
git --version
docker version
docker compose version
```

Клонирование проекта:

```bash
sudo mkdir -p /opt
sudo chown "$USER":"$USER" /opt
cd /opt
git clone https://github.com/Trialexl/Money.git money
cd /opt/money
```

Настройка окружения:

```bash
cp .env.example .env
nano .env
```

Минимально проверить в `.env`:

- `APP_DOMAIN` - домен приложения, например `trialexl.freemyip.com`.
- `ALLOWED_HOSTS` - тот же домен.
- `CSRF_TRUSTED_ORIGINS=https://<домен>`.
- `CORS_ALLOWED_ORIGINS=https://<домен>`.
- `SECRET_KEY` - заменить на сильный секрет.
- `DB_PASSWORD` - заменить.
- `AI_TELEGRAM_BOT_TOKEN` и `AI_TELEGRAM_BOT_SECRET`, если нужен Telegram bot.
- `AI_OPENROUTER_API_KEY`, если используется OpenRouter.
- `INVESTMENT_PRICE_PROVIDER=coingecko`.
- `INVESTMENT_FX_PROVIDER=cbr`.

Первый запуск:

```bash
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps
```

Проверка HTTPS:

```bash
curl -I https://<домен>/api/schema/
curl -I https://<домен>/
```

Создание администратора, если не создавался через `.env`:

```bash
sudo docker compose exec backend python manage.py createsuperuser
```

## 2. Telegram webhook

Webhook настраивается после того, как HTTPS уже работает.

```bash
curl -X POST "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://<домен>/api/v1/ai/telegram-webhook/",
    "secret_token": "<AI_TELEGRAM_BOT_SECRET>"
  }'
```

Проверка:

```bash
curl "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

## 3. Быстрое обновление сервера

Основной скрипт обновления:

```bash
cd /opt/money
sudo ./update-server.sh
```

Что делает `update-server.sh`:

- проверяет наличие `.env`, `docker-compose.yml`, `git`, `docker`;
- останавливается, если в tracked-файлах есть незакоммиченные изменения;
- выполняет `git pull --ff-only`;
- выполняет `docker compose pull`;
- выполняет `docker compose up -d --remove-orphans`;
- выполняет `docker image prune -f`;
- показывает `docker compose ps`.

Важно:

- `docker image prune -f` удаляет только dangling images.
- Скрипт не выполняет `docker system prune`.
- Скрипт не удаляет Docker volumes.
- База в volume `postgres_data` не чистится.

Перед важным обновлением лучше вручную сделать backup:

```bash
cd /opt/money
sudo ./backup-db.sh backup
```

## 4. Backup и restore базы

Создать backup:

```bash
cd /opt/money
sudo ./backup-db.sh backup
```

Файлы сохраняются в:

```text
backups/postgres/
```

Посмотреть backups:

```bash
sudo ./backup-db.sh list
```

Восстановить backup:

```bash
sudo ./backup-db.sh restore backups/postgres/money-postgres-YYYYMMDD-HHMMSS.dump.gz
```

Скрипт перед restore попросит ввести:

```text
RESTORE
```

Очистить старые backup-файлы старше 30 дней:

```bash
sudo ./backup-db.sh cleanup 30
```

Безопасность cleanup:

- удаляются только локальные файлы `*.dump.gz` и `*.sql.gz` в `backups/postgres/`;
- Docker volumes не удаляются;
- текущая база PostgreSQL не удаляется.

## 5. Регламентные задания

Редактировать cron:

```bash
crontab -e
```

Посмотреть текущий cron:

```bash
crontab -l
```

Рекомендуемый набор:

```cron
SHELL=/bin/bash
APP_DIR=/opt/money
API_BASE=https://trialexl.freemyip.com
API_TOKEN=replace-with-api-token

# Backup базы каждый день ночью.
30 3 * * * cd "$APP_DIR" && sudo ./backup-db.sh backup >/tmp/money-db-backup.log 2>&1

# Очистка backup-файлов старше 30 дней раз в неделю.
45 3 * * 0 cd "$APP_DIR" && sudo ./backup-db.sh cleanup 30 >/tmp/money-db-backup-cleanup.log 2>&1

# Курсы валют USD/EUR/RUB через CBR.
0 8 * * * curl -fsS -X POST -H "Authorization: Token $API_TOKEN" "$API_BASE/api/v1/investment/fx-rates/refresh/" >/tmp/money-fx-refresh.log 2>&1

# Цены активных финансовых инструментов.
5 8 * * * curl -fsS -X POST -H "Authorization: Token $API_TOKEN" "$API_BASE/api/v1/investment/prices/refresh/" >/tmp/money-prices-refresh.log 2>&1

# Контроль свежести рыночных данных.
10 8 * * * curl -fsS -H "Authorization: Token $API_TOKEN" "$API_BASE/api/v1/investment/market-health/?max_age_days=2" >/tmp/money-market-health.log 2>&1
```

Почему такой порядок:

- сначала обновляются FX-курсы;
- потом цены инструментов;
- потом проверяется healthcheck.

Что не надо ставить в ежедневный cron без причины:

- `prices/backfill/` - только для первичного заполнения истории или восстановления пропусков;
- `fx-rates/backfill/` - только для первичного заполнения истории или восстановления пропусков;
- `rebuild_investment_snapshots` - теперь snapshots пересчитываются при изменении сделок и цен, команда нужна как аварийная.

## 6. Ручные команды для инвестиций

Обновить FX-курсы:

```bash
curl -fsS -X POST -H "Authorization: Token $API_TOKEN" \
  "$API_BASE/api/v1/investment/fx-rates/refresh/"
```

Заполнить FX-курсы за период:

```bash
curl -fsS -X POST -H "Authorization: Token $API_TOKEN" \
  "$API_BASE/api/v1/investment/fx-rates/backfill/?date_from=2026-01-01&date_to=2026-05-16"
```

Обновить цены инструментов:

```bash
curl -fsS -X POST -H "Authorization: Token $API_TOKEN" \
  "$API_BASE/api/v1/investment/prices/refresh/"
```

Заполнить цены инструментов за период:

```bash
curl -fsS -X POST -H "Authorization: Token $API_TOKEN" \
  "$API_BASE/api/v1/investment/prices/backfill/?date_from=2026-01-01&date_to=2026-05-16"
```

Проверить свежесть рыночных данных:

```bash
curl -fsS -H "Authorization: Token $API_TOKEN" \
  "$API_BASE/api/v1/investment/market-health/?max_age_days=2"
```

Аварийно пересчитать snapshots портфелей:

```bash
cd /opt/money
sudo docker compose exec backend python manage.py rebuild_investment_snapshots
```

Пересчитать snapshots за период:

```bash
sudo docker compose exec backend python manage.py rebuild_investment_snapshots \
  --date-from 2026-01-01 \
  --date-to 2026-05-16
```

## 7. Как смотреть результаты регламентных заданий

Последний backup:

```bash
sudo ./backup-db.sh list | tail
tail -100 /tmp/money-db-backup.log
```

Последнее обновление FX:

```bash
tail -100 /tmp/money-fx-refresh.log
```

Последнее обновление цен:

```bash
tail -100 /tmp/money-prices-refresh.log
```

Последняя проверка healthcheck:

```bash
tail -100 /tmp/money-market-health.log
```

Состояние контейнеров:

```bash
cd /opt/money
sudo docker compose ps
```

Логи backend:

```bash
sudo docker compose logs --tail=200 backend
```

Логи Caddy:

```bash
sudo docker compose logs --tail=200 caddy
```

## 8. Типовые проблемы

`no space left on device`:

```bash
df -h
sudo docker image prune -f
sudo docker builder prune -f
```

Не использовать без осознанной причины:

```bash
docker system prune --volumes
```

Эта команда может удалить volumes и базу.

`market-health` показывает `missing`:

- по активному инструменту нет ни одного price snapshot;
- нужно выполнить `prices/refresh/` или `prices/backfill/`;
- проверить `provider_symbol` инструмента.

`market-health` показывает `stale`:

- данные есть, но старше `max_age_days`;
- проверить cron и логи `/tmp/money-prices-refresh.log`, `/tmp/money-fx-refresh.log`.

После deploy frontend падает на chunk loading:

- обновить страницу с очисткой кеша;
- проверить, что `docker compose pull` подтянул новый frontend image;
- проверить `sudo docker compose logs --tail=200 frontend`.

## 9. Минимальный чеклист после обновления

```bash
cd /opt/money
sudo docker compose ps
curl -I https://trialexl.freemyip.com/
curl -I https://trialexl.freemyip.com/api/schema/
tail -50 /tmp/money-market-health.log
```
