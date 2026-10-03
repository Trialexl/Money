# FrontMoney deployment and operations guide

[English](server-runbook.en.md) · [Русский](server-runbook.md) · [Project overview](../../README.md)

This document is the deployment entry point for a production FrontMoney instance. It covers the initial installation, HTTPS, optional integrations, scheduled jobs, backups, updates, and health checks.

## 1. Prerequisites

- A Linux server with a public IP address.
- A domain with an `A`/`AAAA` record pointing to the server.
- Inbound TCP ports `80` and `443` open.
- Git, Docker Engine, and the Docker Compose plugin.
- Enough storage for PostgreSQL, images, logs, and backups. The default container limits are sized for a small 1 GB VPS.

Verify the host:

```bash
git --version
docker version
docker compose version
```

## 2. Install the project

```bash
sudo mkdir -p /opt
sudo chown "$USER":"$USER" /opt
cd /opt
git clone https://github.com/Trialexl/Money.git money
cd /opt/money
```

Create the production environment file:

```bash
cp .env.example .env
nano .env
```

Never commit `.env`. At minimum, review and replace these values:

```text
APP_DOMAIN=money.example.com
SECRET_KEY=<long-random-secret>
ALLOWED_HOSTS=money.example.com
CSRF_TRUSTED_ORIGINS=https://money.example.com
CORS_ALLOWED_ORIGINS=https://money.example.com
DB_PASSWORD=<strong-database-password>
```

Keep the following production security settings enabled:

```text
DEBUG=False
CORS_ALLOW_CREDENTIALS=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
AUTH_COOKIE_SECURE=True
AUTH_COOKIE_SAMESITE=Lax
```

`NEXT_PUBLIC_API_URL=/api/v1` is the recommended same-origin setup. Caddy obtains and renews the TLS certificate automatically.

## 3. First launch

The production Compose file uses published images from the configured registry:

```bash
sudo docker compose pull
sudo docker compose up -d db
sudo docker compose --profile maintenance run --rm migrate
sudo docker compose up -d
sudo docker compose ps
```

The `migrate` service is an explicit deployment step for migrations, collectstatic, and optional superuser creation. Normal `backend` and `scheduler` restarts skip all startup maintenance.

Create an administrator if one was not created through environment variables:

```bash
sudo docker compose exec backend python manage.py createsuperuser
```

You may instead set `CREATE_SUPERUSER=True` and the `DJANGO_SUPERUSER_*` variables for the first launch. Do not keep a default password in production.

## 4. Verify the deployment

```bash
curl -fsS https://money.example.com/api/v1/health/
curl -I https://money.example.com/api/schema/
curl -I https://money.example.com/
sudo docker compose ps
```

Useful logs:

```bash
sudo docker compose logs --tail=200 backend
sudo docker compose logs --tail=200 frontend
sudo docker compose logs --tail=200 caddy
```

The application should be available at `https://money.example.com`, Django admin at `/admin/`, the OpenAPI schema at `/api/schema/`, and Swagger UI at `/api/docs/`.

## 5. Optional integrations

### AI assistant

For the OpenRouter-powered assistant, configure:

```text
AI_DEFAULT_PROVIDER=openrouter
AI_OPENROUTER_API_KEY=<secret>
AI_OPENROUTER_MODEL=google/gemini-2.5-flash
AI_OPENROUTER_SITE_URL=https://money.example.com
```

Voice transcription additionally requires `AI_OPENAI_API_KEY`. See [AI operations](../../moneybackend/docs/ai_operations.md) for provider behavior and confirmation rules.

### Telegram bot

Set `AI_TELEGRAM_BOT_TOKEN` and a random `AI_TELEGRAM_BOT_SECRET`, restart the backend, then register the webhook:

```bash
curl -X POST "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://money.example.com/api/v1/ai/telegram-webhook/",
    "secret_token": "<AI_TELEGRAM_BOT_SECRET>"
  }'
```

Verify it with:

```bash
curl "https://api.telegram.org/bot<AI_TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

### MCP and OAuth

The OAuth issuer and MCP resource are derived from `APP_DOMAIN`:

```text
https://money.example.com
https://money.example.com/mcp
```

Normally `MCP_ISSUER_URL` and `MCP_PUBLIC_URL` should remain unset. Configure them only when the externally visible URLs differ because of a custom proxy. MCP setup for clients is documented in [Agent skills and MCP](../agent-skills.md) and is also shown in the application under **Settings → MCP connection**.

### Investment market data

The defaults use CoinGecko for crypto prices and the Central Bank of Russia for FX rates:

```text
INVESTMENT_PRICE_PROVIDER=auto
INVESTMENT_FX_PROVIDER=cbr
```

Provider failures are isolated from the regular cash-accounting workflow.

## 6. Scheduled jobs

FrontMoney runs scheduled jobs in the long-running Compose `scheduler` service. It polls for due jobs and maintains a singleton DB lease and heartbeat; no cron dispatcher or recurring `docker compose exec` is needed.

After deployment, inspect the service and remove any legacy `run_scheduled_jobs` entry from the root crontab:

```bash
sudo docker compose ps scheduler
sudo docker compose logs --tail=100 scheduler
sudo docker compose exec -T backend python manage.py run_scheduled_jobs --list
```

The owner, heartbeat and lease expiry are available in Django admin under **Scheduler state**. Job execution state remains available under **Scheduled jobs**.

## 7. Backups and restore verification

Before important updates, create a backup:

```bash
cd /opt/money
sudo ./backup-db.sh backup
```

Inspect backups and verify that the latest dump can be restored into a temporary database:

```bash
sudo ./backup-db.sh list
sudo ./backup-db.sh status
sudo ./backup-db.sh restore-check latest
```

Configure exactly one off-server destination in `.env` when possible:

```text
BACKUP_REMOTE_DIR=/mnt/backup/money/postgres
# or BACKUP_RCLONE_REMOTE=remote:money/postgres
# or BACKUP_RSYNC_TARGET=user@backup-host:/srv/backups/money/postgres
# or BACKUP_SCP_TARGET=user@backup-host:/srv/backups/money/postgres
```

Synchronize and clean up local backups:

```bash
sudo ./backup-db.sh sync latest
sudo ./backup-db.sh cleanup 30
```

Restore is intentionally interactive and requires typing `RESTORE`:

```bash
sudo ./backup-db.sh restore backups/postgres/money-postgres-YYYYMMDD-HHMMSS.dump.gz
```

The scripts do not delete Docker volumes. Backup events are written to `backups/logs/backup-events.log`.

## 8. Validate and update

Run the repository checks on a development machine before deployment:

```bash
./ci.sh
```

Update the server:

```bash
cd /opt/money
sudo ./update-server.sh
```

The update script requires a clean tracked worktree, performs `git pull --ff-only`, pulls container images, recreates services without removing volumes, and removes dangling images only.

After updating, repeat the health checks and inspect the service logs.

## 9. Security checklist

- Use unique production values for `SECRET_KEY`, `DB_PASSWORD`, administrator credentials, bot secrets, and provider keys.
- Keep `.env` readable only by the deployment account and root.
- Do not expose PostgreSQL directly to the internet.
- Restrict `sudo` to the deployment scripts when possible. Granting unrestricted `sudo docker` is effectively equivalent to root access.
- Keep HTTPS and secure cookies enabled.
- Test restore regularly; a backup that has never been restored is not yet verified.
- Store at least one backup outside the application server.
- Review OAuth scopes before authorizing MCP clients. Write access is represented by `frontmoney.write`.

## 10. Detailed operations reference

The [Russian server runbook](server-runbook.md) contains additional diagnostics, job-specific commands, maintenance-screen descriptions, and recovery checks. Both documents describe the same production topology: PostgreSQL, the combined Django/MCP backend, the Next.js frontend, and Caddy.
