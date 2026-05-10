"use client"

import * as Dialog from "@radix-ui/react-dialog"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BarChart3, Coins, Landmark, LineChart, PencilLine, Plus, RefreshCw, Trash2, TrendingUp, X } from "lucide-react"
import { useMemo, useState, type FormEvent } from "react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { formatCurrency, formatDate } from "@/lib/formatters"
import {
  InvestmentService,
  type Instrument,
  type InstrumentPriceSnapshotPayload,
  type InstrumentPayload,
  type InstrumentType,
  type InvestmentAccount,
  type InvestmentAccountPayload,
  type InvestmentOperation,
  type InvestmentOperationPayload,
  type InvestmentOperationType,
  type InvestmentPortfolio,
  type InvestmentPortfolioPayload,
} from "@/services/investment-service"

const operationLabels: Record<InvestmentOperationType, string> = {
  buy: "Покупка",
  sell: "Продажа",
  transfer_instrument: "Перевод",
  correction: "Корректировка",
}

const accountTypeLabels: Record<string, string> = {
  exchange: "Биржа",
  broker: "Брокер",
  cold_wallet: "Холодный кошелек",
  manual: "Ручной счет",
}

type InvestmentDialogState =
  | { type: "portfolio"; mode: "create" | "edit"; item?: InvestmentPortfolio }
  | { type: "instrument"; mode: "create" | "edit"; item?: Instrument }
  | { type: "price"; mode: "create"; item?: Instrument }
  | { type: "account"; mode: "create" | "edit"; item?: InvestmentAccount }
  | { type: "operation"; mode: "create" | "edit"; item?: InvestmentOperation }
  | null

const INVESTMENT_QUERY_KEYS = [
  ["investment-overview"],
  ["investment-portfolios"],
  ["investment-instruments"],
  ["investment-accounts"],
  ["investment-operations"],
]

function parseFormNumber(value: string, fallback = 0) {
  const normalized = value.replace(/\s/g, "").replace(",", ".")
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : fallback
}

function formatInputNumber(value?: number | null) {
  if (value === undefined || value === null) {
    return ""
  }
  return String(value)
}

function formatPercent(value?: number | null) {
  if (value === undefined || value === null) {
    return "нет оценки"
  }
  return `${new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)}%`
}

function todayInputDate() {
  return new Date().toISOString().split("T")[0]
}

function getApiErrorMessage(error: unknown) {
  const data = (error as any)?.response?.data
  if (typeof data === "string") {
    return data
  }
  if (data?.detail) {
    return String(data.detail)
  }
  if (data && typeof data === "object") {
    const [field, value] = Object.entries(data)[0] ?? []
    if (field) {
      const message = Array.isArray(value) ? value.join(", ") : String(value)
      return `${field}: ${message}`
    }
  }
  return "Не удалось сохранить данные. Проверь заполнение формы."
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs uppercase tracking-[0.12em] text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

export default function InvestmentsPage() {
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<InvestmentDialogState>(null)
  const [dialogError, setDialogError] = useState("")

  const overviewQuery = useQuery({
    queryKey: ["investment-overview"],
    queryFn: InvestmentService.getOverview,
  })
  const portfoliosQuery = useQuery({
    queryKey: ["investment-portfolios"],
    queryFn: InvestmentService.getPortfolios,
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

  const invalidateInvestmentQueries = () =>
    Promise.all(INVESTMENT_QUERY_KEYS.map((queryKey) => queryClient.invalidateQueries({ queryKey })))

  const handleSaved = () => {
    setDialog(null)
    setDialogError("")
    void invalidateInvestmentQueries()
  }

  const savePortfolioMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: InvestmentPortfolioPayload | Partial<InvestmentPortfolioPayload> }) =>
      id ? InvestmentService.updatePortfolio(id, payload) : InvestmentService.createPortfolio(payload as InvestmentPortfolioPayload),
    onSuccess: handleSaved,
    onError: (error) => setDialogError(getApiErrorMessage(error)),
  })

  const saveInstrumentMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: InstrumentPayload | Partial<InstrumentPayload> }) =>
      id ? InvestmentService.updateInstrument(id, payload) : InvestmentService.createInstrument(payload as InstrumentPayload),
    onSuccess: handleSaved,
    onError: (error) => setDialogError(getApiErrorMessage(error)),
  })

  const savePriceMutation = useMutation({
    mutationFn: (payload: Partial<InstrumentPriceSnapshotPayload>) => InvestmentService.createPrice(payload),
    onSuccess: handleSaved,
    onError: (error) => setDialogError(getApiErrorMessage(error)),
  })

  const saveAccountMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: InvestmentAccountPayload | Partial<InvestmentAccountPayload> }) =>
      id ? InvestmentService.updateAccount(id, payload) : InvestmentService.createAccount(payload as InvestmentAccountPayload),
    onSuccess: handleSaved,
    onError: (error) => setDialogError(getApiErrorMessage(error)),
  })

  const saveOperationMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: Partial<InvestmentOperationPayload> }) =>
      id ? InvestmentService.updateOperation(id, payload) : InvestmentService.createOperation(payload),
    onSuccess: handleSaved,
    onError: (error) => setDialogError(getApiErrorMessage(error)),
  })

  const isLoading =
    overviewQuery.isLoading ||
    portfoliosQuery.isLoading ||
    instrumentsQuery.isLoading ||
    accountsQuery.isLoading ||
    operationsQuery.isLoading
  const isError =
    overviewQuery.isError ||
    portfoliosQuery.isError ||
    instrumentsQuery.isError ||
    accountsQuery.isError ||
    operationsQuery.isError

  if (isLoading) {
    return <FullPageLoader label="Загружаем портфель..." />
  }

  if (isError || !overviewQuery.data) {
    return (
      <EmptyState
        icon={TrendingUp}
        title="Портфель пока недоступен"
        description="Backend инвестиционного модуля не ответил. Проверь миграции и доступность API."
        action={<Button onClick={() => void invalidateInvestmentQueries()}>Повторить</Button>}
      />
    )
  }

  const overview = overviewQuery.data
  const portfolios = portfoliosQuery.data ?? []
  const instruments = instrumentsQuery.data ?? []
  const accounts = accountsQuery.data ?? []
  const operations = operationsQuery.data ?? []
  const activeInstruments = instruments.filter((instrument) => instrument.is_active)
  const currentPortfolio = overview.portfolio ?? portfolios.find((portfolio) => portfolio.is_default) ?? portfolios[0] ?? null
  const currentPortfolioAccounts = currentPortfolio ? accounts.filter((account) => account.portfolio === currentPortfolio.id) : []
  const visibleAccounts = currentPortfolioAccounts.filter((account) => !account.hidden)
  const canCreateOperation = Boolean(currentPortfolio && activeInstruments.length > 0 && currentPortfolioAccounts.length > 0)

  const openDialog = (nextDialog: InvestmentDialogState) => {
    setDialogError("")
    setDialog(nextDialog)
  }

  const handleDelete = async (kind: "portfolio" | "instrument" | "account" | "operation", id: string, label: string) => {
    if (!window.confirm(`Удалить ${label}?`)) {
      return
    }

    try {
      if (kind === "portfolio") {
        await InvestmentService.deletePortfolio(id)
      }
      if (kind === "instrument") {
        await InvestmentService.deleteInstrument(id)
      }
      if (kind === "account") {
        await InvestmentService.deleteAccount(id)
      }
      if (kind === "operation") {
        await InvestmentService.deleteOperation(id)
      }
      await invalidateInvestmentQueries()
    } catch (error) {
      window.alert(getApiErrorMessage(error))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Финансовые инструменты"
        title="Портфель"
        description="Криптовалюты, средняя покупка и зафиксированный финансовый результат. Денежные кошельки здесь не меняются автоматически."
        actions={
          <>
            <Button variant="outline" onClick={() => openDialog({ type: "portfolio", mode: "create" })}>
              <Plus className="mr-2 h-4 w-4" />
              Портфель
            </Button>
            <Button variant="outline" onClick={() => openDialog({ type: "instrument", mode: "create" })}>
              <Plus className="mr-2 h-4 w-4" />
              Инструмент
            </Button>
            <Button variant="outline" disabled={instruments.length === 0} onClick={() => openDialog({ type: "price", mode: "create", item: activeInstruments[0] ?? instruments[0] })}>
              <Plus className="mr-2 h-4 w-4" />
              Цена
            </Button>
            <Button variant="outline" disabled={!currentPortfolio} onClick={() => openDialog({ type: "account", mode: "create" })}>
              <Plus className="mr-2 h-4 w-4" />
              Счет
            </Button>
            <Button disabled={!canCreateOperation} onClick={() => openDialog({ type: "operation", mode: "create" })}>
              <Plus className="mr-2 h-4 w-4" />
              Операция
            </Button>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Текущая стоимость" value={formatCurrency(overview.current_value_rub)} hint={overview.valuation_complete ? "По последним ценам" : "Есть позиции без цены"} icon={Coins} variant="compact" />
        <StatCard label="Себестоимость" value={formatCurrency(overview.cost_basis_rub)} hint="Остаток позиций в RUB" icon={Landmark} variant="compact" />
        <StatCard label="Total P/L" value={formatCurrency(overview.total_pl_rub)} hint={`Доходность: ${formatPercent(overview.return_percent)}`} icon={LineChart} tone={overview.total_pl_rub < 0 ? "danger" : "positive"} variant="compact" />
        <StatCard label="Unrealized P/L" value={formatCurrency(overview.unrealized_pl_rub)} hint={`Realized: ${formatCurrency(overview.realized_pl_rub)}`} icon={BarChart3} tone={overview.unrealized_pl_rub < 0 ? "danger" : "positive"} variant="compact" />
      </div>

      {currentPortfolio ? (
        <Card>
          <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>Позиции</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                P0-версия считает количество, себестоимость, среднюю покупку и realized P/L. Текущие курсы и unrealized P/L будут следующим этапом.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{currentPortfolio.name}</Badge>
              <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "portfolio", mode: "edit", item: currentPortfolio })} aria-label="Редактировать портфель">
                <PencilLine className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {overview.positions.length === 0 ? (
              <EmptyState
                icon={Coins}
                title="Позиции еще не заведены"
                description="Создай инструмент, инвестиционный счет и операцию покупки. Эти данные не связаны с кошельками учета денег."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1080px] text-left text-sm">
                  <thead className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    <tr className="border-b border-border/70">
                      <th className="py-3 pr-4">Актив</th>
                      <th className="py-3 pr-4 text-right">Количество</th>
                      <th className="py-3 pr-4 text-right">Себестоимость</th>
                      <th className="py-3 pr-4 text-right">Средняя</th>
                      <th className="py-3 pr-4 text-right">Цена</th>
                      <th className="py-3 pr-4 text-right">Стоимость</th>
                      <th className="py-3 pr-4 text-right">Unrealized</th>
                      <th className="py-3 pr-4 text-right">Total P/L</th>
                      <th className="py-3 text-right">%</th>
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
                        <td className="py-3 pr-4 text-right tabular-nums">
                          {position.latest_price_rub === null || position.latest_price_rub === undefined ? (
                            <Button variant="ghost" size="sm" onClick={() => openDialog({ type: "price", mode: "create", item: instruments.find((item) => item.id === position.instrument_id) })}>
                              Добавить
                            </Button>
                          ) : (
                            <div>
                              <div>{formatCurrency(position.latest_price_rub)}</div>
                              <div className="text-xs text-muted-foreground">{position.latest_price_at ? formatDate(position.latest_price_at) : ""}</div>
                            </div>
                          )}
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums">
                          {position.current_value_rub === null || position.current_value_rub === undefined ? "нет цены" : formatCurrency(position.current_value_rub)}
                        </td>
                        <td className={position.unrealized_pl_rub !== undefined && position.unrealized_pl_rub !== null && position.unrealized_pl_rub < 0 ? "py-3 pr-4 text-right text-destructive tabular-nums" : "py-3 pr-4 text-right text-emerald-600 tabular-nums"}>
                          {position.unrealized_pl_rub === null || position.unrealized_pl_rub === undefined ? "нет цены" : formatCurrency(position.unrealized_pl_rub)}
                        </td>
                        <td className={position.total_pl_rub < 0 ? "py-3 pr-4 text-right text-destructive tabular-nums" : "py-3 pr-4 text-right text-emerald-600 tabular-nums"}>
                          {formatCurrency(position.total_pl_rub)}
                        </td>
                        <td className="py-3 text-right tabular-nums">
                          {formatPercent(position.return_percent)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <EmptyState
          icon={Landmark}
          title="Нужен первый портфель"
          description="Создай портфель, затем добавь инвестиционные счета, инструменты и операции."
          action={<Button onClick={() => openDialog({ type: "portfolio", mode: "create" })}>Создать портфель</Button>}
        />
      )}

      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Справочники</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Coins className="h-4 w-4 text-primary" />
                  Инструменты
                </div>
                <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "instrument", mode: "create" })} aria-label="Добавить инструмент">
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                {instruments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Пока пусто.</p>
                ) : (
                  instruments.map((instrument) => (
                    <div key={instrument.id} className="flex items-center justify-between gap-2 rounded-2xl bg-card px-3 py-2 text-sm">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{instrument.ticker}</div>
                        <div className="truncate text-xs text-muted-foreground">{instrument.name}</div>
                      </div>
                      <div className="flex items-center gap-1">
                        <Badge variant={instrument.is_active ? "default" : "outline"}>{instrument.type}</Badge>
                        <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "price", mode: "create", item: instrument })} aria-label="Добавить цену">
                          <LineChart className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "instrument", mode: "edit", item: instrument })} aria-label="Редактировать инструмент">
                          <PencilLine className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => void handleDelete("instrument", instrument.id, instrument.ticker)} aria-label="Удалить инструмент">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Landmark className="h-4 w-4 text-primary" />
                  Счета
                </div>
                <Button variant="ghost" size="icon" disabled={!currentPortfolio} onClick={() => openDialog({ type: "account", mode: "create" })} aria-label="Добавить счет">
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
              <div className="mt-3 space-y-2">
                {currentPortfolioAccounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Пока пусто.</p>
                ) : (
                  currentPortfolioAccounts.map((account) => (
                    <div key={account.id} className="flex items-center justify-between gap-2 rounded-2xl bg-card px-3 py-2 text-sm">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{account.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {account.currency} · {accountTypeLabels[account.type] ?? account.type}
                          {account.hidden ? " · скрыт" : ""}
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "account", mode: "edit", item: account })} aria-label="Редактировать счет">
                          <PencilLine className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => void handleDelete("account", account.id, account.name)} aria-label="Удалить счет">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
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
            <div className="flex items-center gap-1">
              <Button variant="outline" size="icon" onClick={() => void operationsQuery.refetch()} aria-label="Обновить">
                <RefreshCw className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" disabled={!canCreateOperation} onClick={() => openDialog({ type: "operation", mode: "create" })} aria-label="Добавить операцию">
                <Plus className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {operations.length === 0 ? (
              <p className="text-sm text-muted-foreground">Операций пока нет.</p>
            ) : (
              <div className="space-y-2">
                {operations.slice(0, 12).map((operation) => (
                  <div key={operation.id} className="flex items-center justify-between gap-3 rounded-[18px] border border-border/60 bg-background/70 px-3 py-2.5">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">
                        {operationLabels[operation.operation_type] ?? operation.operation_type} · {operation.instrument_ticker}
                      </div>
                      <div className="text-xs text-muted-foreground">{formatDate(operation.date)} · {operation.account_name ?? "счет не указан"}</div>
                    </div>
                    <div className="flex items-center gap-1">
                      <div className="mr-2 text-right text-sm tabular-nums">
                        <div>{operation.quantity}</div>
                        <div className="text-xs text-muted-foreground">{formatCurrency(operation.amount_rub)}</div>
                      </div>
                      <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "operation", mode: "edit", item: operation })} aria-label="Редактировать операцию">
                        <PencilLine className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => void handleDelete("operation", operation.id, operation.number ?? operation.instrument_ticker ?? "операцию")} aria-label="Удалить операцию">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <InvestmentCrudDialog
        dialog={dialog}
        error={dialogError}
        portfolios={portfolios}
        currentPortfolio={currentPortfolio}
        accounts={currentPortfolioAccounts}
        instruments={instruments}
        onOpenChange={(open) => {
          if (!open) {
            setDialog(null)
            setDialogError("")
          }
        }}
        onSavePortfolio={(id, payload) => savePortfolioMutation.mutate({ id, payload })}
        onSaveInstrument={(id, payload) => saveInstrumentMutation.mutate({ id, payload })}
        onSavePrice={(payload) => savePriceMutation.mutate(payload)}
        onSaveAccount={(id, payload) => saveAccountMutation.mutate({ id, payload })}
        onSaveOperation={(id, payload) => saveOperationMutation.mutate({ id, payload })}
        isSaving={
          savePortfolioMutation.isPending ||
          saveInstrumentMutation.isPending ||
          savePriceMutation.isPending ||
          saveAccountMutation.isPending ||
          saveOperationMutation.isPending
        }
      />
    </div>
  )
}

function InvestmentCrudDialog({
  dialog,
  error,
  portfolios,
  currentPortfolio,
  accounts,
  instruments,
  onOpenChange,
  onSavePortfolio,
  onSaveInstrument,
  onSavePrice,
  onSaveAccount,
  onSaveOperation,
  isSaving,
}: {
  dialog: InvestmentDialogState
  error: string
  portfolios: InvestmentPortfolio[]
  currentPortfolio: InvestmentPortfolio | null
  accounts: InvestmentAccount[]
  instruments: Instrument[]
  onOpenChange: (open: boolean) => void
  onSavePortfolio: (id: string | undefined, payload: InvestmentPortfolioPayload | Partial<InvestmentPortfolioPayload>) => void
  onSaveInstrument: (id: string | undefined, payload: InstrumentPayload | Partial<InstrumentPayload>) => void
  onSavePrice: (payload: Partial<InstrumentPriceSnapshotPayload>) => void
  onSaveAccount: (id: string | undefined, payload: InvestmentAccountPayload | Partial<InvestmentAccountPayload>) => void
  onSaveOperation: (id: string | undefined, payload: Partial<InvestmentOperationPayload>) => void
  isSaving: boolean
}) {
  const title = dialog?.mode === "edit" ? "Редактирование" : "Создание"

  return (
    <Dialog.Root open={!!dialog} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(calc(100vw-18px),980px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[28px] border border-border/70 bg-background shadow-[0_35px_120px_-45px_rgba(15,23,42,0.85)]">
          <div className="flex items-start justify-between gap-4 border-b border-border/70 px-5 py-4">
            <div>
              <Dialog.Title className="text-xl font-semibold tracking-[-0.03em] text-foreground">
                {title}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-muted-foreground">
                Данные инвестиционного модуля не меняют кошельки и бюджет учета денег.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Закрыть">
                <X className="h-5 w-5" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="max-h-[calc(92vh-88px)] overflow-y-auto p-5">
            {error ? <div className="mb-4 rounded-2xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div> : null}

            {dialog?.type === "portfolio" ? (
              <PortfolioForm portfolio={dialog.item} isSaving={isSaving} onSubmit={(payload) => onSavePortfolio(dialog.item?.id, payload)} />
            ) : null}

            {dialog?.type === "instrument" ? (
              <InstrumentForm instrument={dialog.item} isSaving={isSaving} onSubmit={(payload) => onSaveInstrument(dialog.item?.id, payload)} />
            ) : null}

            {dialog?.type === "price" ? (
              <PriceSnapshotForm
                instrument={dialog.item}
                instruments={instruments}
                isSaving={isSaving}
                onSubmit={onSavePrice}
              />
            ) : null}

            {dialog?.type === "account" ? (
              <AccountForm
                account={dialog.item}
                portfolios={portfolios}
                currentPortfolio={currentPortfolio}
                isSaving={isSaving}
                onSubmit={(payload) => onSaveAccount(dialog.item?.id, payload)}
              />
            ) : null}

            {dialog?.type === "operation" ? (
              <OperationForm
                operation={dialog.item}
                currentPortfolio={currentPortfolio}
                accounts={accounts}
                instruments={instruments}
                isSaving={isSaving}
                onSubmit={(payload) => onSaveOperation(dialog.item?.id, payload)}
              />
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function PortfolioForm({
  portfolio,
  isSaving,
  onSubmit,
}: {
  portfolio?: InvestmentPortfolio
  isSaving: boolean
  onSubmit: (payload: InvestmentPortfolioPayload | Partial<InvestmentPortfolioPayload>) => void
}) {
  const [name, setName] = useState(portfolio?.name ?? "Основной портфель")
  const [isDefault, setIsDefault] = useState(portfolio?.is_default ?? true)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      name: name.trim(),
      is_default: isDefault,
      project: portfolio?.project ?? null,
    })
  }

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <FormField label="Название портфеля">
        <Input value={name} onChange={(event) => setName(event.target.value)} required placeholder="Например: Крипта" />
      </FormField>
      <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm">
        <Checkbox checked={isDefault} onCheckedChange={(checked) => setIsDefault(checked === true)} />
        Использовать по умолчанию
      </label>
      <Button type="submit" disabled={isSaving || !name.trim()}>
        {isSaving ? "Сохраняем..." : "Сохранить портфель"}
      </Button>
    </form>
  )
}

function InstrumentForm({
  instrument,
  isSaving,
  onSubmit,
}: {
  instrument?: Instrument
  isSaving: boolean
  onSubmit: (payload: InstrumentPayload | Partial<InstrumentPayload>) => void
}) {
  const [type, setType] = useState<InstrumentType>(instrument?.type ?? "crypto")
  const [ticker, setTicker] = useState(instrument?.ticker ?? "")
  const [name, setName] = useState(instrument?.name ?? "")
  const [providerSymbol, setProviderSymbol] = useState(instrument?.provider_symbol ?? "")
  const [quoteCurrency, setQuoteCurrency] = useState(instrument?.quote_currency ?? "USD")
  const [precision, setPrecision] = useState(String(instrument?.precision ?? 8))
  const [isActive, setIsActive] = useState(instrument?.is_active ?? true)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      type,
      ticker: ticker.trim().toUpperCase(),
      name: name.trim(),
      provider_symbol: providerSymbol.trim() || ticker.trim().toUpperCase(),
      quote_currency: quoteCurrency.trim().toUpperCase() || "USD",
      precision: Math.max(0, Math.trunc(parseFormNumber(precision, 8))),
      is_active: isActive,
    })
  }

  return (
    <form className="grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
      <FormField label="Тип">
        <Select value={type} onValueChange={(value) => setType(value as InstrumentType)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="crypto">Криптовалюта</SelectItem>
            <SelectItem value="stock">Акция</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Тикер">
        <Input value={ticker} onChange={(event) => setTicker(event.target.value)} required placeholder="BTC" />
      </FormField>
      <FormField label="Название">
        <Input value={name} onChange={(event) => setName(event.target.value)} required placeholder="Bitcoin" />
      </FormField>
      <FormField label="Символ у провайдера">
        <Input value={providerSymbol} onChange={(event) => setProviderSymbol(event.target.value)} placeholder="BTCUSDT" />
      </FormField>
      <FormField label="Валюта котировки">
        <Input value={quoteCurrency} onChange={(event) => setQuoteCurrency(event.target.value)} placeholder="USD" />
      </FormField>
      <FormField label="Точность">
        <Input value={precision} onChange={(event) => setPrecision(event.target.value)} inputMode="numeric" />
      </FormField>
      <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm md:col-span-2">
        <Checkbox checked={isActive} onCheckedChange={(checked) => setIsActive(checked === true)} />
        Активен для новых операций
      </label>
      <div className="md:col-span-2">
        <Button type="submit" disabled={isSaving || !ticker.trim() || !name.trim()}>
          {isSaving ? "Сохраняем..." : "Сохранить инструмент"}
        </Button>
      </div>
    </form>
  )
}

function PriceSnapshotForm({
  instrument,
  instruments,
  isSaving,
  onSubmit,
}: {
  instrument?: Instrument
  instruments: Instrument[]
  isSaving: boolean
  onSubmit: (payload: Partial<InstrumentPriceSnapshotPayload>) => void
}) {
  const [instrumentId, setInstrumentId] = useState(instrument?.id ?? instruments[0]?.id ?? "")
  const selectedInstrument = instruments.find((item) => item.id === instrumentId)
  const [capturedAt, setCapturedAt] = useState(todayInputDate())
  const [price, setPrice] = useState("")
  const [priceCurrency, setPriceCurrency] = useState(selectedInstrument?.quote_currency ?? "USD")
  const [fxRateToRub, setFxRateToRub] = useState(priceCurrency.toUpperCase() === "RUB" ? "1" : "")
  const [priceRub, setPriceRub] = useState("")
  const [source, setSource] = useState("manual")

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      instrument: instrumentId,
      captured_at: capturedAt,
      price: parseFormNumber(price),
      price_currency: priceCurrency.trim().toUpperCase() || selectedInstrument?.quote_currency || "USD",
      fx_rate_to_rub: parseFormNumber(fxRateToRub, 1),
      price_rub: priceRub.trim() ? parseFormNumber(priceRub) : undefined,
      source: source.trim() || "manual",
    })
  }

  return (
    <form className="grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
      <FormField label="Инструмент">
        <Select
          value={instrumentId}
          onValueChange={(value) => {
            setInstrumentId(value)
            const nextInstrument = instruments.find((item) => item.id === value)
            if (nextInstrument) {
              setPriceCurrency(nextInstrument.quote_currency)
              setFxRateToRub(nextInstrument.quote_currency.toUpperCase() === "RUB" ? "1" : fxRateToRub)
            }
          }}
        >
          <SelectTrigger>
            <SelectValue placeholder="Выбери инструмент" />
          </SelectTrigger>
          <SelectContent>
            {instruments.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.ticker} · {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Дата цены">
        <Input type="date" value={capturedAt} onChange={(event) => setCapturedAt(event.target.value)} required />
      </FormField>
      <FormField label="Цена">
        <Input value={price} onChange={(event) => setPrice(event.target.value)} required inputMode="decimal" placeholder="Например: 62000" />
      </FormField>
      <FormField label="Валюта цены">
        <Input value={priceCurrency} onChange={(event) => setPriceCurrency(event.target.value)} placeholder="USD" />
      </FormField>
      <FormField label="Курс к RUB">
        <Input value={fxRateToRub} onChange={(event) => setFxRateToRub(event.target.value)} required inputMode="decimal" placeholder="Например: 92.5" />
      </FormField>
      <FormField label="Цена в RUB">
        <Input value={priceRub} onChange={(event) => setPriceRub(event.target.value)} inputMode="decimal" placeholder="Можно оставить пустым" />
      </FormField>
      <FormField label="Источник">
        <Input value={source} onChange={(event) => setSource(event.target.value)} placeholder="manual" />
      </FormField>
      <div className="flex items-end">
        <Button type="submit" disabled={isSaving || !instrumentId || !price.trim() || !fxRateToRub.trim()}>
          {isSaving ? "Сохраняем..." : "Сохранить цену"}
        </Button>
      </div>
    </form>
  )
}

function AccountForm({
  account,
  portfolios,
  currentPortfolio,
  isSaving,
  onSubmit,
}: {
  account?: InvestmentAccount
  portfolios: InvestmentPortfolio[]
  currentPortfolio: InvestmentPortfolio | null
  isSaving: boolean
  onSubmit: (payload: InvestmentAccountPayload | Partial<InvestmentAccountPayload>) => void
}) {
  const defaultPortfolioId = account?.portfolio ?? currentPortfolio?.id ?? portfolios[0]?.id ?? ""
  const [portfolio, setPortfolio] = useState(defaultPortfolioId)
  const [name, setName] = useState(account?.name ?? "")
  const [type, setType] = useState(account?.type ?? "manual")
  const [currency, setCurrency] = useState(account?.currency ?? "RUB")
  const [hidden, setHidden] = useState(account?.hidden ?? false)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      portfolio,
      name: name.trim(),
      type,
      currency: currency.trim().toUpperCase() || "RUB",
      hidden,
    })
  }

  return (
    <form className="grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
      <FormField label="Портфель">
        <Select value={portfolio} onValueChange={setPortfolio}>
          <SelectTrigger>
            <SelectValue placeholder="Выбери портфель" />
          </SelectTrigger>
          <SelectContent>
            {portfolios.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Тип счета">
        <Select value={type} onValueChange={setType}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="exchange">Биржа</SelectItem>
            <SelectItem value="broker">Брокер</SelectItem>
            <SelectItem value="cold_wallet">Холодный кошелек</SelectItem>
            <SelectItem value="manual">Ручной счет</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Название">
        <Input value={name} onChange={(event) => setName(event.target.value)} required placeholder="Binance" />
      </FormField>
      <FormField label="Валюта">
        <Input value={currency} onChange={(event) => setCurrency(event.target.value)} placeholder="RUB" />
      </FormField>
      <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm md:col-span-2">
        <Checkbox checked={hidden} onCheckedChange={(checked) => setHidden(checked === true)} />
        Скрывать в быстрых списках
      </label>
      <div className="md:col-span-2">
        <Button type="submit" disabled={isSaving || !portfolio || !name.trim()}>
          {isSaving ? "Сохраняем..." : "Сохранить счет"}
        </Button>
      </div>
    </form>
  )
}

function OperationForm({
  operation,
  currentPortfolio,
  accounts,
  instruments,
  isSaving,
  onSubmit,
}: {
  operation?: InvestmentOperation
  currentPortfolio: InvestmentPortfolio | null
  accounts: InvestmentAccount[]
  instruments: Instrument[]
  isSaving: boolean
  onSubmit: (payload: Partial<InvestmentOperationPayload>) => void
}) {
  const activeInstruments = useMemo(() => instruments.filter((instrument) => instrument.is_active || instrument.id === operation?.instrument), [instruments, operation?.instrument])
  const [date, setDate] = useState(operation?.date ?? todayInputDate())
  const [operationType, setOperationType] = useState<InvestmentOperationType>(operation?.operation_type ?? "buy")
  const [account, setAccount] = useState(operation?.account ?? accounts[0]?.id ?? "")
  const [accountTo, setAccountTo] = useState(operation?.account_to ?? "")
  const [instrument, setInstrument] = useState(operation?.instrument ?? activeInstruments[0]?.id ?? "")
  const [quantity, setQuantity] = useState(formatInputNumber(operation?.quantity))
  const [price, setPrice] = useState(formatInputNumber(operation?.price))
  const [priceCurrency, setPriceCurrency] = useState(operation?.price_currency ?? "RUB")
  const [amount, setAmount] = useState(formatInputNumber(operation?.amount))
  const [amountCurrency, setAmountCurrency] = useState(operation?.amount_currency ?? "RUB")
  const [amountRub, setAmountRub] = useState(formatInputNumber(operation?.amount_rub))
  const [fxRateToRub, setFxRateToRub] = useState(formatInputNumber(operation?.fx_rate_to_rub ?? 1))
  const [feeAmount, setFeeAmount] = useState(formatInputNumber(operation?.fee_amount ?? 0))
  const [feeCurrency, setFeeCurrency] = useState(operation?.fee_currency ?? "RUB")
  const [feeRub, setFeeRub] = useState(formatInputNumber(operation?.fee_rub ?? 0))
  const [posted, setPosted] = useState(operation?.posted ?? true)
  const [deleted, setDeleted] = useState(operation?.deleted ?? false)
  const [comment, setComment] = useState(operation?.comment ?? "")

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      date,
      portfolio: operation?.portfolio ?? currentPortfolio?.id ?? "",
      account,
      account_to: operationType === "transfer_instrument" ? accountTo : null,
      instrument,
      operation_type: operationType,
      quantity: parseFormNumber(quantity),
      price: price.trim() ? parseFormNumber(price) : undefined,
      price_currency: priceCurrency.trim().toUpperCase() || "RUB",
      amount: amount.trim() ? parseFormNumber(amount) : undefined,
      amount_currency: amountCurrency.trim().toUpperCase() || "RUB",
      amount_rub: parseFormNumber(amountRub),
      fx_rate_to_rub: parseFormNumber(fxRateToRub, 1),
      fee_amount: parseFormNumber(feeAmount),
      fee_currency: feeCurrency.trim().toUpperCase() || "RUB",
      fee_rub: parseFormNumber(feeRub),
      comment: comment.trim(),
      posted,
      deleted,
    })
  }

  const needsAmount = operationType === "buy" || operationType === "sell"

  return (
    <form className="grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
      <FormField label="Дата">
        <Input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
      </FormField>
      <FormField label="Тип операции">
        <Select value={operationType} onValueChange={(value) => setOperationType(value as InvestmentOperationType)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="buy">Покупка</SelectItem>
            <SelectItem value="sell">Продажа</SelectItem>
            <SelectItem value="transfer_instrument">Перевод инструмента</SelectItem>
            <SelectItem value="correction">Корректировка</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Счет">
        <Select value={account} onValueChange={setAccount}>
          <SelectTrigger>
            <SelectValue placeholder="Выбери счет" />
          </SelectTrigger>
          <SelectContent>
            {accounts.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Счет-получатель">
        <Select value={accountTo || "none"} disabled={operationType !== "transfer_instrument"} onValueChange={(value) => setAccountTo(value === "none" ? "" : value)}>
          <SelectTrigger>
            <SelectValue placeholder="Только для перевода" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Не выбран</SelectItem>
            {accounts
              .filter((item) => item.id !== account)
              .map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.name}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Инструмент">
        <Select value={instrument} onValueChange={setInstrument}>
          <SelectTrigger>
            <SelectValue placeholder="Выбери инструмент" />
          </SelectTrigger>
          <SelectContent>
            {activeInstruments.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.ticker} · {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Количество">
        <Input value={quantity} onChange={(event) => setQuantity(event.target.value)} required inputMode="decimal" placeholder="0.01" />
      </FormField>
      <FormField label="Цена">
        <Input value={price} onChange={(event) => setPrice(event.target.value)} required={needsAmount} inputMode="decimal" placeholder="Цена за единицу" />
      </FormField>
      <FormField label="Валюта цены">
        <Input value={priceCurrency} onChange={(event) => setPriceCurrency(event.target.value)} placeholder="RUB" />
      </FormField>
      <FormField label="Сумма">
        <Input value={amount} onChange={(event) => setAmount(event.target.value)} inputMode="decimal" placeholder="В валюте операции" />
      </FormField>
      <FormField label="Валюта суммы">
        <Input value={amountCurrency} onChange={(event) => setAmountCurrency(event.target.value)} placeholder="RUB" />
      </FormField>
      <FormField label="Сумма RUB">
        <Input value={amountRub} onChange={(event) => setAmountRub(event.target.value)} required={needsAmount} inputMode="decimal" placeholder="Итог в рублях" />
      </FormField>
      <FormField label="Курс к RUB">
        <Input value={fxRateToRub} onChange={(event) => setFxRateToRub(event.target.value)} inputMode="decimal" />
      </FormField>
      <FormField label="Комиссия">
        <Input value={feeAmount} onChange={(event) => setFeeAmount(event.target.value)} inputMode="decimal" />
      </FormField>
      <FormField label="Валюта комиссии">
        <Input value={feeCurrency} onChange={(event) => setFeeCurrency(event.target.value)} placeholder="RUB" />
      </FormField>
      <FormField label="Комиссия RUB">
        <Input value={feeRub} onChange={(event) => setFeeRub(event.target.value)} inputMode="decimal" />
      </FormField>
      <div />
      <div className="md:col-span-2">
        <FormField label="Комментарий">
          <Textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} />
        </FormField>
      </div>
      <div className="flex flex-wrap gap-3 md:col-span-2">
        <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm">
          <Checkbox checked={posted} onCheckedChange={(checked) => setPosted(checked === true)} />
          Проведена
        </label>
        <label className="flex items-center gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm">
          <Checkbox checked={deleted} onCheckedChange={(checked) => setDeleted(checked === true)} />
          Помечена на удаление
        </label>
      </div>
      <div className="md:col-span-2">
        <Button
          type="submit"
          disabled={
            isSaving ||
            !currentPortfolio ||
            !account ||
            !instrument ||
            !quantity.trim() ||
            (operationType === "transfer_instrument" && !accountTo) ||
            (needsAmount && (!price.trim() || !amountRub.trim()))
          }
        >
          {isSaving ? "Сохраняем..." : "Сохранить операцию"}
        </Button>
      </div>
    </form>
  )
}
