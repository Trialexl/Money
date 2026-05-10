"use client"

import { useQuery } from "@tanstack/react-query"
import { BarChart3, Coins, LineChart, Landmark, RefreshCw, TrendingUp } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { InvestmentService } from "@/services/investment-service"

const operationLabels: Record<string, string> = {
  buy: "Покупка",
  sell: "Продажа",
  transfer_instrument: "Перевод",
  correction: "Корректировка",
}

export default function InvestmentsPage() {
  const overviewQuery = useQuery({
    queryKey: ["investment-overview"],
    queryFn: InvestmentService.getOverview,
  })
  const instrumentsQuery = useQuery({
    queryKey: ["investment-instruments"],
    queryFn: InvestmentService.getInstruments,
  })
  const accountsQuery = useQuery({
    queryKey: ["investment-accounts"],
    queryFn: InvestmentService.getAccounts,
  })
  const operationsQuery = useQuery({
    queryKey: ["investment-operations"],
    queryFn: InvestmentService.getOperations,
  })

  const isLoading = overviewQuery.isLoading || instrumentsQuery.isLoading || accountsQuery.isLoading || operationsQuery.isLoading
  const isError = overviewQuery.isError || instrumentsQuery.isError || accountsQuery.isError || operationsQuery.isError

  if (isLoading) {
    return <FullPageLoader label="Загружаем портфель..." />
  }

  if (isError || !overviewQuery.data) {
    return (
      <EmptyState
        icon={TrendingUp}
        title="Портфель пока недоступен"
        description="Backend инвестиционного модуля не ответил. Проверь миграции и доступность API."
        action={<Button onClick={() => void overviewQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const overview = overviewQuery.data
  const instruments = instrumentsQuery.data ?? []
  const accounts = accountsQuery.data ?? []
  const operations = operationsQuery.data ?? []
  const visibleAccounts = accounts.filter((account) => !account.hidden)

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Финансовые инструменты"
        title="Портфель"
        description="Криптовалюты, средняя покупка и зафиксированный финансовый результат. Денежные кошельки здесь не меняются автоматически."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Себестоимость" value={formatCurrency(overview.cost_basis_rub)} hint="Остаток позиций в RUB" icon={Coins} variant="compact" />
        <StatCard label="Realized P/L" value={formatCurrency(overview.realized_pl_rub)} hint="Зафиксированный результат" icon={LineChart} tone={overview.realized_pl_rub < 0 ? "danger" : "positive"} variant="compact" />
        <StatCard label="Куплено" value={formatCurrency(overview.bought_rub)} hint="С учетом комиссий" icon={TrendingUp} variant="compact" />
        <StatCard label="Продано" value={formatCurrency(overview.sold_rub)} hint="После комиссий" icon={BarChart3} variant="compact" />
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>Позиции</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              P0-версия считает количество, себестоимость, среднюю покупку и realized P/L. Текущие курсы и unrealized P/L будут следующим этапом.
            </p>
          </div>
          {overview.portfolio ? <Badge variant="outline">{overview.portfolio.name}</Badge> : null}
        </CardHeader>
        <CardContent>
          {overview.positions.length === 0 ? (
            <EmptyState
              icon={Coins}
              title="Позиции еще не заведены"
              description="Создай инструменты, инвестиционный счет и операции покупки через API. UI-формы создания будут добавлены следующим шагом."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  <tr className="border-b border-border/70">
                    <th className="py-3 pr-4">Актив</th>
                    <th className="py-3 pr-4 text-right">Количество</th>
                    <th className="py-3 pr-4 text-right">Себестоимость</th>
                    <th className="py-3 pr-4 text-right">Средняя</th>
                    <th className="py-3 text-right">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.positions.map((position) => (
                    <tr key={position.instrument_id} className="border-b border-border/50">
                      <td className="py-3 pr-4">
                        <div className="font-medium text-foreground">{position.instrument_ticker}</div>
                        <div className="text-xs text-muted-foreground">{position.instrument_name}</div>
                      </td>
                      <td className="py-3 pr-4 text-right tabular-nums">{position.quantity}</td>
                      <td className="py-3 pr-4 text-right tabular-nums">{formatCurrency(position.cost_basis_rub)}</td>
                      <td className="py-3 pr-4 text-right tabular-nums">{formatCurrency(position.average_buy_price_rub)}</td>
                      <td className={position.realized_pl_rub < 0 ? "py-3 text-right text-destructive tabular-nums" : "py-3 text-right text-emerald-600 tabular-nums"}>
                        {formatCurrency(position.realized_pl_rub)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Справочники</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Coins className="h-4 w-4 text-primary" />
                Инструменты
              </div>
              <div className="mt-3 space-y-2">
                {instruments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Пока пусто.</p>
                ) : (
                  instruments.map((instrument) => (
                    <div key={instrument.id} className="flex items-center justify-between gap-2 rounded-2xl bg-card px-3 py-2 text-sm">
                      <span className="font-medium">{instrument.ticker}</span>
                      <Badge variant={instrument.is_active ? "default" : "outline"}>{instrument.type}</Badge>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Landmark className="h-4 w-4 text-primary" />
                Счета
              </div>
              <div className="mt-3 space-y-2">
                {accounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Пока пусто.</p>
                ) : (
                  visibleAccounts.map((account) => (
                    <div key={account.id} className="rounded-2xl bg-card px-3 py-2 text-sm">
                      <div className="font-medium">{account.name}</div>
                      <div className="text-xs text-muted-foreground">{account.currency} · {account.type}</div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Последние операции</CardTitle>
            <Button variant="outline" size="icon" onClick={() => void operationsQuery.refetch()} aria-label="Обновить">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            {operations.length === 0 ? (
              <p className="text-sm text-muted-foreground">Операций пока нет.</p>
            ) : (
              <div className="space-y-2">
                {operations.slice(0, 10).map((operation) => (
                  <div key={operation.id} className="flex items-center justify-between gap-3 rounded-[18px] border border-border/60 bg-background/70 px-3 py-2.5">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {operationLabels[operation.operation_type] ?? operation.operation_type} · {operation.instrument_ticker}
                      </div>
                      <div className="text-xs text-muted-foreground">{formatDate(operation.date)} · {operation.account_name ?? "счет не указан"}</div>
                    </div>
                    <div className="text-right text-sm tabular-nums">
                      <div>{operation.quantity}</div>
                      <div className="text-xs text-muted-foreground">{formatCurrency(operation.amount_rub)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
