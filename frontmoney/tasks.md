# FrontMoney Rebuild Roadmap

## Phase 1: Foundation
- [x] Redefine the rebuild plan around a modern product UI instead of patching the legacy prototype
- [x] Add app-wide providers for theme and TanStack Query
- [x] Rework the design tokens, typography, surfaces, and control styles
- [x] Build a new authenticated app shell with responsive navigation and top bar
- [x] Standardize page header, empty state, loading state, and metric card patterns

## Phase 2: Entry Flows
- [x] Rebuild the login screen with clearer auth UX and API/CORS failure messaging
- [x] Rebuild dashboard around decision-ready summaries instead of raw CRUD tables
- [x] Add a profile/settings area for the authenticated user

## Phase 3: Reference Data
- [x] Rebuild wallets list, detail, and form flows on the new foundation
- [x] Rebuild projects section
- [x] Rebuild cash flow items section

## Phase 4: Operations
- [x] Rebuild receipts flows
- [x] Rebuild expenditures flows
- [x] Rebuild transfers flows
- [x] Rebuild budgets flows
- [x] Rebuild auto-payments flows

## Phase 5: Analytics
- [x] Rebuild reports UX and chart presentation
- [x] Revisit export UX so reports feel native rather than bolted on
- [x] Migrate dashboard to `/dashboard/overview/`
- [x] Migrate reports to server-side report endpoints
- [x] Integrate planning/graphics endpoints if they are still needed product-wise

## Phase 6: Quality
- [x] Move more data loading to reusable query hooks and mutation patterns
- [x] Add frontend test coverage for critical auth and CRUD flows
- [x] Fix auth/profile/wallet contract mismatches from the latest OpenAPI
- [x] Remove dead dependencies and legacy page patterns after migration

## Phase 7: AI Surface
- [x] Add AI operation input screen for text and image upload
- [x] Handle `created`, `preview`, `needs_confirmation`, `balance`, and `duplicate` AI responses
- [x] Add Telegram link flow via `/ai/telegram-link-token/`

## Backlog: Next UX and Automation Pass
- [x] In expenditure create flow, analyze expense cash flow items from the last 60 days and rank article suggestions by usage frequency
- [x] In receipt create flow, analyze income cash flow items from the last 60 days and rank article suggestions by usage frequency
- [x] In budget form, when a cash flow item is selected, propagate the same value into the linked budget document field
- [x] Add duplicate actions to every document list; duplicated documents should open prefilled with today as the date
- [x] Decouple planning graphics save from document save so the schedule can be saved independently
- [x] Add automatic planning distribution: take document total, start date, and month count, then spread the amount across the period and prefill the graphics rows

## Backlog: Document + Graphics UX Reset
- [x] Rework every document form with graphics so the user edits one document, not a document plus a separate mini-workflow for schedule rows
- [x] Replace the separate graphics save action with a single document-level save flow; `Save and exit` should also be available on every document form
- [x] Persist graphics in one bulk document save request instead of saving rows one-by-one, so save latency does not grow with the row count
- [x] Add a form-only `monthly amount` helper field: if it is filled, generate graphics from monthly amount × month count and derive the total automatically while still allowing manual total override
- [x] Keep graphics attached to the document contractually and visually; the UI should not imply that schedule rows are a standalone object
- [x] Compress the document + graphics layout so the screen is denser and faster to scan on notebook and desktop widths

## Backlog: Search and Filters
- [x] Add frontend search by cash flow item: operation lists and document forms should allow finding records and options by article name/alias, keep pagination stable, and preserve selected filters in the URL where the page already uses URL state

## Backlog: Budget Forecasting
- [ ] Add a dashboard/report date selector for future budget calculation: the user should be able to choose a future date or month and see balances, budget remaining, overruns, and month result calculated as of that selected date instead of always using today.
- [ ] Extend the backend dashboard/report contract with an explicit calculation date parameter, so frontend and bot budget views use the same source of truth for current and future periods.
- [ ] Preserve selected budget calculation date in the URL where applicable, so future budget views can be refreshed, shared, and revisited without losing context.
