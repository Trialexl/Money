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

## Backup базы

```bash
./backup-db.sh backup
./backup-db.sh list
./backup-db.sh restore backups/postgres/money-postgres-YYYYMMDD-HHMMSS.dump.gz
./backup-db.sh cleanup 30
```

Скрипт сохраняет дампы PostgreSQL в `backups/postgres/`, требует явное подтверждение `RESTORE` перед восстановлением и не удаляет Docker volumes.

## Документация

- [Индекс документации](docs/README.md)
- [Investment module](docs/investment-module.md)
- [PRD финансовых инструментов](docs/product/financial-instruments-prd.md)
- [Backlog финансовых инструментов](docs/product/financial-instruments-tasks.md)

## Git

Этот корневой репозиторий создан как отдельный repo для объединённого проекта.
Старые git-метаданные frontend и backend вынесены из рабочих директорий, чтобы весь проект можно было версионировать одним репозиторием.
