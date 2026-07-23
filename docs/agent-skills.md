# Навыки агентов

Навыки проекта Money хранятся в `.agents/skills/` и версионируются вместе с репозиторием. Codex может выбрать подходящий навык автоматически или выполнить его по явному имени.

## `manage-frontmoney-finances`

Навык работает с расходами, бюджетами, кошельками, отчетами и инвестиционным портфелем через OAuth MCP `frontmoney`.

Состав:

- `SKILL.md` — выбор предметных MCP tools, процесс и ограничения безопасных операций;
- `agents/openai.yaml` — зависимость от MCP `frontmoney`.

Явный вызов:

```text
$manage-frontmoney-finances покажи расходы за текущий месяц
```

## OAuth вместо секретов в skill

Skill не читает API-токены, `.env` или секреты агента. Codex подключается к `https://trialexl.freemyip.com/mcp`, выполняет Authorization Code + PKCE и хранит OAuth-учетные данные в системном keyring.

Проектная конфигурация находится в `.codex/config.toml`. После первого запуска выбрать **Authenticate** у MCP `frontmoney` или выполнить:

```powershell
codex mcp login frontmoney
```

В браузере нужно войти в FrontMoney и подтвердить scopes `frontmoney.read` и `frontmoney.write`. Агент получает предметные MCP-инструменты вроде `list_wallets`, `get_financial_report`, `get_portfolio_analysis` и `create_transaction`, но не OAuth-токены, REST-пути или HTTP-методы.

## Серверная конфигурация

В production достаточно существующего домена:

```text
APP_DOMAIN=<app-domain>
```

Из него автоматически получаются `https://<app-domain>` для OAuth issuer и `https://<app-domain>/mcp` для MCP resource. `MCP_ISSUER_URL` и `MCP_PUBLIC_URL` остаются необязательными overrides для нестандартного reverse proxy.

`MCP_OAUTH_ALLOWED_REDIRECT_ORIGINS` нужен только для дополнительных не-loopback HTTPS callback origins. Обычный Codex использует локальный callback на `localhost` или `127.0.0.1` и не требует добавления origin.

После обновления backend выполнить миграции и запустить Compose. Django и MCP работают в одном ASGI-процессе с одним worker; Caddy публикует `/mcp`, OAuth endpoints и обычное приложение через один контейнер `backend`. Это исключает второй Python/Django-процесс на VPS с 1 ГБ RAM.

Значения памяти по умолчанию в Compose ограничивают четыре runtime-контейнера суммарно 848 МБ: PostgreSQL 256 МБ, объединенный backend 320 МБ, frontend 224 МБ и Caddy 48 МБ. Если production `.env` уже содержит старые `*_MEMORY_*`, заменить их значениями из `.env.example`, иначе они переопределят новые defaults.

## Обновление навыка

Репозиторная копия `.agents/skills/manage-frontmoney-finances/` — источник истины. При изменении API:

1. Обновить соответствующий предметный tool и его схему аргументов в `moneybackend/mcp_gateway/domain_tools.py`.
2. Проверить, что внутренний MCP allowlist в `moneybackend/mcp_gateway/api_proxy.py` разрешает только нужные финансовые корни.
3. Запустить `quick_validate.py` из `skill-creator`.
4. Прогнать тесты `mcp_gateway.tests` и убедиться, что skill не содержит API-токенов, REST-путей или прямых HTTP-команд.
