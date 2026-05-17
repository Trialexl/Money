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
- `CORS_ALLOW_CREDENTIALS=True` - нужно для cookie-auth web frontend.
- `AUTH_COOKIE_SECURE=True`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True` - для HTTPS.
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
curl -fsS https://<домен>/api/v1/health/
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

Перед обновлением на рабочей машине желательно выполнить pre-deploy проверку:

```bash
cd /opt/money
./ci.sh
```

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

Минимальная настройка off-server backup в `.env`:

```text
BACKUP_RETENTION_DAYS=30
BACKUP_MIN_BYTES=1024
BACKUP_UPLOAD_AFTER_CREATE=true
BACKUP_ALERT_WEBHOOK_URL=
```

Выбрать нужно только один внешний target, остальные оставить пустыми:

```text
# Самый простой вариант: примонтированный внешний диск/сетевой каталог.
BACKUP_REMOTE_DIR=/mnt/backup/money/postgres

# Или rclone remote.
BACKUP_RCLONE_REMOTE=remote:money/postgres

# Или отдельная машина по rsync/scp.
BACKUP_RSYNC_TARGET=user@backup-host:/srv/backups/money/postgres
BACKUP_SCP_TARGET=user@backup-host:/srv/backups/money/postgres
```

Если target задан, `backup` после создания локального файла автоматически выполнит `sync`.

В Django admin для superuser есть раздел:

```text
Обслуживание -> Backup базы
```

Там можно создать backup, скачать файл и запустить restore-check. В production backend контейнер пишет в тот же host-каталог `backups/postgres/`, потому что он примонтирован в `docker-compose.yml`.

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
sudo ./backup-db.sh status
```

Проверить, что backup можно восстановить, не трогая рабочую базу:

```bash
sudo ./backup-db.sh restore-check latest
```

Команда создает временную БД внутри PostgreSQL, восстанавливает туда выбранный dump, выполняет smoke-запрос и удаляет временную БД.

Выгрузить backup во внешний storage вручную:

```bash
sudo ./backup-db.sh sync latest
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

Журнал backup/restore-check:

```bash
tail -100 backups/logs/backup-events.log
```

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

# Единая точка регламентных заданий backend.
*/5 * * * * cd "$APP_DIR" && sudo docker compose exec -T backend python manage.py run_scheduled_jobs >/tmp/money-scheduled-jobs.log 2>&1

# Базовый healthcheck приложения с опциональным webhook-уведомлением.
*/5 * * * * cd "$APP_DIR" && HEALTH_URL="$API_BASE/api/v1/health/" ./health-check.sh >/tmp/money-health-cron.log 2>&1
```

Внутри `run_scheduled_jobs` backend сам хранит расписание, `last_run`, `status`, `duration`, `error` и историю запусков в admin-разделе `Регламентные задания`.

Проверить список jobs:

```bash
sudo docker compose exec backend python manage.py run_scheduled_jobs --list
```

Запустить конкретную job вручную:

```bash
sudo docker compose exec backend python manage.py run_scheduled_jobs --job investment.fx_refresh
```

Старые cron+cURL строки для `fx-rates/refresh`, `prices/refresh`, `market-health`, `backup` и `restore-check` после обновления нужно удалить, чтобы задания не запускались дважды.

## 6. Диагностика health и логов

Проверить health всех контейнеров:

```bash
cd /opt/money
sudo docker compose ps
curl -fsS https://<домен>/api/v1/health/
```

Проверить последние логи без риска разрастания файла:

```bash
sudo docker compose logs --tail=200 backend
sudo docker compose logs --tail=200 frontend
sudo docker compose logs --tail=200 caddy
```

Ограничение docker logs задается через `.env`:

```text
DOCKER_LOG_MAX_SIZE=10m
DOCKER_LOG_MAX_FILE=5
```

Если нужен внешний alert, укажи webhook перед запуском `health-check.sh`:

```bash
ALERT_WEBHOOK_URL=https://example.com/webhook ./health-check.sh
```

Что не надо ставить в ежедневный cron без причины:

- `prices/backfill/` - только для первичного заполнения истории или восстановления пропусков;
- `fx-rates/backfill/` - только для первичного заполнения истории или восстановления пропусков;
- `rebuild_investment_snapshots` - теперь snapshots пересчитываются при изменении сделок и цен, команда нужна как аварийная.

## 7. Ручные команды для инвестиций

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

## 8. Как смотреть результаты регламентных заданий

Последний backup:

```bash
sudo ./backup-db.sh list | tail
sudo ./backup-db.sh status
tail -100 backups/logs/backup-events.log
```

Последние регламентные задания:

```bash
tail -100 /tmp/money-scheduled-jobs.log
sudo docker compose exec backend python manage.py run_scheduled_jobs --list
```

Последнее обновление FX:

```bash
sudo docker compose exec backend python manage.py run_scheduled_jobs --list | grep investment.fx_refresh
```

Последнее обновление цен:

```bash
sudo docker compose exec backend python manage.py run_scheduled_jobs --list | grep investment.price_refresh
```

Последняя проверка healthcheck:

```bash
tail -100 /tmp/money-health-cron.log
sudo docker compose exec backend python manage.py run_scheduled_jobs --list | grep investment.market_health
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

## 9. Типовые проблемы

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
- проверить `run_scheduled_jobs --list`, admin-раздел `Регламентные задания` и лог `/tmp/money-scheduled-jobs.log`.

После deploy frontend падает на chunk loading:

- обновить страницу с очисткой кеша;
- проверить, что `docker compose pull` подтянул новый frontend image;
- проверить `sudo docker compose logs --tail=200 frontend`.

## 10. Минимальный чеклист после обновления

```bash
cd /opt/money
sudo docker compose ps
curl -fsS https://trialexl.freemyip.com/api/v1/health/
curl -I https://trialexl.freemyip.com/
curl -I https://trialexl.freemyip.com/api/schema/
tail -50 /tmp/money-health-cron.log
tail -50 /tmp/money-scheduled-jobs.log
sudo docker compose exec backend python manage.py run_scheduled_jobs --list
```
