# Backlog: стабилизация приложения Money

Дата: 2026-05-17
Основание: анализ текущего состояния объединенного приложения Money
Статус: открыто

Цель документа - зафиксировать действительно необходимые задачи, которые снижают риск потери данных, регрессий, неверных отчетов и проблем production-эксплуатации.

## Приоритеты

- `P0` - критично для безопасной эксплуатации production.
- `P1` - нужно для устойчивого развития без постоянных регрессий.
- `P2` - полезно после стабилизации ядра.

## P0. Production hardening

### P0-SEC-001. Жесткие production-настройки Django

Статус: готово - production settings теперь fail-fast без `SECRET_KEY`, `DEBUG=False` по умолчанию, secure cookies/HSTS/CORS credentials настраиваются через `.env`.

Проблема: backend сейчас допускает небезопасные значения по умолчанию: fallback `SECRET_KEY`, `DEBUG=True`, secure cookies выключены.

Задачи:

- запретить запуск production без явно заданного `SECRET_KEY`;
- сделать `DEBUG=False` безопасным значением по умолчанию для production deployment;
- включить `SESSION_COOKIE_SECURE` и `CSRF_COOKIE_SECURE` в production;
- добавить HSTS/SSL redirect настройки для HTTPS deployment;
- добавить проверку `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS` на старте.

Acceptance criteria:

- production backend не стартует с insecure `SECRET_KEY`;
- cookies защищены при HTTPS;
- случайный запуск с `DEBUG=True` явно виден и не проходит checklist.

### P0-SEC-002. Перевести web-auth с localStorage на безопасное хранение

Статус: готово - web JWT хранится в `HttpOnly` cookies, frontend больше не сохраняет access/refresh в `localStorage`, DRF token auth для 1C сохранен.

Проблема: access/refresh tokens лежат в `localStorage`, что повышает риск кражи токенов при XSS.

Задачи:

- спроектировать auth через `HttpOnly Secure SameSite` cookies или другое серверное хранение refresh-token;
- сохранить совместимость DRF token auth для 1C;
- убрать хранение refresh token в `localStorage`;
- обновить frontend interceptor и login/logout flow;
- добавить регрессионные тесты login, refresh, logout, redirect.

Acceptance criteria:

- refresh token недоступен из JavaScript;
- пользователь не видит browser basic-auth popup при 401;
- 1C sync продолжает использовать `Authorization: Token`.

### P0-OPS-001. Healthchecks, log rotation и базовые алерты

Статус: готово - добавлен `/api/v1/health/`, Docker healthchecks для backend/frontend/caddy, ограничение размера docker logs и `health-check.sh` для cron/webhook уведомлений.

Проблема: в docker compose healthcheck есть только у PostgreSQL, а падение backend/frontend/caddy, OOM и переполнение диска не контролируются.

Задачи:

- добавить healthcheck для backend, frontend и caddy;
- настроить Docker logging driver с ограничением размера логов;
- добавить checks для disk free, container restart count, OOM, HTTP 5xx;
- описать команды проверки в runbook;
- определить канал уведомлений: Telegram, email или внешний мониторинг.

Acceptance criteria:

- `docker compose ps` показывает health для ключевых сервисов;
- логи контейнеров не могут бесконечно съесть диск;
- есть инструкция, как понять, что сервис деградировал.

### P0-OPS-002. Off-server backup и проверка restore

Статус: готово - `backup-db.sh` проверяет gzip/размер backup, пишет журнал, умеет выгружать backup во внешний storage и выполнять `restore-check` во временной БД без перезаписи production. В Django admin добавлен раздел для создания, скачивания и restore-check backup-файлов.

Проблема: текущий backup сохраняется локально в `backups/postgres/`, но локального backup недостаточно при потере сервера или диска.

Задачи:

- добавить выгрузку backup во внешний storage или на отдельную машину;
- добавить проверку успешности backup и размер файла;
- добавить регулярную restore-проверку на отдельной базе или локальном контейнере;
- добавить уведомление при ошибке backup/cleanup/restore-check;
- описать retention policy.

Acceptance criteria:

- backup есть вне production-сервера;
- есть журнал последних backup и restore-check;
- restore-процедура проверена и описана.

### P0-OPS-003. Заменить разрозненные cron+cURL задачи на управляемые background jobs

Статус: готово - добавлен backend app `ops` с registry регламентных заданий, состоянием `last_run/status/duration/error`, историей запусков в admin и management-командой `run_scheduled_jobs`; cron теперь нужен один, без набора curl-команд.

Проблема: регламентные задачи сейчас запускаются через cron и HTTP endpoints. Это плохо контролируется, сложно ретраить и сложно диагностировать.

Задачи:

- выбрать механизм: Celery/RQ/APScheduler или management-command scheduler;
- вынести refresh FX, refresh prices, market health, snapshots, backup checks в job registry;
- добавить retry/backoff/timeout;
- хранить статус последнего запуска, длительность и ошибку;
- оставить HTTP endpoints только для ручного запуска из UI/API.

Acceptance criteria:

- регламентные задачи видны в одном месте;
- есть last run, status, duration, error;
- временная ошибка provider-а не ломает следующий запуск.

### P0-1C-001. Автоматический двусторонний обмен с 1C и контроль проведения  - задачу не делаем. Не приоритет. Оставил  на всякий случай. Но  задача не требуется к выполнению.

Проблема: 1C sync сейчас зависит от ручного запуска через `DjАдминистрирование`; также требуется контролировать, что документы в 1C не только записаны, но и проведены.

Задачи:

- добавить регламентное задание в расширение 1C для двустороннего обмена;
- добавить статус последнего успешного обмена и последней ошибки;
- явно проверить сценарий `Django -> 1C`: документ записан и проведен;
- добавить журнал конфликтов, если один документ изменен с двух сторон;
- добавить инструкцию ручного восстановления обмена.

Acceptance criteria:

- обмен может работать без ручного открытия формы администрирования;
- документы, пришедшие из Django, участвуют в отчетах 1C после проведения;
- конфликт не затирается молча без следа.

### P0-DATA-001. Экран сверки данных и технический health report

Статус: готово - добавлен read-only технический отчет `/api/v1/technical-health/` и admin-раздел `Обслуживание -> Сверка данных`. Отчет сверяет документы с регистрами, orphan-регистры, очередь 1С, активные AI-уточнения, статусы регламентных заданий и качество рыночных данных.

Проблема: отчеты зависят от регистров, графиков, posted/deleted, outbox и рыночных snapshots. Сейчас нет единого места, где видно расхождения.

Задачи:

- добавить endpoint технической сверки;
- проверить документы без регистров и регистры без документов;
- проверить posted/deleted mismatch;
- проверить остатки кошельков против `FlowOfFunds`;
- проверить `OneCSyncOutbox`, pending confirmations, failed AI attempts;
- проверить gaps/stale для FX и price snapshots;
- сделать frontend/admin экран с понятными статусами.

Acceptance criteria:

- можно быстро понять, почему отчет показывает неверную сумму;
- проблемы сверки имеют список объектов и ссылку на исправление;
- health report не меняет данные.

### P0-QA-001. CI pipeline для обязательных проверок

Статус: готово частично - добавлены `./ci.sh`, `make ci` и GitHub Actions workflow. Frontend lint оставлен за `P1-FE-001`, потому что текущий `next lint` требует отдельной настройки под Next 15/ESLint 9.

Проблема: нет единого gate перед deploy/push, поэтому регрессии ловятся уже на сервере.

Задачи:

- добавить GitHub Actions или локальный `make ci`;
- запускать backend tests;
- запускать frontend tests;
- запускать frontend build;
- проверять `docker compose config`;
- проверять миграции и OpenAPI/schema diff.

Acceptance criteria:

- перед deploy есть одна команда проверки;
- failing tests/build блокируют релиз;
- checklist обновления ссылается на CI.

## P1. Устойчивость разработки и производительность

### P1-PERF-001. Индексы для отчетов и списков документов

Статус: готово - добавлены миграции с индексами для денежных регистров, документов, списков, dashboard/report-фильтров и инвестиционных операций. Индексы покрывают даты, состояние `deleted/posted`, кошельки, статьи, проекты и связку `type_of_document + document_id`.

Проблема: отчеты и списки активно фильтруют по датам, кошелькам, статьям, документам, `posted/deleted`. Без индексов скорость будет падать с ростом базы.

Задачи:

- снять `EXPLAIN` для основных отчетов: расходы, бюджет, поток денег, кошельки, dashboard;
- добавить индексы на регистры `FlowOfFunds`, `BudgetIncome`, `BudgetExpense`;
- добавить индексы на документы по `date`, `posted`, `deleted`, `wallet`, `cash_flow_item`;
- проверить инвестиционные отчеты по snapshots;
- добавить регрессионный performance-smoke на крупном наборе данных.

Acceptance criteria:

- основные отчеты не делают полные сканы больших таблиц без необходимости;
- dashboard не деградирует при росте документов;
- индексы зафиксированы миграциями.

### P1-ARCH-001. Разделить крупные backend/frontend модули

Проблема: `money/views.py`, `money/ai_service.py`, frontend `reports/page.tsx` и `investments/page.tsx` стали слишком большими. Это повышает риск регрессий.

Статус: в работе. Backend-срез начат: dashboard вынесен в `money/dashboard_views.py`, отчеты в `money/report_views.py`, read-only viewsets регистров вынесены в `money/register_views.py`, графики планирования в `money/graphic_views.py`, 1C outbox в `money/sync_views.py`, технический health endpoint в `money/technical_views.py`, API routes сохранены.

Задачи:

- вынести money API viewsets по доменным файлам: documents, reports, dashboard, ai, sync;
- вынести dashboard viewset в отдельный backend-модуль;
- вынести report viewset в отдельный backend-модуль;
- вынести регистровые viewsets в отдельный backend-модуль;
- вынести графики планирования и 1C outbox в отдельные backend-модули;
- вынести технические endpoints в отдельный backend-модуль;
- разделить AI service на parser, confirmation flow, telegram adapter, audit;
- разбить frontend reports на hooks, chart components, period selector, tables;
- разбить frontend investments на overview, operations, charts, market data, reports;
- сохранить публичные routes/API без изменений.

Acceptance criteria:

- каждый модуль имеет понятную ответственность;
- существующие тесты проходят;
- новые изменения можно тестировать точечно.

### P1-FE-001. Привести frontend dependency stack к поддерживаемому состоянию

Проблема: в frontend используется Next 15 с React 18, а lint script указан как `next lint`.

Задачи:

- проверить поддерживаемую связку Next/React;
- обновить React/React DOM или зафиксировать Next на совместимой версии;
- заменить `next lint` на актуальный lint setup;
- убедиться, что `npm run build`, `npm run test`, `npm run lint` работают локально и в CI.

Acceptance criteria:

- frontend toolchain не опирается на deprecated команды;
- build и lint воспроизводимы;
- версия React соответствует версии Next.

### P1-AI-001. Регрессионный набор реальных AI/bot сценариев

Проблема: улучшения промптов и flow бота могут ломать уже исправленные реальные кейсы.

Задачи:

- собрать набор обезличенных реальных сообщений, скринов и голосовых;
- хранить ожидаемую нормализованную структуру;
- покрыть кейсы: скрин банка, пропуск строки, выбор кошелька, расходы по месяцу, перевод, остатки;
- запускать regression suite без реального provider-а через fixtures;
- отдельно тестировать provider integration вручную или в nightly.

Acceptance criteria:

- изменение AI flow не принимается без прогона набора кейсов;
- для новой ошибки можно добавить fixture и больше ее не терять;
- provider failure не ломает денежный учет.

### P1-AI-002. Политика хранения AI-данных

Проблема: бот обрабатывает финансовые тексты, изображения и голосовые, но нужно явно определить срок хранения и очистку.

Задачи:

- описать, какие payloads сохраняются в audit;
- добавить retention policy для изображений/голоса/raw provider payload;
- добавить management command очистки старых AI audit данных;
- добавить настройку срока хранения через env;
- описать это в документации.

Acceptance criteria:

- чувствительные AI-данные не хранятся бесконечно без причины;
- очистка не удаляет созданные документы;
- retention можно проверить командой.

### P1-INV-001. Контроль качества рыночных данных

Проблема: графики инвестиций зависят от price/fx snapshots, а gaps/stale данные могут давать убедительно выглядящий, но неверный график.

Задачи:

- добавить gap detection по каждому инструменту и валютной паре;
- добавить backfill с rate-limit aware batching;
- добавить ручное исправление snapshots;
- показывать неполные точки графика как incomplete, а не рисовать их как нормальные;
- добавить список источников и last successful refresh.

Acceptance criteria:

- графики строятся только на датах, где расчет валиден;
- пользователь видит, какие данные отсутствуют;
- backfill не зависает и не создает несколько записей вместо всего периода без объяснения.

### P1-AUDIT-001. История изменений документов

Проблема: документы меняются из web, бота и 1C. Без audit trail сложно понять, почему изменилась сумма, дата, статья или кошелек.

Задачи:

- добавить журнал изменений для Receipt, Expenditure, Transfer, Budget, AutoPayment;
- фиксировать источник изменения: web, bot, 1C, sync, admin;
- хранить старые и новые значения ключевых полей;
- показывать историю в admin или frontend;
- не логировать лишние чувствительные payloads.

Acceptance criteria:

- по документу видно, кто и когда его изменил;
- можно отследить конфликт Django/1C;
- audit не ломает массовые sync операции.

## P2. Продуктовое развитие после стабилизации

### P2-ARCH-001. Явно зафиксировать single-user или multi-user модель - оставляем пока как есть. Задачу пропускаем

Проблема: денежный учет в основном admin/global, а инвестиции user-scoped. Нужно решить, приложение личное single-tenant или готовится к нескольким пользователям.

Задачи:

- описать целевую модель владения данными;
- если single-tenant, убрать вводящие в заблуждение non-admin сценарии;
- если multi-user, добавить owner/organization scope в справочники, документы, отчеты и AI;
- обновить permissions и тесты.

Acceptance criteria:

- права доступа соответствуют реальному продукту;
- пользователь не может увидеть чужие данные в multi-user сценарии;
- single-user режим не притворяется multi-user.

### P2-DOC-001. Очистить и синхронизировать документацию

Проблема: часть старых docs описывает уже изменившееся поведение, например Telegram buttons и frontend/backend handoff.

Задачи:

- пройти `frontmoney/docs`, `moneybackend/docs`, `docs`;
- удалить или обновить устаревшие фразы `пока`, если функционал уже реализован;
- добавить release checklist;
- связать runbook, backup, update script, cron/jobs и 1C sync в один сценарий эксплуатации.

Acceptance criteria:

- документация соответствует текущему поведению приложения;
- новый оператор может развернуть и обслуживать систему без чтения истории чата;
- устаревшие инструкции не конфликтуют с production.

### P2-UX-001. UX-доработки делать после P0/P1

Проблема: новые экраны и улучшения графиков полезны, но без P0/P1 будут увеличивать поверхность регрессий.

Задачи:

- собирать UX-идеи в отдельный backlog;
- перед реализацией проверять влияние на отчеты, sync, AI и производительность;
- не начинать крупные UX-переработки без CI и data health.

Acceptance criteria:

- UX-развитие не ухудшает надежность;
- каждое крупное изменение имеет тестовый сценарий;
- приоритеты согласованы с P0/P1.

## Рекомендуемый порядок выполнения

1. `P0-SEC-001` - production hardening.
2. `P0-QA-001` - CI pipeline.
3. `P0-OPS-001` - healthchecks, log rotation, alerts.
4. `P0-OPS-002` - off-server backup и restore-check.
5. `P0-OPS-003` - managed background jobs.
6. `P0-1C-001` - автоматический 1C sync и проведение.
7. `P0-DATA-001` - экран сверки данных.
8. `P0-SEC-002` - безопасное хранение web-auth tokens.
9. `P1-PERF-001` - индексы и performance.
10. `P1-ARCH-001` - разделение крупных модулей.
11. `P1-FE-001` - frontend dependency stack.
12. `P1-AI-001` - AI regression suite.
13. `P1-INV-001` - market data quality.
14. `P1-AUDIT-001` - история изменений документов.
