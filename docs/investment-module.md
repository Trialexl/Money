# Investment module

Дата: 2026-05-10  
Статус: MVP implementation notes  
Связанные документы:

- [PRD: финансовые инструменты](product/financial-instruments-prd.md)
- [Backlog: финансовые инструменты](product/financial-instruments-tasks.md)
- [Backend OpenAPI snapshot](../moneybackend/docs/openapi.json)
- [Frontend OpenAPI snapshot](../frontmoney/docs/openapi.json)

## Границы модуля

Модуль финансовых инструментов ведет отдельный учет инвестиционных активов: криптовалют MVP и будущих акций. Он не является частью денежного учета доходов, расходов, переводов и бюджетов.

Инвестиционные операции не создают:

- `FlowOfFunds`;
- `BudgetIncome`;
- `BudgetExpense`;
- `Receipt`;
- `Expenditure`;
- `Transfer`;
- `OneCSyncOutbox`.

Инвестиционный модуль не реализуется в 1С и не синхронизируется с 1С.

## Денежная часть

Связь покупки крипты со списанием денег с кошелька в MVP не предусматривается.

Рекомендуемый сценарий:

1. Покупка крипты на 100 000 RUB отражается в текущем учете денег обычным переводом в скрытый кошелек, например `Крипта`.
2. В investment module создается операция покупки инструмента на ту же сумму для расчета позиции, средней цены и P/L.
3. Если прибыль зафиксирована деньгами, пользователь вручную создает приход в скрытый кошелек со статьей вроде `прибыль крипта`.

Так текущий учет денег показывает реальные остатки и движение средств, а investment module показывает активы, среднюю покупку и прибыль/убыток. Модули не дублируют и не перезаписывают друг друга.

## Основные сущности

`Instrument` - финансовый инструмент.

- `type`: `crypto` или `stock`;
- `ticker`;
- `name`;
- `provider_symbol`;
- `quote_currency`;
- `precision`;
- `is_active`.

`InvestmentPortfolio` - портфель пользователя.

- всегда принадлежит пользователю;
- `base_currency` в MVP всегда `RUB`;
- может быть портфелем по умолчанию.

`InvestmentAccount` - место хранения активов.

- типы: `exchange`, `broker`, `cold_wallet`, `manual`;
- привязан к портфелю;
- `hidden` скрывает счет в UI, но не удаляет данные.

`InvestmentOperation` - операция с активом.

- типы MVP: `buy`, `sell`, `transfer_instrument`, `correction`;
- хранит количество, цену, сумму в валюте операции и сумму в RUB;
- продажа фиксирует realized P/L;
- перевод инструмента между investment accounts не меняет общую позицию портфеля.

`InstrumentPriceSnapshot` - снимок цены.

- поддерживает ручной источник `manual`;
- используется для текущей стоимости, unrealized P/L, total P/L и доходности;
- позже может заполняться refresh endpoint-ом из provider-а курсов.

`FxRateSnapshot` - снимок валютного курса.

- хранит `base_currency`, `quote_currency`, `rate`, `source`;
- нужен для сохранения использованных внешних курсов;
- не пересчитывает исторические операции задним числом.

`InvestmentTargetAllocation` - целевая доля инструмента в портфеле.

- хранит `target_percent` и `tolerance_percent`;
- сумма целевых долей одного портфеля не должна превышать 100%;
- используется только для аналитики ребалансировки и не создает операций.

## Price providers

Текущий слой provider-ов находится в `moneybackend/investments/price_providers.py`.

Доступные provider-ы:

- `coingecko` - основной provider для криптовалют MVP;
- `static` - тестовый provider с заранее заданными ценами;
- `manual`/`disabled` - автоматическое получение цен отключено, используется ручной ввод snapshots.

Env-настройки:

- `INVESTMENT_PRICE_PROVIDER`, по умолчанию `coingecko`;
- `INVESTMENT_PRICE_PROVIDER_BASE_URL`, по умолчанию `https://api.coingecko.com/api/v3/simple/price`;
- `INVESTMENT_PRICE_PROVIDER_TIMEOUT`, по умолчанию `10.0`.

Для CoinGecko `provider_symbol` должен быть CoinGecko id, например `bitcoin`, `ethereum`, `tether`. Для удобства базовые тикеры `BTC`, `ETH`, `USDT` мапятся автоматически.

Любая ошибка provider-а превращается в `PriceProviderError`. Это контролируемая ошибка инвестиционного модуля: она не должна ломать обычный учет денег, dashboard, отчеты или 1С sync.

## FX providers

Слой валютных provider-ов находится в `moneybackend/investments/fx_providers.py`.

Доступные provider-ы:

- `cbr` - основной provider для USD/RUB и EUR/RUB;
- `static` - тестовый provider с заранее заданными курсами;
- `manual`/`disabled` - автоматическое получение валютных курсов отключено.

Env-настройки:

- `INVESTMENT_FX_PROVIDER`, по умолчанию `cbr`;
- `INVESTMENT_FX_PROVIDER_BASE_URL`, по умолчанию `https://www.cbr.ru/scripts/XML_daily.asp`;
- `INVESTMENT_FX_PROVIDER_TIMEOUT`, по умолчанию `10.0`.

`CbrFxRateProvider` поддерживает курсы к RUB. Ошибки provider-а превращаются в `FxRateProviderError` и не должны влиять на обычный учет денег.

## API

Все endpoints находятся под `/api/v1/investment/`.

- `instruments/` - CRUD инструментов, фильтры `type`, `is_active`, `search`.
- `prices/` - CRUD снимков цен, фильтры `instrument`, `date_from`, `date_to`, `source`.
- `prices/refresh/` - обновление цен активных инструментов через configured price/fx providers, с частичными ошибками в `results`.
- `fx-rates/` - CRUD снимков валютных курсов, фильтры `base_currency`, `quote_currency`, `date_from`, `date_to`, `source`.
- `portfolios/` - CRUD портфелей текущего пользователя.
- `portfolios/{id}/overview/` - сводка конкретного портфеля.
- `portfolios/{id}/positions/` - позиции конкретного портфеля, параметр `include_zero`.
- `portfolios/{id}/performance/` - динамика стоимости и P/L, параметры `date_from`, `date_to`, `group_by=day|month`.
- `portfolios/{id}/rebalance/` - текущие отклонения от целевых долей, без автоматического создания операций.
- `target-allocations/` - CRUD целевых долей инструментов, фильтры `portfolio`, `instrument`.
- `accounts/` - CRUD investment accounts, фильтры `portfolio`, `hidden`.
- `operations/` - CRUD investment operations, фильтры `portfolio`, `account`, `instrument`, `operation_type`, `date_from`, `date_to`, `deleted`.
- `portfolio-overview/` - overview портфеля по умолчанию или указанного `portfolio`.

Актуальный OpenAPI доступен в приложении по `/api/schema/` и сохранен в snapshots:

- `moneybackend/docs/openapi.json`;
- `frontmoney/docs/openapi.json`.

## Права доступа

Обычный пользователь видит только свои:

- портфели;
- investment accounts;
- investment operations;
- portfolio overview.

Пользователь не может создать счет или операцию в чужом портфеле. Staff сохраняет административный доступ через Django admin и API queryset.

Инструменты и price snapshots являются общим справочником/рыночными данными.

## Расчеты

Позиции считаются по проведенным и не удаленным investment operations.

- покупки увеличивают количество и себестоимость;
- продажи уменьшают количество по средневзвешенной себестоимости и фиксируют realized P/L;
- корректировки меняют количество и себестоимость вручную;
- переводы между investment accounts не меняют агрегированную позицию портфеля.

Overview считает:

- `cost_basis_rub`;
- `current_value_rub`;
- `realized_pl_rub`;
- `unrealized_pl_rub`;
- `total_pl_rub`;
- `return_percent`;
- `valuation_complete`.
- `largest_asset`;
- `latest_price_at`;

Если по активу нет price snapshot, текущая стоимость и unrealized P/L для этой позиции не считаются, а `valuation_complete` становится `false`.

Позиции дополнительно возвращают `allocation_percent`, `target_allocation_percent`, `tolerance_percent`, `allocation_deviation_percent`, `allocation_deviation_rub` и `rebalance_amount_rub`.

Performance API строит `opening` на момент перед `date_from` и затем точки по дням или месяцам. Для каждой точки используются только операции и price snapshots, доступные на конец этой точки. Поэтому график за год и график за весь период должны давать одинаковое значение на одной и той же дате.

Rebalance API возвращает текущую долю, целевую долю, отклонение в процентах и RUB, а также расчетную сумму `buy/sell/hold`. Это аналитическая подсказка, не инвестиционная рекомендация и не команда на создание операций.

На фронте блок ребалансировки показывает карточки отклонений, таблицу текущих/целевых долей, цветовую индикацию выше/ниже цели и CRUD целевых долей с настройкой tolerance.

Telegram bot поддерживает read-only команды инвестиционного модуля: `портфель`, `сколько btc`, `ребалансировка портфеля`. Эти команды только читают данные портфеля и не создают инвестиционные или денежные операции.

Экран портфеля хранит учет в RUB, но позволяет переключить отображение в USD/EUR. Переключатель использует последний `FxRateSnapshot` выбранной валюты к RUB и меняет только представление сумм.
