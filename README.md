# Money

Объединённый репозиторий проекта учёта денег.

## Структура

- `frontmoney/` — Next.js frontend
- `moneybackend/` — Django backend
- `docker-compose.yml` — общий production stack с HTTPS через Caddy
- `deploy/Caddyfile` — reverse proxy и TLS

## Быстрый старт

```bash
cp .env.example .env
docker compose up -d --build
```

## Проверка перед deploy

```bash
./ci.sh
# или
make ci
```

Скрипт запускает backend checks/tests/schema smoke, frontend typecheck/tests/build и `docker compose config`. Backend-тесты идут на `lk.test_settings` с SQLite и не трогают production-базу.

## Backup базы

```bash
./backup-db.sh backup
./backup-db.sh list
./backup-db.sh restore backups/postgres/money-postgres-YYYYMMDD-HHMMSS.dump.gz
./backup-db.sh cleanup 30
```

Скрипт сохраняет дампы PostgreSQL в `backups/postgres/`, требует явное подтверждение `RESTORE` перед восстановлением и не удаляет Docker volumes.

## Healthcheck

```bash
./health-check.sh
curl -fsS https://<домен>/api/v1/health/
```

В production compose включены healthchecks для backend/frontend/caddy и ограничение размера docker logs.

## Обновление сервера

```bash
sudo ./update-server.sh
```

Скрипт выполняет `git pull --ff-only`, `docker compose pull`, `docker compose up -d --remove-orphans` и безопасный `docker image prune -f` без удаления volumes.

## Документация

- [Индекс документации](docs/README.md)
- [Server runbook: установка, обновление, cron, backup](docs/operations/server-runbook.md)
- [Investment module](docs/investment-module.md)
- [PRD финансовых инструментов](docs/product/financial-instruments-prd.md)
- [Backlog финансовых инструментов](docs/product/financial-instruments-tasks.md)

## Git

Этот корневой репозиторий создан как отдельный repo для объединённого проекта.
Старые git-метаданные frontend и backend вынесены из рабочих директорий, чтобы весь проект можно было версионировать одним репозиторием.
