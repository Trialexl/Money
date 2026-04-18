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

## Git

Этот корневой репозиторий создан как отдельный repo для объединённого проекта.
Старые git-метаданные frontend и backend вынесены из рабочих директорий, чтобы весь проект можно было версионировать одним репозиторием.
