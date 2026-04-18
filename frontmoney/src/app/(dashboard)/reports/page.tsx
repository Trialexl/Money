"use client"

import { useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ResponsiveBar } from "@nivo/bar"
import { ResponsiveLine } from "@nivo/line"
import { ResponsivePie } from "@nivo/pie"
import {
  BarChart3,
  Landmark,
  TrendingDown,
  TrendingUp,
  Wallet2,
} from "lucide-react"

import ExportReportButtons from "@/components/reports/export-report-buttons"
import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { exportFormatters } from "@/lib/export-utils"
import { formatCurrency, formatDate, formatDateForInput } from "@/lib/formatters"
import { DashboardService, type DashboardWalletSummary } from "@/services/dashboard-service"
import { ReportService, type BudgetReportSummary, type CashFlowReportDetail, type CashFlowReportMonth } from "@/services/report-service"

type TimelineMode = "daily" | "monthly"
type RangePreset = "week" | "month" | "quarter" | "year" | "ytd" | null

type BudgetExecutionRow = {
  key: string
  name: string
  type: "income" | "expense"
  budgetAmount: number
  actualAmount: number
  difference: number
  executionPercent: number
}

type TimelineRow = {
  key: string
  label: string
  income: number
  expense: number
  net: number
}

type WalletRow = {
  id: string
  name: string
  balance: number
  share: number
}

type CategoryRow = {
  id: string
  name: string
  amount: number
  percentage: number
}

function getDateKey(value?: string) {
  return value ? value.slice(0, 10) : ""
}

function getMonthKey(value: string) {
  return getDateKey(value).slice(0, 7)
}

function formatMonthLabel(value: string) {
  return new Date(`${value}-01`).toLocaleDateString("ru-RU", {
    month: "short",
    year: "numeric",
  })
}

function shiftDays(days: number) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date
}

function renderNoData(title: string, description: string) {
  return (
    <Card>
      <CardContent className="py-16 text-center">
        <h3 className="text-lg font-semibold tracking-[-0.03em]">{title}</h3>
        <p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  )
}

export default function ReportsPage() {
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("daily")
  const [selectedPreset, setSelectedPreset] = useState<RangePreset>("month")
  const [dateFrom, setDateFrom] = useState(formatDateForInput(shiftDays(-30)))
  const [dateTo, setDateTo] = useState(formatDateForInput())
  const cashFlowChartRef = useRef<HTMLDivElement>(null)
  const walletChartRef = useRef<HTMLDivElement>(null)
  const categoryChartRef = useRef<HTMLDivElement>(null)
  const budgetIncomeChartRef = useRef<HTMLDivElement>(null)
  const budgetExpenseChartRef = useRef<HTMLDivElement>(null)

  const reportsQuery = useQuery({
    queryKey: ["reports-analytics", { dateFrom, dateTo }],
    staleTime: 60_000,
    queryFn: async () => {
      const [cashFlow, budgetIncome, budgetExpense, overview] = await Promise.all([
        ReportService.getCashFlowReport({ dateFrom, dateTo }),
        ReportService.getBudgetIncomeReport({ dateFrom, dateTo }),
        ReportService.getBudgetExpenseReport({ dateFrom, dateTo }),
        DashboardService.getOverview({ date: dateTo, hideHiddenWallets: true }),
      ])

      return {
        cashFlow,
        budgetIncome,
        budgetExpense,
        overview,
      }
    },
  })

  const setPresetRange = (preset: Exclude<RangePreset, null>) => {
    const today = new Date()
    const from = new Date(today)

    if (preset === "week") {
      from.setDate(today.getDate() - 7)
    }

    if (preset === "month") {
      from.setMonth(today.getMonth() - 1)
    }

    if (preset === "quarter") {
      from.setMonth(today.getMonth() - 3)
    }

    if (preset === "year") {
      from.setFullYear(today.getFullYear() - 1)
    }

    if (preset === "ytd") {
      from.setMonth(0, 1)
    }

    setDateFrom(formatDateForInput(from))
    setDateTo(formatDateForInput(today))
    setSelectedPreset(preset)
  }

  if (reportsQuery.isLoading) {
    return <FullPageLoader label="Собираем аналитические срезы..." />
  }

  if (reportsQuery.isError || !reportsQuery.data) {
    return (
      <EmptyState
        icon={BarChart3}
        title="Не удалось загрузить отчеты"
        description="Аналитический слой сейчас недоступен. Проверь backend API и попробуй снова."
        action={<Button onClick={() => reportsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const { cashFlow, budgetIncome, budgetExpense, overview } = reportsQuery.data
  const incomeTotal = cashFlow.totals.income
  const expenseTotal = cashFlow.totals.expense
  const netTotal = incomeTotal - expenseTotal
  const plannedBudgetCount = budgetExpense.summary.length
  const includedExpenseTotal = budgetExpense.totals.actual

  const timelineMap = new Map<string, TimelineRow>()

  if (timelineMode === "daily") {
    cashFlow.details.forEach((detail: CashFlowReportDetail) => {
      const key = getDateKey(detail.period)
      const label = formatDate(key)
      const row = timelineMap.get(key) || { key, label, income: 0, expense: 0, net: 0 }
      row.income += detail.income
      row.expense += detail.expense
      row.net += detail.income - detail.expense
      timelineMap.set(key, row)
    })
  } else {
    cashFlow.months.forEach((month: CashFlowReportMonth) => {
      const key = getMonthKey(month.period)
      const label = formatMonthLabel(key)
      const row = timelineMap.get(key) || { key, label, income: 0, expense: 0, net: 0 }
      row.income += month.income
      row.expense += month.expense
      row.net += month.income - month.expense
      timelineMap.set(key, row)
    })
  }

  const timelineRows: TimelineRow[] = Array.from(timelineMap.values()).sort((left: TimelineRow, right: TimelineRow) => left.key.localeCompare(right.key))
  let runningNet = 0
  const cumulativeLineData = timelineRows.map((row: TimelineRow) => {
    runningNet += row.net
    return { x: row.label, y: runningNet }
  })

  const cashFlowExportRows = timelineRows.map((row: TimelineRow) => ({
    period: row.label,
    income: row.income,
    expense: row.expense,
    net: row.net,
  }))

  const totalAbsoluteBalance = overview.wallets.reduce(
    (sum: number, wallet: DashboardWalletSummary) => sum + Math.abs(wallet.balance),
    0
  )
  const walletRows: WalletRow[] = overview.wallets
    .map((wallet: DashboardWalletSummary) => ({
      id: wallet.wallet_id,
      name: wallet.wallet_name,
      balance: wallet.balance,
      share: totalAbsoluteBalance > 0 ? (Math.abs(wallet.balance) / totalAbsoluteBalance) * 100 : 0,
    }))
    .sort((left: WalletRow, right: WalletRow) => right.balance - left.balance)
  const positiveWalletRows = walletRows.filter((wallet: WalletRow) => wallet.balance > 0)
  const totalWalletBalance = walletRows.reduce((sum: number, wallet: WalletRow) => sum + wallet.balance, 0)
  const positiveWalletBalance = positiveWalletRows.reduce((sum: number, wallet: WalletRow) => sum + wallet.balance, 0)
  const negativeWalletBalance = walletRows.filter((wallet: WalletRow) => wallet.balance < 0).reduce((sum: number, wallet: WalletRow) => sum + wallet.balance, 0)
  const dominantWallet = walletRows[0] || null

  const walletExportRows = walletRows.map((wallet: WalletRow) => ({
    name: wallet.name,
    balance: wallet.balance,
    share: wallet.share,
  }))

  const categoryTotals = new Map<string, CategoryRow>()
  cashFlow.details.forEach((detail: CashFlowReportDetail) => {
    if (detail.expense <= 0) {
      return
    }

    const key = detail.cash_flow_item_id || detail.cash_flow_item_name || "unknown"
    const item = categoryTotals.get(key) || {
      id: key,
      name: detail.cash_flow_item_name || "Неизвестная статья",
      amount: 0,
      percentage: 0,
    }
    item.amount += detail.expense
    categoryTotals.set(key, item)
  })

  const categoryRows: CategoryRow[] = Array.from(categoryTotals.values())
    .sort((left: CategoryRow, right: CategoryRow) => right.amount - left.amount)
    .map((item: CategoryRow) => ({
      ...item,
      percentage: expenseTotal > 0 ? (item.amount / expenseTotal) * 100 : 0,
    }))
  const topCategoryRows = categoryRows.slice(0, 8)
  const topExpenseCategory = categoryRows[0] || null
  const categoriesExportRows = categoryRows.map((category: CategoryRow) => ({
    name: category.name,
    amount: category.amount,
    percentage: category.percentage,
  }))

  const budgetExecutionMap = new Map<string, BudgetExecutionRow>()

  budgetIncome.summary.forEach((summaryRow: BudgetReportSummary) => {
    const key = `income:${summaryRow.cash_flow_item_id || summaryRow.cash_flow_item_name || "unknown"}`
    const budgetRow = budgetExecutionMap.get(key) || {
      key,
      name: summaryRow.cash_flow_item_name || "Неизвестная статья",
      type: "income" as const,
      budgetAmount: 0,
      actualAmount: 0,
      difference: 0,
      executionPercent: 0,
    }
    budgetRow.budgetAmount += summaryRow.budget
    budgetRow.actualAmount += summaryRow.actual
    budgetRow.difference += summaryRow.balance
    budgetExecutionMap.set(key, budgetRow)
  })

  budgetExpense.summary.forEach((row: BudgetReportSummary) => {
    const key = `expense:${row.cash_flow_item_id || row.cash_flow_item_name || "unknown"}`
    const budgetRow = budgetExecutionMap.get(key) || {
      key,
      name: row.cash_flow_item_name || "Неизвестная статья",
      type: "expense" as const,
      budgetAmount: 0,
      actualAmount: 0,
      difference: 0,
      executionPercent: 0,
    }
    budgetRow.budgetAmount += row.budget
    budgetRow.actualAmount += row.actual
    budgetRow.difference += row.balance
    budgetExecutionMap.set(key, budgetRow)
  })

  const budgetExecutionRows = Array.from(budgetExecutionMap.values())
    .map((row: BudgetExecutionRow) => {
      const executionPercent = row.budgetAmount > 0 ? (row.actualAmount / row.budgetAmount) * 100 : row.actualAmount > 0 ? 100 : 0
      return {
        ...row,
        executionPercent,
      }
    })
    .sort((left: BudgetExecutionRow, right: BudgetExecutionRow) => right.budgetAmount - left.budgetAmount)

  const incomeBudgetRows = budgetExecutionRows.filter((row: BudgetExecutionRow) => row.type === "income")
  const expenseBudgetRows = budgetExecutionRows.filter((row: BudgetExecutionRow) => row.type === "expense")
  const totalBudgetIncome = budgetIncome.totals.budget
  const totalBudgetExpense = budgetExpense.totals.budget
  const totalActualIncome = budgetIncome.totals.actual
  const totalActualExpense = budgetExpense.totals.actual
  const incomeBudgetChartRows = incomeBudgetRows.slice(0, 8).map((row: BudgetExecutionRow) => ({ name: row.name, budget: row.budgetAmount, actual: row.actualAmount }))
  const expenseBudgetChartRows = expenseBudgetRows.slice(0, 8).map((row: BudgetExecutionRow) => ({ name: row.name, budget: row.budgetAmount, actual: row.actualAmount }))

  const budgetExportRows = budgetExecutionRows.map((row: BudgetExecutionRow) => ({
    name: row.name,
    type: row.type === "income" ? "Доход" : "Расход",
    budgetAmount: row.budgetAmount,
    actualAmount: row.actualAmount,
    difference: row.difference,
    executionPercent: row.executionPercent,
  }))

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Отчеты"
        title="Отчеты"
        description="Срез периода по деньгам, кошелькам и бюджету."
      />

      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-1">
              <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">Период анализа</div>
              <div className="text-sm leading-5 text-muted-foreground">
                Быстрый диапазон или свой период.
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant={selectedPreset === "week" ? "default" : "outline"} size="sm" onClick={() => setPresetRange("week")}>
                7 дней
              </Button>
              <Button variant={selectedPreset === "month" ? "default" : "outline"} size="sm" onClick={() => setPresetRange("month")}>
                Месяц
              </Button>
              <Button variant={selectedPreset === "quarter" ? "default" : "outline"} size="sm" onClick={() => setPresetRange("quarter")}>
                Квартал
              </Button>
              <Button variant={selectedPreset === "year" ? "default" : "outline"} size="sm" onClick={() => setPresetRange("year")}>
                Год
              </Button>
              <Button variant={selectedPreset === "ytd" ? "default" : "outline"} size="sm" onClick={() => setPresetRange("ytd")}>
                С начала года
              </Button>
            </div>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="space-y-2">
              <Label htmlFor="reports-date-from">Дата с</Label>
              <Input
                id="reports-date-from"
                type="date"
                value={dateFrom}
                onChange={(event) => {
                  setDateFrom(event.target.value)
                  setSelectedPreset(null)
                }}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="reports-date-to">Дата по</Label>
              <Input
                id="reports-date-to"
                type="date"
                value={dateTo}
                onChange={(event) => {
                  setDateTo(event.target.value)
                  setSelectedPreset(null)
                }}
              />
            </div>
          </div>

          <div className="rounded-[18px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
            Период: с {formatDate(dateFrom)} по {formatDate(dateTo)}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="grid gap-3 p-4 md:grid-cols-3">
          <div className="rounded-[18px] border border-border/60 bg-background/70 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Итог периода</div>
            <div className={`mt-2 text-xl font-semibold tracking-[-0.04em] ${netTotal >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
              {formatCurrency(netTotal)}
            </div>
            <p className="mt-2 text-sm leading-5 text-muted-foreground">
              {netTotal >= 0 ? "Период в плюсе." : "Расходы выше доходов."}
            </p>
          </div>
          <div className="rounded-[18px] border border-border/60 bg-background/70 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Главная статья</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em] text-foreground">
              {topExpenseCategory ? topExpenseCategory.name : "Нет данных"}
            </div>
            <p className="mt-2 text-sm leading-5 text-muted-foreground">
              {topExpenseCategory
                ? `${formatCurrency(topExpenseCategory.amount)} · ${topExpenseCategory.percentage.toFixed(1)}% от всех расходов`
                : "За выбранный период расходы по категориям не найдены."}
            </p>
          </div>
          <div className="rounded-[18px] border border-border/60 bg-background/70 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Крупнейший кошелек</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em] text-foreground">
              {dominantWallet ? dominantWallet.name : "Нет данных"}
            </div>
            <p className="mt-2 text-sm leading-5 text-muted-foreground">
              {dominantWallet
                ? `${formatCurrency(dominantWallet.balance)} · ${dominantWallet.share.toFixed(1)}% от видимого остатка`
                : "Нет кошельков с доступным балансом."}
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Доходы за период" value={formatCurrency(incomeTotal)} hint="Все зафиксированные поступления" icon={TrendingUp} tone="positive" />
        <StatCard label="Расходы за период" value={formatCurrency(expenseTotal)} hint="Все списания по выбранному периоду" icon={TrendingDown} tone="danger" />
        <StatCard label="Чистый поток" value={formatCurrency(netTotal)} hint="Доходы минус расходы" icon={BarChart3} tone={netTotal >= 0 ? "positive" : "danger"} />
        <StatCard label="Бюджетный факт" value={formatCurrency(includedExpenseTotal)} hint={`${plannedBudgetCount} строк отчета по расходному бюджету`} icon={Landmark} />
      </div>

      <Tabs defaultValue="cashflow" className="space-y-5">
        <TabsList className="grid h-auto grid-cols-2 gap-2 rounded-[18px] bg-muted/60 p-1.5 xl:grid-cols-4">
          <TabsTrigger value="cashflow" className="rounded-[14px] py-2.5">
            Поток денег
          </TabsTrigger>
          <TabsTrigger value="wallets" className="rounded-[14px] py-2.5">
            Кошельки
          </TabsTrigger>
          <TabsTrigger value="categories" className="rounded-[14px] py-2.5">
            Категории
          </TabsTrigger>
          <TabsTrigger value="budget" className="rounded-[14px] py-2.5">
            Исполнение бюджета
          </TabsTrigger>
        </TabsList>

        <TabsContent value="cashflow" className="space-y-6">
          <Card>
            <CardHeader className="gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-1">
                <CardTitle>Доходы, расходы и динамика чистого потока</CardTitle>
                <CardDescription>Главный ответ по периоду: когда деньги приходят, когда уходят и как меняется итог.</CardDescription>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex gap-2 rounded-[24px] border border-border/70 bg-background/70 p-2">
                  <Button variant={timelineMode === "daily" ? "default" : "outline"} size="sm" onClick={() => setTimelineMode("daily")}>
                    По дням
                  </Button>
                  <Button variant={timelineMode === "monthly" ? "default" : "outline"} size="sm" onClick={() => setTimelineMode("monthly")}>
                    По месяцам
                  </Button>
                </div>
                <ExportReportButtons
                  data={cashFlowExportRows}
                  columns={[
                    { key: "period", header: "Период" },
                    { key: "income", header: "Доходы", formatter: exportFormatters.currency },
                    { key: "expense", header: "Расходы", formatter: exportFormatters.currency },
                    { key: "net", header: "Чистый поток", formatter: exportFormatters.currency },
                  ]}
                  filename="cash-flow-report"
                  title="Отчет по движению денег"
                  chartRef={cashFlowChartRef}
                />
              </div>
            </CardHeader>
          </Card>

          {timelineRows.length === 0 ? (
            renderNoData("Нет данных по потоку денег", "За выбранный период не найдено ни приходов, ни расходов. Измени диапазон или проверь, есть ли операции в базе.")
          ) : (
            <div className="grid gap-6 xl:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>{timelineMode === "daily" ? "Доходы и расходы по дням" : "Доходы и расходы по месяцам"}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-[380px]" ref={cashFlowChartRef}>
                    <ResponsiveBar
                      data={timelineRows}
                      keys={["income", "expense"]}
                      indexBy="label"
                      margin={{ top: 20, right: 20, bottom: 80, left: 48 }}
                      padding={0.3}
                      groupMode="grouped"
                      axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -35 }}
                      axisLeft={{ tickSize: 0, tickPadding: 8 }}
                      tooltip={({ id, value, indexValue }) => (
                        <div className="rounded border bg-background px-2 py-1 text-xs">
                          {String(indexValue)} / {String(id)}: {formatCurrency(Number(value))}
                        </div>
                      )}
                      colors={["hsl(var(--primary))", "#ef4444"]}
                    />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Кумулятивный чистый поток</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-[380px]">
                    <ResponsiveLine
                      data={[
                        {
                          id: "Чистый поток",
                          data: cumulativeLineData,
                        },
                      ]}
                      margin={{ top: 20, right: 20, bottom: 80, left: 48 }}
                      xScale={{ type: "point" }}
                      yScale={{ type: "linear", stacked: false }}
                      axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -35 }}
                      axisLeft={{ tickSize: 0, tickPadding: 8 }}
                      curve="monotoneX"
                      pointSize={7}
                      colors={["hsl(var(--primary))"]}
                      useMesh
                      tooltip={({ point }) => (
                        <div className="rounded border bg-background px-2 py-1 text-xs">
                          {String(point.data.x)}: {formatCurrency(Number(point.data.y))}
                        </div>
                      )}
                    />
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="wallets" className="space-y-6">
          <Card>
            <CardHeader className="gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-1">
                <CardTitle>Структура капитала по кошелькам</CardTitle>
                <CardDescription>Показывает, где сейчас лежат деньги и насколько баланс распределён между кошельками.</CardDescription>
              </div>
              <ExportReportButtons
                data={walletExportRows}
                columns={[
                  { key: "name", header: "Кошелек" },
                  { key: "balance", header: "Баланс", formatter: exportFormatters.currency },
                  { key: "share", header: "Доля", formatter: exportFormatters.percent },
                ]}
                filename="wallet-structure-report"
                title="Структура балансов по кошелькам"
                chartRef={walletChartRef}
              />
            </CardHeader>
          </Card>

          <div className="grid gap-4 md:grid-cols-3">
            <StatCard label="Общий баланс" value={formatCurrency(totalWalletBalance)} hint="Сумма по всем видимым кошелькам" icon={Wallet2} tone={totalWalletBalance >= 0 ? "positive" : "danger"} />
            <StatCard label="Положительные балансы" value={formatCurrency(positiveWalletBalance)} hint="Кошельки с положительным остатком" icon={TrendingUp} tone="positive" />
            <StatCard label="Отрицательные балансы" value={formatCurrency(negativeWalletBalance)} hint="Кошельки в минусе или долге" icon={TrendingDown} tone="danger" />
          </div>

          {walletRows.length === 0 ? (
            renderNoData("Нет данных по кошелькам", "В системе пока нет кошельков с доступными балансами.")
          ) : (
            <div className="grid gap-6 xl:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Распределение положительных балансов</CardTitle>
                </CardHeader>
                <CardContent>
                  {positiveWalletRows.length === 0 ? (
                    <div className="py-20 text-center text-sm text-muted-foreground">Нет кошельков с положительным балансом для круговой диаграммы.</div>
                  ) : (
                    <div className="h-[380px]" ref={walletChartRef}>
                      <ResponsivePie
                        data={positiveWalletRows.map((wallet) => ({
                          id: wallet.name,
                          label: wallet.name,
                          value: wallet.balance,
                        }))}
                        margin={{ top: 20, right: 140, bottom: 20, left: 20 }}
                        innerRadius={0.58}
                        padAngle={1}
                        cornerRadius={4}
                        activeOuterRadiusOffset={8}
                        tooltip={({ datum }) => (
                          <div className="rounded border bg-background px-2 py-1 text-xs">
                            {String(datum.label)}: {formatCurrency(Number(datum.value))}
                          </div>
                        )}
                        legends={[
                          {
                            anchor: "right",
                            direction: "column",
                            translateX: 110,
                            itemWidth: 120,
                            itemHeight: 18,
                          },
                        ]}
                        colors={{ scheme: "category10" }}
                      />
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Детализация балансов</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b text-left text-sm text-muted-foreground">
                          <th className="pb-3">Кошелек</th>
                          <th className="pb-3 text-right">Баланс</th>
                          <th className="pb-3 text-right">Доля</th>
                        </tr>
                      </thead>
                      <tbody>
                        {walletRows.map((wallet) => (
                          <tr key={wallet.id} className="border-b border-border/60">
                            <td className="py-3">{wallet.name}</td>
                            <td className={`py-3 text-right font-medium ${wallet.balance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(wallet.balance)}
                            </td>
                            <td className="py-3 text-right text-muted-foreground">{wallet.share.toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        <TabsContent value="categories" className="space-y-6">
          <Card>
            <CardHeader className="gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-1">
                <CardTitle>Структура расходных категорий</CardTitle>
                <CardDescription>Показывает, какие статьи съедают основную часть расходов и куда смотреть в первую очередь.</CardDescription>
              </div>
              <ExportReportButtons
                data={categoriesExportRows}
                columns={[
                  { key: "name", header: "Категория" },
                  { key: "amount", header: "Сумма", formatter: exportFormatters.currency },
                  { key: "percentage", header: "Доля", formatter: exportFormatters.percent },
                ]}
                filename="expense-categories-report"
                title="Отчет по структуре расходных категорий"
                chartRef={categoryChartRef}
              />
            </CardHeader>
          </Card>

          {categoryRows.length === 0 ? (
            renderNoData("Нет расходов по категориям", "За выбранный период не найдено расходов. Измени диапазон или проверь, есть ли траты в системе.")
          ) : (
            <>
              <div className="grid gap-6 xl:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle>Распределение расходов</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-[420px]">
                      <ResponsivePie
                        data={categoryRows.slice(0, 10).map((category) => ({
                          id: category.name,
                          label: category.name,
                          value: category.amount,
                        }))}
                        margin={{ top: 20, right: 140, bottom: 20, left: 20 }}
                        innerRadius={0.58}
                        padAngle={1}
                        cornerRadius={4}
                        activeOuterRadiusOffset={8}
                        tooltip={({ datum }) => (
                          <div className="rounded border bg-background px-2 py-1 text-xs">
                            {String(datum.label)}: {formatCurrency(Number(datum.value))}
                          </div>
                        )}
                        legends={[
                          {
                            anchor: "right",
                            direction: "column",
                            translateX: 110,
                            itemWidth: 120,
                            itemHeight: 18,
                          },
                        ]}
                        colors={{ scheme: "category10" }}
                      />
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Топ категорий по сумме</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-[420px]" ref={categoryChartRef}>
                      <ResponsiveBar
                        data={topCategoryRows.map((category) => ({ name: category.name, amount: category.amount }))}
                        keys={["amount"]}
                        indexBy="name"
                        margin={{ top: 20, right: 20, bottom: 30, left: 130 }}
                        padding={0.3}
                        layout="horizontal"
                        axisBottom={{ tickSize: 0, tickPadding: 8 }}
                        axisLeft={{ tickSize: 0, tickPadding: 8 }}
                        tooltip={({ value, indexValue }) => (
                          <div className="rounded border bg-background px-2 py-1 text-xs">
                            {String(indexValue)}: {formatCurrency(Number(value))}
                          </div>
                        )}
                        colors={["#ef4444"]}
                      />
                    </div>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Детализация категорий расходов</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b text-left text-sm text-muted-foreground">
                          <th className="pb-3">Категория</th>
                          <th className="pb-3 text-right">Сумма</th>
                          <th className="pb-3 text-right">Доля</th>
                        </tr>
                      </thead>
                      <tbody>
                        {categoryRows.map((category) => (
                          <tr key={category.id} className="border-b border-border/60">
                            <td className="py-3">{category.name}</td>
                            <td className="py-3 text-right font-medium text-rose-600 dark:text-rose-300">{formatCurrency(category.amount)}</td>
                            <td className="py-3 text-right text-muted-foreground">{category.percentage.toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>

        <TabsContent value="budget" className="space-y-6">
          <Card>
            <CardHeader className="gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-1">
                <CardTitle>Исполнение бюджета</CardTitle>
                <CardDescription>План и факт рядом, чтобы сразу видеть отклонения по доходам и расходам.</CardDescription>
              </div>
              <ExportReportButtons
                data={budgetExportRows}
                columns={[
                  { key: "name", header: "Категория" },
                  { key: "type", header: "Тип" },
                  { key: "budgetAmount", header: "План", formatter: exportFormatters.currency },
                  { key: "actualAmount", header: "Факт", formatter: exportFormatters.currency },
                  { key: "difference", header: "Разница", formatter: exportFormatters.currency },
                  { key: "executionPercent", header: "Исполнение", formatter: exportFormatters.percent },
                ]}
                filename="budget-execution-report"
                title="Исполнение бюджета"
              />
            </CardHeader>
          </Card>

          <div className="grid gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Доходный бюджет</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <div className="text-muted-foreground">План</div>
                    <div className="mt-2 text-xl font-semibold">{formatCurrency(totalBudgetIncome)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Факт</div>
                    <div className="mt-2 text-xl font-semibold text-emerald-600 dark:text-emerald-300">{formatCurrency(totalActualIncome)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Исполнение</div>
                    <div className="mt-2 text-xl font-semibold">
                      {totalBudgetIncome > 0 ? `${Math.round((totalActualIncome / totalBudgetIncome) * 100)}%` : "—"}
                    </div>
                  </div>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full bg-emerald-500"
                    style={{
                      width: `${totalBudgetIncome > 0 ? Math.min(100, (totalActualIncome / totalBudgetIncome) * 100) : 0}%`,
                    }}
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Расходный бюджет</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <div className="text-muted-foreground">План</div>
                    <div className="mt-2 text-xl font-semibold">{formatCurrency(totalBudgetExpense)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Факт</div>
                    <div className="mt-2 text-xl font-semibold text-rose-600 dark:text-rose-300">{formatCurrency(totalActualExpense)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Исполнение</div>
                    <div className="mt-2 text-xl font-semibold">
                      {totalBudgetExpense > 0 ? `${Math.round((totalActualExpense / totalBudgetExpense) * 100)}%` : "—"}
                    </div>
                  </div>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className={`h-full ${totalActualExpense > totalBudgetExpense ? "bg-rose-500" : "bg-primary"}`}
                    style={{
                      width: `${totalBudgetExpense > 0 ? Math.min(100, (totalActualExpense / totalBudgetExpense) * 100) : 0}%`,
                    }}
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          {budgetExecutionRows.length === 0 ? (
            renderNoData("Нет данных по исполнению бюджета", "За выбранный период не найдено бюджетов и связанных с ними фактических операций.")
          ) : (
            <>
              <div className="grid gap-6 xl:grid-cols-2">
                <Card>
                  <CardHeader className="gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <CardTitle>Доходы: план vs факт</CardTitle>
                    </div>
                    <ExportReportButtons
                      data={incomeBudgetChartRows}
                      columns={[
                        { key: "name", header: "Категория" },
                        { key: "budget", header: "План", formatter: exportFormatters.currency },
                        { key: "actual", header: "Факт", formatter: exportFormatters.currency },
                      ]}
                      filename="budget-income-plan-fact"
                      title="Доходный бюджет: план vs факт"
                      chartRef={budgetIncomeChartRef}
                    />
                  </CardHeader>
                  <CardContent>
                    {incomeBudgetChartRows.length === 0 ? (
                      <div className="py-20 text-center text-sm text-muted-foreground">Доходных бюджетов в выбранном периоде нет.</div>
                    ) : (
                      <div className="h-[380px]" ref={budgetIncomeChartRef}>
                        <ResponsiveBar
                          data={incomeBudgetChartRows}
                          keys={["budget", "actual"]}
                          indexBy="name"
                          margin={{ top: 20, right: 20, bottom: 30, left: 130 }}
                          padding={0.3}
                          layout="horizontal"
                          groupMode="grouped"
                          axisBottom={{ tickSize: 0, tickPadding: 8 }}
                          axisLeft={{ tickSize: 0, tickPadding: 8 }}
                          tooltip={({ id, value, indexValue }) => (
                            <div className="rounded border bg-background px-2 py-1 text-xs">
                              {String(indexValue)} / {String(id)}: {formatCurrency(Number(value))}
                            </div>
                          )}
                          colors={["hsl(var(--primary))", "#10b981"]}
                        />
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <CardTitle>Расходы: план vs факт</CardTitle>
                    </div>
                    <ExportReportButtons
                      data={expenseBudgetChartRows}
                      columns={[
                        { key: "name", header: "Категория" },
                        { key: "budget", header: "План", formatter: exportFormatters.currency },
                        { key: "actual", header: "Факт", formatter: exportFormatters.currency },
                      ]}
                      filename="budget-expense-plan-fact"
                      title="Расходный бюджет: план vs факт"
                      chartRef={budgetExpenseChartRef}
                    />
                  </CardHeader>
                  <CardContent>
                    {expenseBudgetChartRows.length === 0 ? (
                      <div className="py-20 text-center text-sm text-muted-foreground">Расходных бюджетов в выбранном периоде нет.</div>
                    ) : (
                      <div className="h-[380px]" ref={budgetExpenseChartRef}>
                        <ResponsiveBar
                          data={expenseBudgetChartRows}
                          keys={["budget", "actual"]}
                          indexBy="name"
                          margin={{ top: 20, right: 20, bottom: 30, left: 130 }}
                          padding={0.3}
                          layout="horizontal"
                          groupMode="grouped"
                          axisBottom={{ tickSize: 0, tickPadding: 8 }}
                          axisLeft={{ tickSize: 0, tickPadding: 8 }}
                          tooltip={({ id, value, indexValue }) => (
                            <div className="rounded border bg-background px-2 py-1 text-xs">
                              {String(indexValue)} / {String(id)}: {formatCurrency(Number(value))}
                            </div>
                          )}
                          colors={["hsl(var(--primary))", "#ef4444"]}
                        />
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Детализация исполнения бюджета</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b text-left text-sm text-muted-foreground">
                          <th className="pb-3">Категория</th>
                          <th className="pb-3">Тип</th>
                          <th className="pb-3 text-right">План</th>
                          <th className="pb-3 text-right">Факт</th>
                          <th className="pb-3 text-right">Разница</th>
                          <th className="pb-3 text-right">Исполнение</th>
                        </tr>
                      </thead>
                      <tbody>
                        {budgetExecutionRows.map((row) => {
                          const isIncome = row.type === "income"
                          return (
                            <tr key={row.key} className="border-b border-border/60">
                              <td className="py-3">{row.name}</td>
                              <td className="py-3">
                                <Badge variant={isIncome ? "success" : "secondary"}>{isIncome ? "Доход" : "Расход"}</Badge>
                              </td>
                              <td className="py-3 text-right">{formatCurrency(row.budgetAmount)}</td>
                              <td className={`py-3 text-right font-medium ${isIncome ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                {formatCurrency(row.actualAmount)}
                              </td>
                              <td className={`py-3 text-right ${row.difference >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                {formatCurrency(row.difference)}
                              </td>
                              <td className="py-3 text-right">
                                {row.budgetAmount > 0 ? `${Math.round(row.executionPercent)}%` : "—"}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
