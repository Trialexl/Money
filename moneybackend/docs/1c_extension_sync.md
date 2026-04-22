# Контракт обмена между расширением 1С и Django

## Что является источником истины

Для предметной логики источником истины остается выгрузка основной конфигурации в `1c/`.

Для интеграционного контракта источником истины является расширение в `1c/расширения/`, прежде всего:

- `1c/расширения/CommonModules/DjОбмен/Ext/Module.bsl`
- `1c/расширения/CommonModules/Dj_Users/Ext/Module.bsl`
- `1c/расширения/DataProcessors/DjАдминистрирование/Forms/Форма/Ext/Form/Module.bsl`

## Аутентификация

Расширение 1С использует DRF token authentication, а не JWT:

- заголовок: `Authorization: Token <token>`
- настройки подключения берутся из регистра `DjНастройкиСоединения`
- для HTTPS расширение теперь само включает `ЗащищенноеСоединениеOpenSSL`, если:
  - в поле `Адрес` указан префикс `https://`
  - или в поле `Порт` указан `443`

Для production-сервера с текущим deployment это означает:

- `Адрес = trialexl.freemyip.com`
- `Порт = 443`
- `Токен = <DRF token>`

JWT endpoints `/api/v1/auth/token/` и `/api/v1/auth/refresh/` остаются актуальными для web/API-клиентов, но не являются основным механизмом для расширения 1С.

## Актуальные маршруты обмена

### Справочники

- `wallets`
- `projects`
- `cash-flow-items`
- `users`

### Документы

- `receipts`
- `expenditures`
- `transfers`
- `budgets`
- `auto-payments`

### Табличные части графиков

- `expenditure-graphics`
- `transfer-graphics`
- `budget-graphics`
- `auto-payment-graphics`

### Атомарная замена графиков при выгрузке из 1С

Для документов с графиками оно сначала upsert-ит шапку через обычный detail endpoint, а затем атомарно заменяет весь график document-level action:

- `PUT /api/v1/expenditures/<document_uuid>/replace-graphics/`
- `PUT /api/v1/transfers/<document_uuid>/replace-graphics/`
- `PUT /api/v1/budgets/<document_uuid>/replace-graphics/`
- `PUT /api/v1/auto-payments/<document_uuid>/replace-graphics/`

Payload action содержит массив `rows` с полями `date_start` и `amount`.

## Обратная синхронизация Django -> 1С

На стороне Django реализован outbox измененных объектов.
На стороне 1С consumer встроен в расширение: команда `Обновить` в `DjАдминистрирование` теперь сначала отправляет локальную очередь `1С -> Django`, а затем читает `Django -> 1С` outbox и подтверждает обработанные записи.

### API очереди

- `GET /api/v1/onec-sync/outbox/`
- `POST /api/v1/onec-sync/outbox/ack/`

### Что попадает в очередь

- `cash-flow-items`
- `wallets`
- `projects`
- `users`
- `receipts`
- `expenditures`
- `transfers`
- `budgets`
- `auto-payments`

Для документов с графиками в payload сразу вкладываются строки `graphics`, а для элемента очереди отдельно отдаются:

- `route`
- `graphics_route`
- `clear_type`

Поля `graphics_route` и `clear_type` сохранены для совместимости, но текущее расширение 1С применяет входящий объект как единый пакет и заполняет график напрямую из `graphics`.

### Поведение очереди

- очередь дедуплицируется по `(entity_type, object_id)`
- повторное изменение объекта не создает дубль, а обновляет существующую запись
- изменение строки графика ставит в очередь родительский документ
- hard delete ставит в очередь запись с `operation = delete`
- `ack` не удаляет запись, а проставляет `acknowledged_at`

### Query-параметры списка

- `limit`
- `entity_type`
- `include_acknowledged`

## Правила payload

- все имена полей в JSON должны быть в `snake_case`
- для строк графиков используется `date_start`, а не `dateStart`
- для статей движения средств используется `include_in_budget`, а не `IncludeInBudget`
- пользовательский frontend не должен передавать `id/number/code`, но для интеграционного `Token` auth эти поля остаются разрешены, чтобы не ломать синхронизацию 1С

### Контрагенты -> users

Контрагент выгружается в `/api/v1/users/` со следующими полями:

- `id`
- `username` = `ИНН`
- `full_name`
- `status`
- `tax_id`
- `is_active`
- `password` при наличии в 1С

`status` маппится так:

- `ЮрЛицо.ЮрЛицо -> COMP`
- иначе `PRIV`

## Что уже выровнено

- исходящая синхронизация 1С -> Django использует document-level `replace-graphics` для полной замены графиков
- строки графиков переведены на `date_start`
- статья движения средств переведена на `include_in_budget`
- `Контрагенты` включены в очередную и полную выгрузку справочников
- `ПометкаУдаления` контрагента теперь выгружается как `is_active = false`
- добавлены тесты на `Token` auth и на document-level `replace-graphics` сценарий для 1С-синхронизации
- на стороне Django добавлен outbox измененных объектов для обратной синхронизации
- на стороне 1С реализовано чтение `onec-sync/outbox`, применение объектов и `ack` обратно в Django
- входящая загрузка из Django не ставит объекты обратно в исходящую очередь 1С, чтобы не было зацикливания

## Известные ограничения

- в расширении пока нет регламентного фонового задания для автоматического запуска двустороннего обмена; сейчас обмен запускается вручную через `DjАдминистрирование`
- обратная синхронизация `users -> Контрагенты` не обязана переносить пароль, если его нет в payload, и может упираться в ограничение длины реквизита `ИНН` в 1С
- пользователь, созданный из 1С без `password`, в Django получает unusable password и не сможет войти, пока пароль не будет установлен отдельно
