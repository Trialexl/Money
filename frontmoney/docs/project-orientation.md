# FrontMoney: внутренняя карта проекта

Этот файл нужен для быстрого входа в кодовую базу. Он описывает текущее состояние фронтенда по фактическому коду, а не по историческому README.

## Что это за проект

`FrontMoney` это фронтенд для системы управления личными финансами, работающий поверх Django REST API.

- Фронтенд: Next.js App Router
- Язык: TypeScript
- UI: Tailwind CSS + shadcn/ui + Radix primitives
- Сеть: axios
- Состояние: Zustand только для auth
- Графики: Nivo
- Экспорт: `papaparse`, `file-saver`, `jspdf`, `html2canvas`

Важно: в [README](./../README.md) часть описания уже устарела. Например, там указан Next.js 14, а в `package.json` сейчас `next@15.4.6`.

## Быстрый старт

Основные команды:

```bash
npm install
npm run dev
npm run build
npm run start
npm run lint
```

Минимально нужные env-переменные из `.env`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_APP_NAME=FrontMoney
NEXT_PUBLIC_APP_DESCRIPTION=Система управления личными финансами
NEXT_PUBLIC_AUTH_ENABLED=true
```

Если `NEXT_PUBLIC_API_URL` не задан, фронт всё равно по умолчанию смотрит на `http://localhost:8000/api/v1`.

## Где смотреть в первую очередь

Если нужно быстро понять проект, открывать файлы лучше в таком порядке:

1. `package.json` - стек, скрипты, зависимости.
2. `src/app/layout.tsx` - корневой layout и theme provider.
3. `src/app/page.tsx` - редирект с `/` на `/dashboard`.
4. `src/app/(dashboard)/layout.tsx` - клиентская защита приватной зоны.
5. `src/components/shared/sidebar-nav.tsx` - полный список основных разделов.
6. `src/lib/api.ts` - axios instance, auth header, refresh token.
7. `src/store/auth-store.ts` - единственный заметный глобальный store.
8. `src/services/*` - весь слой интеграции с backend.
9. `src/app/(dashboard)/*/page.tsx` - реальные UI-потоки по разделам.
10. `docs/backend.md` и `docs/openapi.json` - backend-контракт и описание API.

## Фактическая структура проекта

```text
docs/
  backend.md               описание Django backend
  openapi.json             OpenAPI слепок backend API
  project-orientation.md   этот файл

src/
  app/
    layout.tsx             корневой layout
    page.tsx               redirect('/dashboard')
    auth/login/page.tsx    логин
    (dashboard)/...        все защищенные страницы
  components/
    ui/                    базовые shadcn/ui компоненты
    shared/                формы, sidebar, theme provider, tree item
    reports/               отчеты, графики, экспорт
  lib/
    api.ts                 axios + interceptors
    auth.ts                localStorage tokens
    formatters.ts          форматирование дат/валют
    export-utils.ts        CSV/PDF export helpers
    utils.ts               cn и мелкие helper'ы
  services/
    auth-service.ts
    wallet-service.ts
    project-service.ts
    cash-flow-item-service.ts
    financial-operations-service.ts
  store/
    auth-store.ts
  types/
    index.ts               API-aligned helpers и часть типов
```

## Архитектурный паттерн

Проект почти полностью клиентский.

- Почти все страницы имеют `"use client"`.
- Данные грузятся прямо в page-компонентах через `useEffect`.
- Фильтры, таблицы, загрузка и ошибки хранятся локально через `useState`.
- Общий state практически отсутствует, кроме auth в Zustand.
- React Query в текущем коде не используется, хотя зависимость установлена.
- Server Components почти не участвуют в бизнес-логике.
- Middleware/server-side auth guard нет; защита приватной зоны делается в клиентском layout.

Типовой CRUD-поток выглядит так:

1. `src/app/(dashboard)/<entity>/page.tsx` грузит список.
2. `src/app/(dashboard)/<entity>/new/page.tsx` рендерит форму создания.
3. `src/app/(dashboard)/<entity>/[id]/edit/page.tsx` подгружает сущность и рендерит ту же форму.
4. `src/components/shared/<entity>-form.tsx` управляет полями и вызывает сервис.
5. `src/services/*` маппят UI-модель в backend payload.

## Навигация и маршруты

### Публичная зона

- `/` -> редирект на `/dashboard`
- `/auth/login` -> логин

### Приватная зона

Все страницы внутри `src/app/(dashboard)` попадают под `src/app/(dashboard)/layout.tsx`.

- `/dashboard`
- `/wallets`
- `/wallets/new`
- `/wallets/[id]`
- `/wallets/[id]/edit`
- `/cash-flow-items`
- `/cash-flow-items/new`
- `/cash-flow-items/[id]/edit`
- `/projects`
- `/projects/new`
- `/projects/[id]/edit`
- `/receipts`
- `/receipts/new`
- `/receipts/[id]/edit`
- `/expenditures`
- `/expenditures/new`
- `/expenditures/[id]/edit`
- `/transfers`
- `/transfers/new`
- `/transfers/[id]/edit`
- `/budgets`
- `/budgets/new`
- `/budgets/[id]/edit`
- `/auto-payments`
- `/auto-payments/new`
- `/auto-payments/[id]/edit`
- `/reports`
- `/settings`

### Навигационное меню

Актуальный список пунктов меню живёт в `src/components/shared/app-shell.tsx` (`sidebar-nav.tsx` остался как legacy-компонент). Это один из самых быстрых способов понять продуктовые разделы проекта:

- Дашборд
- Кошельки
- Статьи
- Проекты
- Приходы
- Расходы
- Переводы
- Бюджеты
- Автоплатежи
- Отчеты
- Настройки

## Авторизация

Auth здесь целиком клиентская.

- `src/app/auth/login/page.tsx` вызывает `AuthService.login`.
- `src/services/auth-service.ts` пишет `access` и `refresh` в `localStorage` через `src/lib/auth.ts`.
- `src/lib/api.ts` добавляет `Authorization: Bearer ...` к каждому запросу.
- При `401` axios interceptor делает `POST /auth/refresh/`.
- Если refresh не удался, токены очищаются и пользователь отправляется на `/auth/login`.
- `src/app/(dashboard)/layout.tsx` проверяет только наличие токена в `localStorage` через `isAuthenticated()`, а потом вызывает `loadProfile()`.
- `AuthService.getProfile()` теперь нормализует и новый backend-контракт (`full_name`, `status`), и старый фронтовый shape (`first_name`, `last_name`, `email`), чтобы app shell и settings не зависели от расхождения схем.

Практический вывод: пока токен просто лежит в `localStorage`, приватная зона считается доступной до первого неуспешного запроса в API.

## Доменные сущности и их сервисы

### Справочники

- `WalletService`
  - список, детальная, create/update/delete
  - отдельный `getWalletBalance(id)` ходит в `/wallets/{id}/balance/`
- `CashFlowItemService`
  - список, детальная, create/update/delete
  - отдельный `getCashFlowItemHierarchy()` нормализует древовидный ответ backend
- `ProjectService`
  - список, детальная, create/update/delete

### Финансовые операции

Всё собрано в `src/services/financial-operations-service.ts`.

- `ReceiptService`
- `ExpenditureService`
- `TransferService`
- `BudgetService`
- `AutoPaymentService`

Сервисный слой выполняет заметный mapping между UI-моделью и backend API:

- `description` в UI отправляется как `comment`
- суммы отправляются строкой через `toApiAmount()`
- `Transfer`: `wallet_from`/`wallet_to` -> `wallet_out`/`wallet_in`
- `Budget`: UI `type` -> backend `type_of_budget` boolean
- `AutoPayment`: UI использует `next_date` и `period_days`, но backend сейчас маппится на `date_start` и `amount_month`

## Страницы и связанные с ними файлы

### 1. Dashboard

`src/app/(dashboard)/dashboard/page.tsx`

- сам тянет кошельки, балансы, приходы и расходы
- баланс по кошелькам запрашивается по одному запросу на каждый кошелек
- считает локально "потрачено за день" и "потрачено за месяц"

### 2. Справочники

#### Wallets

- list: `src/app/(dashboard)/wallets/page.tsx`
- detail: `src/app/(dashboard)/wallets/[id]/page.tsx`
- form: `src/components/shared/wallet-form.tsx`
- service: `src/services/wallet-service.ts`

Особенность: есть отдельная detail-страница, которой нет у большинства остальных сущностей.

#### Cash Flow Items

- list: `src/app/(dashboard)/cash-flow-items/page.tsx`
- form: `src/components/shared/cash-flow-item-form.tsx`
- tree item: `src/components/shared/tree-item.tsx`
- service: `src/services/cash-flow-item-service.ts`

Особенность: поддерживается `parentId` в new-странице и древовидное отображение.

#### Projects

- list/edit/new: `src/app/(dashboard)/projects/*`
- form: `src/components/shared/project-form.tsx`
- service: `src/services/project-service.ts`

### 3. Финансовые документы

Для `receipts`, `expenditures`, `transfers`, `budgets`, `auto-payments` паттерн одинаковый:

- list page с фильтрами и удалением
- new page
- edit page
- shared form component
- методы в `financial-operations-service.ts`

Связанные формы:

- `src/components/shared/receipt-form.tsx`
- `src/components/shared/expenditure-form.tsx`
- `src/components/shared/transfer-form.tsx`
- `src/components/shared/budget-form.tsx`
- `src/components/shared/auto-payment-form.tsx`

### 4. Reports

- root page: `src/app/(dashboard)/reports/page.tsx`
- export actions: `src/components/reports/export-report-buttons.tsx`

Отчеты сейчас работают так:

- root page сама тянет данные из обычных CRUD endpoint'ов, а не из специальных aggregation endpoint'ов
- фильтрует и агрегирует на клиенте
- использует Nivo для графиков
- умеет экспортировать таблицу в CSV/PDF и график в PDF

## Дублирование сущностей

Почти все `new`-страницы поддерживают шаблон дублирования через query param:

```text
/wallets/new?duplicate=<id>
/projects/new?duplicate=<id>
/receipts/new?duplicate=<id>
/expenditures/new?duplicate=<id>
/transfers/new?duplicate=<id>
/budgets/new?duplicate=<id>
/auto-payments/new?duplicate=<id>
```

Механика везде одна:

- `new/page.tsx` читает `duplicate` через `useSearchParams()`
- подгружает исходную сущность
- передает ее в форму как начальные значения

Для `cash-flow-items/new` используется другой сценарий: там подхватывается `parentId`, а не `duplicate`.

## Backend и контракт API

Основа для сверки фронта и бэка:

- `docs/backend.md` - человекочитаемое описание backend
- `docs/openapi.json` - текущий OpenAPI snapshot

По `openapi.json` в проекте сейчас 34 path'а. Для фронта ключевые:

- `/auth/token/`, `/auth/refresh/`, `/auth/logout/`
- `/profile/`, `/profile/{id}/`
- `/wallets/`, `/wallets/{id}/`, `/wallets/{id}/balance/`
- `/cash-flow-items/`, `/cash-flow-items/hierarchy/`
- `/projects/`
- `/receipts/`
- `/expenditures/`
- `/transfers/`
- `/budgets/`
- `/auto-payments/`

Также в контракте есть `*-graphics` endpoint'ы, но в текущем UI они не интегрированы в основной функционал.

## Места, где уже есть несовпадения или технический долг

Это полезно помнить сразу, чтобы не тратить время на ложные ожидания:

- `README.md` частично устарел относительно реального кода.
- `tasks.md` содержит живой список незавершенных задач и уже найденных backend/frontend mismatch'ей.
- `WalletService.getWalletBalance()` уже помечен комментарием как потенциально неточный по схеме ответа.
- `AutoPaymentService` использует временный mapping `period_days -> amount_month`.
- `AuthService.getProfile()` специально нормализует ответ, потому что backend может вернуть массив, а не объект.
- `CashFlowItemService.getCashFlowItemHierarchy()` умеет строить дерево даже из плоского ответа, то есть backend-ответ не считается полностью стабильным.
- Клиентская auth-защита завязана на `localStorage`, а не на server-side session/middleware.
- Списки и отчеты в основном фильтруют данные на клиенте после полного получения списка.

## Что реально используется из зависимостей

По текущему `src/` реально видны в работе:

- Next.js, React, TypeScript
- Tailwind CSS
- TanStack Query
- next-themes
- axios
- Zustand
- Nivo
- Lucide
- `papaparse`, `file-saver`, `jspdf`, `jspdf-autotable`, `html2canvas`

После rebuild data layer уже действительно собран на `@tanstack/react-query`, а legacy chart/form зависимости из раннего прототипа удалены. Если снова появится соблазн искать старые table/form abstractions, их сейчас в проекте нет.

## Полезные ориентиры по задачам

Если нужно быстро что-то чинить, вот краткая карта по направлениям:

- проблемы логина/редиректов -> `src/lib/api.ts`, `src/lib/auth.ts`, `src/store/auth-store.ts`, `src/app/(dashboard)/layout.tsx`
- проблемы бокового меню/маршрутов -> `src/components/shared/sidebar-nav.tsx`
- проблемы с маппингом payload в API -> `src/services/*`, `src/types/index.ts`
- проблемы формы документа -> соответствующий `src/components/shared/*-form.tsx`
- проблемы списков и фильтров -> `src/app/(dashboard)/*/page.tsx`
- проблемы графиков/экспорта -> `src/app/(dashboard)/reports/page.tsx`, `src/components/reports/export-report-buttons.tsx`, `src/lib/export-utils.ts`
- вопросы по backend-контракту -> `docs/openapi.json`, `docs/backend.md`, `tasks.md`

## Что смотреть следующим шагом

Если понадобится более глубокая документация, логично отдельно добавить:

1. таблицу "маршрут -> страница -> форма -> сервис -> endpoint"
2. список фактических полей по каждой сущности
3. карту известных расхождений между `openapi.json` и фронтовыми типами
4. описание пользовательских сценариев по разделам
