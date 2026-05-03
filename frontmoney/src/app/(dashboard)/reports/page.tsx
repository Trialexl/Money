"use client"

import Link from "next/link"
import { useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { ResponsiveBar } from "@nivo/bar"
import { ResponsiveLine } from "@nivo/line"
import { ResponsivePie } from "@nivo/pie"
import {
  BarChart3,
  ChevronDown,
  ChevronRight,
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { exportFormatters } from "@/lib/export-utils"
import { formatCurrency, formatDate, formatDateForInput } from "@/lib/formatters"
import { DashboardService, type DashboardWalletSummary } from "@/services/dashboard-service"
import { ProjectService } from "@/services/project-service"
import {
  ReportService,
  type BudgetReportDetail,
  type BudgetReportSummary,
  type CashFlowReportDetail,
  type CashFlowReportMonth,
} from "@/services/report-service"

type TimelineMode = "daily" | "monthly"
type RangePreset = "week" | "month" | "quarter" | "year" | "ytd" | null
type ReportTab = "cashflow" | "wallets" | "categories" | "budget"

type BudgetPlanningRow = {
  key: string
  monthKey: string
  monthLabel: string
  itemKey: string
  itemName: string
  plannedAmount: number
  actualAmount: number
  balance: number
  executionPercent: number
}

type BudgetPlanDetailRow = {
  key: string
  monthKey: string
  monthLabel: string
  itemKey: string
  itemName: string
  amount: number
  documentHref: string | null
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

type MonthlyCashFlowItemRow = {
  key: string
  monthKey: string
  monthLabel: string
  itemKey: string
  itemName: string
  income: number
  expense: number
  net: number
}

type MonthlyCashFlowGroup = {
  key: string
  label: string
  income: number
  expense: number
  net: number
  rows: MonthlyCashFlowItemRow[]
}

const REPORT_ITEM_COLORS = [
  "#2dd4bf",
  "#60a5fa",
  "#f97316",
  "#a78bfa",
  "#f43f5e",
  "#84cc16",
  "#facc15",
  "#38bdf8",
  "#fb7185",
  "#34d399",
  "#c084fc",
  "#fb923c",
]

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

function formatCompactCurrency(value: number) {
  const absoluteValue = Math.abs(value)

  if (absoluteValue >= 1_000_000) {
    return `${(value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`
  }

  if (absoluteValue >= 1_000) {
    return `${Math.round(value / 1_000).toLocaleString("ru-RU")} тыс`
  }

  return Math.round(value).toLocaleString("ru-RU")
}

function shiftDays(days: number) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date
}

function getMonthInputValue(value: string) {
  return getDateKey(value).slice(0, 7) || formatDateForInput().slice(0, 7)
}

function getMonthStartDate(monthValue: string) {
  return `${monthValue}-01`
}

function getMonthEndDate(monthValue: string) {
  const [year, month] = monthValue.split("-").map(Number)
  return formatDateForInput(new Date(year, month, 0))
}

function getBudgetDocumentHref(row: BudgetReportDetail) {
  if (!row.document_id || row.document_type !== "Budget") {
    return null
  }
  return `/budgets/${row.document_id}/edit`
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
  const router = useRouter()
  const searchParams = useSearchParams()
  const today = formatDateForInput()
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("daily")
  const [activeTab, setActiveTab] = useState<ReportTab>("cashflow")
  const [selectedPreset, setSelectedPreset] = useState<RangePreset>("month")
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") || formatDateForInput(shiftDays(-30)))
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") || today)
  const [budgetForecast, setBudgetForecast] = useState(searchParams.get("budget_forecast") !== "false")
  const [budgetProjectId, setBudgetProjectId] = useState(searchParams.get("budget_project") || "")
  const [collapsedMonthlyGroups, setCollapsedMonthlyGroups] = useState<Record<string, boolean>>({})
  const [selectedMonthlyExpenseItemKey, setSelectedMonthlyExpenseItemKey] = useState<string | null>(null)
  const [selectedBudgetPlanItemKey, setSelectedBudgetPlanItemKey] = useState<string | null>(null)
  const budgetFromMonth = getMonthInputValue(dateFrom)
  const budgetToMonth = getMonthInputValue(dateTo)
  const budgetDateFrom = getMonthStartDate(budgetFromMonth)
  const budgetDateTo = getMonthEndDate(budgetToMonth)
  const budgetYear = Number(budgetFromMonth.slice(0, 4)) || new Date().getFullYear()
  const cashFlowChartRef = useRef<HTMLDivElement>(null)
  const walletChartRef = useRef<HTMLDivElement>(null)
  const categoryChartRef = useRef<HTMLDivElement>(null)
  const budgetExpenseChartRef = useRef<HTMLDivElement>(null)

  const projectsQuery = useQuery({
    queryKey: ["projects", "reports-budget"],
    staleTime: 300_000,
    queryFn: () => ProjectService.getProjects(),
  })

  const reportsQuery = useQuery({
    queryKey: [
      "reports-analytics",
      { dateFrom, dateTo, budgetDateFrom, budgetDateTo, budgetForecast, budgetProjectId },
    ],
    staleTime: 60_000,
    queryFn: async () => {
      const [cashFlow, budgetExpense, overview] = await Promise.all([
        ReportService.getCashFlowReport({ dateFrom, dateTo }),
        ReportService.getBudgetExpenseReport({
          dateFrom: budgetDateFrom,
          dateTo: budgetDateTo,
          limitByToday: budgetForecast,
          project: budgetProjectId || undefined,
        }),
        DashboardService.getOverview({ date: dateTo, hideHiddenWallets: true }),
      ])

      return {
        cashFlow,
        budgetExpense,
        overview,
      }
    },
  })

  const updateReportUrl = (
    nextDateFrom: string,
    nextDateTo: string,
    nextBudgetForecast: boolean,
    nextBudgetProjectId = budgetProjectId
  ) => {
    const params = new URLSearchParams(searchParams.toString())
    params.set("date_from", nextDateFrom)
    params.set("date_to", nextDateTo)
    params.set("budget_forecast", nextBudgetForecast ? "true" : "false")
    if (nextBudgetProjectId) {
      params.set("budget_project", nextBudgetProjectId)
    } else {
      params.delete("budget_project")
    }
    router.replace(`/reports?${params.toString()}`, { scroll: false })
  }

  const setBudgetMonthRange = (nextDateFromMonth: string, nextDateToMonth: string) => {
    if (!nextDateFromMonth || !nextDateToMonth) {
      return
    }
    const normalizedDateToMonth =
      nextDateToMonth < nextDateFromMonth ? nextDateFromMonth : nextDateToMonth
    const nextDateFrom = getMonthStartDate(nextDateFromMonth)
    const nextDateTo = getMonthEndDate(normalizedDateToMonth)
    setDateFrom(nextDateFrom)
    setDateTo(nextDateTo)
    setSelectedPreset(null)
    setSelectedBudgetPlanItemKey(null)
    updateReportUrl(nextDateFrom, nextDateTo, budgetForecast)
  }

  const setBudgetYearRange = (year: number) => {
    const nextDateFrom = `${year}-01-01`
    const nextDateTo = `${year}-12-31`
    setDateFrom(nextDateFrom)
    setDateTo(nextDateTo)
    setSelectedPreset(null)
    setSelectedBudgetPlanItemKey(null)
    updateReportUrl(nextDateFrom, nextDateTo, budgetForecast)
  }

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

    const nextDateFrom = formatDateForInput(from)
    const nextDateTo = formatDateForInput(today)
    setDateFrom(nextDateFrom)
    setDateTo(nextDateTo)
    setSelectedPreset(preset)
    updateReportUrl(nextDateFrom, nextDateTo, budgetForecast)
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

  const { cashFlow, budgetExpense, overview } = reportsQuery.data
  const budgetProjectOptions = (projectsQuery.data ?? [])
    .filter((project) => !project.deleted)
    .sort((left, right) => left.name.localeCompare(right.name, "ru"))
  const selectedBudgetProjectName =
    budgetProjectId
      ? budgetProjectOptions.find((project) => project.id === budgetProjectId)?.name ?? "Выбранный проект"
      : "Без проекта"
  const incomeTotal = cashFlow.totals.income
  const expenseTotal = cashFlow.totals.expense
  const netTotal = incomeTotal - expenseTotal
  const plannedBudgetCount = budgetExpense.summary.length
  const includedExpenseTotal = budgetExpense.totals.actual
  const isFutureReportDate = dateTo > today
  const isBudgetTab = activeTab === "budget"

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
  const topExpenseCategory = categoryRows[0] || null

  const monthlyCashFlowItemMap = new Map<string, MonthlyCashFlowItemRow>()
  cashFlow.details.forEach((detail: CashFlowReportDetail) => {
    const monthKey = getMonthKey(detail.period)
    const itemKey = detail.cash_flow_item_id || detail.cash_flow_item_name || "unknown"
    const key = `${monthKey}:${itemKey}`
    const row = monthlyCashFlowItemMap.get(key) || {
      key,
      monthKey,
      monthLabel: formatMonthLabel(monthKey),
      itemKey,
      itemName: detail.cash_flow_item_name || "Неизвестная статья",
      income: 0,
      expense: 0,
      net: 0,
    }
    row.income += detail.income
    row.expense += detail.expense
    row.net = row.income - row.expense
    monthlyCashFlowItemMap.set(key, row)
  })

  const monthlyCashFlowItemRows = Array.from(monthlyCashFlowItemMap.values()).sort((left, right) => {
    const monthCompare = left.monthKey.localeCompare(right.monthKey)
    if (monthCompare !== 0) {
      return monthCompare
    }
    const turnoverCompare = right.income + right.expense - (left.income + left.expense)
    if (turnoverCompare !== 0) {
      return turnoverCompare
    }
    return left.itemName.localeCompare(right.itemName, "ru")
  })
  const monthlyCashFlowGroupMap = new Map<string, MonthlyCashFlowGroup>()
  monthlyCashFlowItemRows.forEach((row) => {
    const group = monthlyCashFlowGroupMap.get(row.monthKey) || {
      key: row.monthKey,
      label: row.monthLabel,
      income: 0,
      expense: 0,
      net: 0,
      rows: [],
    }
    group.income += row.income
    group.expense += row.expense
    group.net = group.income - group.expense
    group.rows.push(row)
    monthlyCashFlowGroupMap.set(row.monthKey, group)
  })
  const monthlyCashFlowGroups = Array.from(monthlyCashFlowGroupMap.values()).sort((left, right) =>
    left.key.localeCompare(right.key)
  )
  const monthlyExpenseItemTotals = new Map<string, { key: string; name: string; expense: number }>()
  monthlyCashFlowItemRows.forEach((row) => {
    if (row.expense <= 0) {
      return
    }
    const item = monthlyExpenseItemTotals.get(row.itemKey) || {
      key: row.itemKey,
      name: row.itemName,
      expense: 0,
    }
    item.expense += row.expense
    monthlyExpenseItemTotals.set(row.itemKey, item)
  })
  const monthlyExpenseItems = Array.from(monthlyExpenseItemTotals.values()).sort(
    (left, right) => right.expense - left.expense
  )
  const monthlyExpenseLegendItems = monthlyExpenseItems.map((item, index) => ({
    ...item,
    color: REPORT_ITEM_COLORS[index % REPORT_ITEM_COLORS.length],
    share: expenseTotal > 0 ? (item.expense / expenseTotal) * 100 : 0,
  }))
  const monthlyExpenseItemByKey = new Map(monthlyExpenseLegendItems.map((item) => [item.key, item]))
  const monthlyExpenseColorByKey = new Map(monthlyExpenseLegendItems.map((item) => [item.key, item.color]))
  const activeSelectedMonthlyExpenseItemKey =
    selectedMonthlyExpenseItemKey && monthlyExpenseItemTotals.has(selectedMonthlyExpenseItemKey)
      ? selectedMonthlyExpenseItemKey
      : null
  const selectedMonthlyExpenseItemName =
    activeSelectedMonthlyExpenseItemKey
      ? monthlyExpenseItems.find((item) => item.key === activeSelectedMonthlyExpenseItemKey)?.name ?? null
      : null
  const visibleMonthlyCashFlowGroups = activeSelectedMonthlyExpenseItemKey
    ? monthlyCashFlowGroups
        .map((group) => ({
          ...group,
          income: group.rows
            .filter((row) => row.itemKey === activeSelectedMonthlyExpenseItemKey)
            .reduce((sum, row) => sum + row.income, 0),
          expense: group.rows
            .filter((row) => row.itemKey === activeSelectedMonthlyExpenseItemKey)
            .reduce((sum, row) => sum + row.expense, 0),
          rows: group.rows.filter((row) => row.itemKey === activeSelectedMonthlyExpenseItemKey),
        }))
        .map((group) => ({
          ...group,
          net: group.income - group.expense,
        }))
        .filter((group) => group.rows.length > 0)
    : monthlyCashFlowGroups
  const monthlyExpenseChartKeys = activeSelectedMonthlyExpenseItemKey
    ? [activeSelectedMonthlyExpenseItemKey]
    : monthlyExpenseLegendItems.map((item) => item.key)
  const monthlyExpenseChartRows = visibleMonthlyCashFlowGroups.map((group) => {
    const chartRow: Record<string, string | number> = {
      month: group.label,
    }
    group.rows
      .filter((row) => row.expense > 0)
      .forEach((row) => {
        chartRow[row.itemKey] = (Number(chartRow[row.itemKey]) || 0) + row.expense
      })
    return chartRow
  })
  const monthlyCashFlowExportRows = monthlyCashFlowItemRows.map((row) => ({
    month: row.monthLabel,
    cashFlowItem: row.itemName,
    income: row.income,
    expense: row.expense,
    net: row.net,
  }))

  const budgetPlanningMap = new Map<string, BudgetPlanningRow>()

  budgetExpense.summary.forEach((row: BudgetReportSummary) => {
    if (row.budget <= 0) {
      return
    }

    const monthKey = getMonthKey(row.period)
    const itemKey = row.cash_flow_item_id || row.cash_flow_item_name || "unknown"
    const key = `${monthKey}:${itemKey}`
    const planRow = budgetPlanningMap.get(key) || {
      key,
      monthKey,
      monthLabel: formatMonthLabel(monthKey),
      itemKey,
      itemName: row.cash_flow_item_name || "Неизвестная статья",
      plannedAmount: 0,
      actualAmount: 0,
      balance: 0,
      executionPercent: 0,
    }
    planRow.plannedAmount += row.budget
    planRow.actualAmount += row.actual
    planRow.balance += row.balance
    planRow.executionPercent =
      planRow.plannedAmount > 0 ? (planRow.actualAmount / planRow.plannedAmount) * 100 : 0
    budgetPlanningMap.set(key, planRow)
  })

  const budgetPlanningRows = Array.from(budgetPlanningMap.values()).sort((left, right) => {
    const monthCompare = left.monthKey.localeCompare(right.monthKey)
    if (monthCompare !== 0) {
      return monthCompare
    }
    return right.plannedAmount - left.plannedAmount
  })
  const budgetPlanItemTotals = new Map<string, { key: string; name: string; plannedAmount: number }>()
  budgetPlanningRows.forEach((row) => {
    const item = budgetPlanItemTotals.get(row.itemKey) || {
      key: row.itemKey,
      name: row.itemName,
      plannedAmount: 0,
    }
    item.plannedAmount += row.plannedAmount
    budgetPlanItemTotals.set(row.itemKey, item)
  })
  const budgetPlanItems = Array.from(budgetPlanItemTotals.values()).sort(
    (left, right) => right.plannedAmount - left.plannedAmount
  )
  const plannedExpenseTotal = budgetPlanningRows.reduce((sum, row) => sum + row.plannedAmount, 0)
  const plannedExpenseActual = budgetPlanningRows.reduce((sum, row) => sum + row.actualAmount, 0)
  const plannedExpenseBalance = plannedExpenseTotal - plannedExpenseActual
  const budgetPlanLegendItems = budgetPlanItems.map((item, index) => ({
    ...item,
    color: REPORT_ITEM_COLORS[index % REPORT_ITEM_COLORS.length],
    share: plannedExpenseTotal > 0 ? (item.plannedAmount / plannedExpenseTotal) * 100 : 0,
  }))
  const budgetPlanItemByKey = new Map(budgetPlanLegendItems.map((item) => [item.key, item]))
  const budgetPlanColorByKey = new Map(budgetPlanLegendItems.map((item) => [item.key, item.color]))
  const budgetPlanMonthKeys = Array.from(new Set(budgetPlanningRows.map((row) => row.monthKey))).sort()
  const activeSelectedBudgetPlanItemKey =
    selectedBudgetPlanItemKey && budgetPlanItemTotals.has(selectedBudgetPlanItemKey)
      ? selectedBudgetPlanItemKey
      : null
  const selectedBudgetPlanItemName =
    activeSelectedBudgetPlanItemKey
      ? budgetPlanItems.find((item) => item.key === activeSelectedBudgetPlanItemKey)?.name ?? null
      : null
  const visibleBudgetPlanningRows = activeSelectedBudgetPlanItemKey
    ? budgetPlanningRows.filter((row) => row.itemKey === activeSelectedBudgetPlanItemKey)
    : budgetPlanningRows
  const budgetPlanChartKeys = activeSelectedBudgetPlanItemKey
    ? [activeSelectedBudgetPlanItemKey]
    : budgetPlanLegendItems.map((item) => item.key)
  const budgetPlanChartRows = budgetPlanMonthKeys.map((monthKey) => {
    const chartRow: Record<string, string | number> = {
      month: formatMonthLabel(monthKey),
    }
    visibleBudgetPlanningRows
      .filter((row) => row.monthKey === monthKey)
      .forEach((row) => {
        chartRow[row.itemKey] = (Number(chartRow[row.itemKey]) || 0) + row.plannedAmount
      })
    return chartRow
  })
  const budgetPlanDetailRows: BudgetPlanDetailRow[] = budgetExpense.details
    .filter((row) => row.entry_type === "budget" && row.amount > 0)
    .map((row) => {
      const monthKey = getMonthKey(row.period)
      const itemKey = row.cash_flow_item_id || row.cash_flow_item_name || "unknown"
      return {
        key: `${row.document_id || "unknown"}:${row.period}:${itemKey}:${row.amount}`,
        monthKey,
        monthLabel: formatMonthLabel(monthKey),
        itemKey,
        itemName: row.cash_flow_item_name || "Неизвестная статья",
        amount: row.amount,
        documentHref: getBudgetDocumentHref(row),
      }
    })
    .sort((left, right) => {
      const monthCompare = left.monthKey.localeCompare(right.monthKey)
      if (monthCompare !== 0) {
        return monthCompare
      }
      return left.itemName.localeCompare(right.itemName, "ru")
    })
  const visibleBudgetPlanDetailRows = activeSelectedBudgetPlanItemKey
    ? budgetPlanDetailRows.filter((row) => row.itemKey === activeSelectedBudgetPlanItemKey)
    : budgetPlanDetailRows
  const budgetPlanExportRows = budgetPlanningRows.map((row) => ({
    month: row.monthLabel,
    cashFlowItem: row.itemName,
    plannedAmount: row.plannedAmount,
    actualAmount: row.actualAmount,
    balance: row.balance,
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
              <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                {isBudgetTab ? "Период бюджета" : "Период анализа"}
              </div>
              <div className="text-sm leading-5 text-muted-foreground">
                {isBudgetTab
                  ? "Выбор только по месяцам: бюджет считается от начала до конца месяца."
                  : "Быстрый диапазон или свой период."}
              </div>
            </div>
            {isBudgetTab ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => setBudgetYearRange(budgetYear - 1)}>
                  {budgetYear - 1}
                </Button>
                <Button variant="default" size="sm" onClick={() => setBudgetYearRange(new Date().getFullYear())}>
                  Текущий год
                </Button>
                <Button variant="outline" size="sm" onClick={() => setBudgetYearRange(budgetYear + 1)}>
                  {budgetYear + 1}
                </Button>
              </div>
            ) : (
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
            )}
          </div>

          {isBudgetTab ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(260px,0.8fr)]">
              <div className="space-y-2">
                <Label htmlFor="budget-period-month-from">Месяц с</Label>
                <Input
                  id="budget-period-month-from"
                  type="month"
                  value={budgetFromMonth}
                  onChange={(event) => setBudgetMonthRange(event.target.value, budgetToMonth)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-period-month-to">Месяц по</Label>
                <Input
                  id="budget-period-month-to"
                  type="month"
                  value={budgetToMonth}
                  onChange={(event) => setBudgetMonthRange(budgetFromMonth, event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-project">Проект</Label>
                <Select
                  value={budgetProjectId || "none"}
                  onValueChange={(value) => {
                    const nextBudgetProjectId = value === "none" ? "" : value
                    setBudgetProjectId(nextBudgetProjectId)
                    setSelectedBudgetPlanItemKey(null)
                    updateReportUrl(dateFrom, dateTo, budgetForecast, nextBudgetProjectId)
                  }}
                  disabled={projectsQuery.isLoading}
                >
                  <SelectTrigger id="budget-project">
                    <SelectValue placeholder="Без проекта" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">Без проекта</SelectItem>
                    {budgetProjectOptions.map((project) => (
                      <SelectItem key={project.id} value={project.id}>
                        {project.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <div className="space-y-2">
                <Label htmlFor="reports-date-from">Дата с</Label>
                <Input
                  id="reports-date-from"
                  type="date"
                  value={dateFrom}
                  onChange={(event) => {
                    const nextDateFrom = event.target.value
                    setDateFrom(nextDateFrom)
                    setSelectedPreset(null)
                    setSelectedBudgetPlanItemKey(null)
                    updateReportUrl(nextDateFrom, dateTo, budgetForecast)
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
                    const nextDateTo = event.target.value
                    setDateTo(nextDateTo)
                    setSelectedPreset(null)
                    setSelectedBudgetPlanItemKey(null)
                    updateReportUrl(dateFrom, nextDateTo, budgetForecast)
                  }}
                />
              </div>
            </div>
          )}

          {isBudgetTab ? (
            <div className="flex flex-col gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1">
                <Label htmlFor="budget-forecast-mode" className="cursor-pointer">
                  Прогноз бюджета
                </Label>
                <div className="text-sm leading-5 text-muted-foreground">
                  План считается до конца выбранного месяца, факт ограничивается сегодняшним днем.
                </div>
              </div>
              <Switch
                id="budget-forecast-mode"
                checked={budgetForecast}
                onCheckedChange={(checked) => {
                  const nextBudgetForecast = Boolean(checked)
                  setBudgetForecast(nextBudgetForecast)
                  updateReportUrl(dateFrom, dateTo, nextBudgetForecast)
                }}
              />
            </div>
          ) : null}

          <div className="rounded-[18px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
            {isBudgetTab ? (
              <>
                Период бюджета: с {formatDate(budgetDateFrom)} по {formatDate(budgetDateTo)} · проект:{" "}
                {selectedBudgetProjectName}
              </>
            ) : (
              <>
                Период: с {formatDate(dateFrom)} по {formatDate(dateTo)}
                {isFutureReportDate && budgetForecast ? " · прогноз по бюджету включен" : ""}
              </>
            )}
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

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as ReportTab)}
        className="space-y-5"
      >
        <TabsList className="grid h-auto grid-cols-2 gap-2 rounded-[18px] bg-muted/60 p-1.5 xl:grid-cols-4">
          <TabsTrigger value="cashflow" className="rounded-[14px] py-2.5">
            Поток денег
          </TabsTrigger>
          <TabsTrigger value="wallets" className="rounded-[14px] py-2.5">
            Кошельки
          </TabsTrigger>
          <TabsTrigger value="categories" className="rounded-[14px] py-2.5">
            Статьи по месяцам
          </TabsTrigger>
          <TabsTrigger value="budget" className="rounded-[14px] py-2.5">
            План бюджета
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
                <CardTitle>Помесячный отчет по статьям</CardTitle>
                <CardDescription>
                  Расходы на графике собраны по месяцам и статьям. Ниже таблица в стиле 1С: месяц, итог прихода,
                  итог расхода и статьи внутри группы.
                </CardDescription>
              </div>
              <ExportReportButtons
                data={monthlyCashFlowExportRows}
                columns={[
                  { key: "month", header: "Месяц" },
                  { key: "cashFlowItem", header: "Статья" },
                  { key: "income", header: "Приход", formatter: exportFormatters.currency },
                  { key: "expense", header: "Расход", formatter: exportFormatters.currency },
                  { key: "net", header: "Итог", formatter: exportFormatters.currency },
                ]}
                filename="monthly-cash-flow-by-items"
                title="Помесячный отчет по статьям"
                chartRef={categoryChartRef}
              />
            </CardHeader>
          </Card>

          {monthlyCashFlowGroups.length === 0 ? (
            renderNoData("Нет данных по статьям", "За выбранный период не найдено приходов или расходов по статьям.")
          ) : (
            <>
              <Card>
                <CardHeader className="gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-1">
                    <CardTitle>Расходы по месяцам и статьям</CardTitle>
                    <CardDescription>
                      Цвета соответствуют легенде справа. Клик по статье фильтрует график и таблицу.
                    </CardDescription>
                  </div>
                  {selectedMonthlyExpenseItemName ? (
                    <Button variant="outline" size="sm" onClick={() => setSelectedMonthlyExpenseItemKey(null)}>
                      Все статьи
                    </Button>
                  ) : null}
                </CardHeader>
                <CardContent>
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="h-[420px] min-w-0" ref={categoryChartRef}>
                      {monthlyExpenseChartKeys.length === 0 ? (
                        <div className="flex h-full items-center justify-center rounded-[22px] border border-dashed border-border/70 text-sm text-muted-foreground">
                          За выбранный период нет расходов по статьям.
                        </div>
                      ) : (
                        <ResponsiveBar
                          data={monthlyExpenseChartRows}
                          keys={monthlyExpenseChartKeys}
                          indexBy="month"
                          margin={{ top: 12, right: 12, bottom: 44, left: 68 }}
                          padding={0.34}
                          axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: 0 }}
                          axisLeft={{
                            tickSize: 0,
                            tickPadding: 8,
                            format: (value) => formatCompactCurrency(Number(value)),
                          }}
                          enableLabel={false}
                          colors={({ id }) => monthlyExpenseColorByKey.get(String(id)) || "#94a3b8"}
                          colorBy="id"
                          theme={{
                            axis: {
                              ticks: {
                                text: {
                                  fill: "hsl(var(--muted-foreground))",
                                  fontSize: 11,
                                },
                              },
                            },
                            grid: {
                              line: {
                                stroke: "hsl(var(--border))",
                                strokeOpacity: 0.45,
                              },
                            },
                            tooltip: {
                              container: {
                                background: "hsl(var(--background))",
                                color: "hsl(var(--foreground))",
                                border: "1px solid hsl(var(--border))",
                                borderRadius: 12,
                                boxShadow: "0 12px 32px rgb(0 0 0 / 0.22)",
                              },
                            },
                          }}
                          tooltip={({ id, value, indexValue }) => {
                            const item = monthlyExpenseItemByKey.get(String(id))
                            return (
                              <div className="px-2 py-1 text-xs">
                                {String(indexValue)} / {item?.name || String(id)}: {formatCurrency(Number(value))}
                              </div>
                            )
                          }}
                        />
                      )}
                    </div>
                    <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold tracking-[-0.02em]">Легенда расходных статей</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Клик по статье фильтрует график и таблицу.
                          </div>
                        </div>
                        {selectedMonthlyExpenseItemName ? (
                          <Button variant="ghost" size="sm" onClick={() => setSelectedMonthlyExpenseItemKey(null)}>
                            Сброс
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-4 max-h-[340px] space-y-2 overflow-y-auto pr-1">
                        {monthlyExpenseLegendItems.length === 0 ? (
                          <div className="rounded-2xl border border-border/60 bg-card/50 px-3 py-3 text-sm text-muted-foreground">
                            Расходных статей нет.
                          </div>
                        ) : (
                          monthlyExpenseLegendItems.map((item) => {
                            const isSelected = activeSelectedMonthlyExpenseItemKey === item.key
                            return (
                            <button
                              key={item.key}
                              type="button"
                              className={`w-full rounded-2xl border px-3 py-2 text-left transition ${
                                isSelected
                                  ? "border-primary bg-primary/10"
                                  : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                              }`}
                              onClick={() =>
                                setSelectedMonthlyExpenseItemKey((current) =>
                                  current === item.key ? null : item.key
                                )
                              }
                            >
                              <div className="flex items-center gap-2">
                                <span
                                  className="h-3 w-3 shrink-0 rounded-full"
                                  style={{ backgroundColor: item.color }}
                                />
                                <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.name}</span>
                                <span className="text-sm font-semibold text-rose-600 dark:text-rose-300">
                                  {formatCurrency(item.expense)}
                                </span>
                              </div>
                              <div className="mt-1 text-xs text-muted-foreground">
                                {item.share.toFixed(1)}% от расходов
                              </div>
                            </button>
                          )})
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>
                    {selectedMonthlyExpenseItemName
                      ? `Таблица: ${selectedMonthlyExpenseItemName}`
                      : "Таблица по месяцам и статьям"}
                  </CardTitle>
                  <CardDescription>
                    В каждой группе сначала итог месяца, затем строки статей с приходом, расходом и результатом.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b text-left text-sm text-muted-foreground">
                          <th className="pb-3">Месяц / статья</th>
                          <th className="pb-3 text-right">Приход</th>
                          <th className="pb-3 text-right">Расход</th>
                          <th className="pb-3 text-right">Итог</th>
                        </tr>
                      </thead>
                      {visibleMonthlyCashFlowGroups.map((group) => {
                        const isCollapsed = collapsedMonthlyGroups[group.key] ?? false

                        return (
                        <tbody key={group.key}>
                          <tr
                            className="cursor-pointer border-b border-border bg-muted/40 text-sm font-semibold transition-colors hover:bg-muted/60"
                            onClick={() =>
                              setCollapsedMonthlyGroups((current) => ({
                                ...current,
                                [group.key]: !(current[group.key] ?? false),
                              }))
                            }
                          >
                            <td className="py-3">
                              <span className="flex items-center gap-2">
                                {isCollapsed ? (
                                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                ) : (
                                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                                )}
                                <span>{group.label}</span>
                                <span className="text-xs font-medium text-muted-foreground">
                                  {group.rows.length} стат.
                                </span>
                              </span>
                            </td>
                            <td className="py-3 text-right text-emerald-600 dark:text-emerald-300">
                              {formatCurrency(group.income)}
                            </td>
                            <td className="py-3 text-right text-rose-600 dark:text-rose-300">
                              {formatCurrency(group.expense)}
                            </td>
                            <td className={`py-3 text-right ${group.net >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(group.net)}
                            </td>
                          </tr>
                          {isCollapsed ? null : group.rows.map((row) => (
                            <tr key={row.key} className="border-b border-border/60">
                              <td className="py-3 pl-5 font-medium">{row.itemName}</td>
                              <td className="py-3 text-right text-emerald-600 dark:text-emerald-300">
                                {row.income > 0 ? formatCurrency(row.income) : "—"}
                              </td>
                              <td className="py-3 text-right text-rose-600 dark:text-rose-300">
                                {row.expense > 0 ? formatCurrency(row.expense) : "—"}
                              </td>
                              <td className={`py-3 text-right ${row.net >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                {formatCurrency(row.net)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      )})}
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
                <CardTitle>План расходов по месяцам</CardTitle>
                <CardDescription>
                  Бюджетный отчет работает месячными периодами: от первого дня месяца до последнего.
                </CardDescription>
              </div>
              <ExportReportButtons
                data={budgetPlanExportRows}
                columns={[
                  { key: "month", header: "Месяц" },
                  { key: "cashFlowItem", header: "Статья" },
                  { key: "plannedAmount", header: "План", formatter: exportFormatters.currency },
                  { key: "actualAmount", header: "Факт", formatter: exportFormatters.currency },
                  { key: "balance", header: "Остаток", formatter: exportFormatters.currency },
                  { key: "executionPercent", header: "Исполнение", formatter: exportFormatters.percent },
                ]}
                filename="budget-expense-plan-by-month"
                title="План расходного бюджета по месяцам"
                chartRef={budgetExpenseChartRef}
              />
            </CardHeader>
          </Card>

          <div className="grid gap-4 md:grid-cols-3">
            <StatCard
              label="План расходов"
              value={formatCurrency(plannedExpenseTotal)}
              hint={`${budgetPlanMonthKeys.length} мес. · ${budgetPlanItems.length} стат.`}
              icon={Landmark}
            />
            <StatCard
              label="Факт по плановым статьям"
              value={formatCurrency(plannedExpenseActual)}
              hint={budgetForecast ? "Факт ограничен сегодняшним днем" : "Факт за выбранный период"}
              icon={TrendingDown}
              tone="danger"
            />
            <StatCard
              label="Остаток по плану"
              value={formatCurrency(plannedExpenseBalance)}
              hint="План минус факт по запланированным статьям"
              icon={BarChart3}
              tone={plannedExpenseBalance >= 0 ? "positive" : "danger"}
            />
          </div>

          {budgetPlanningRows.length === 0 ? (
            renderNoData(
              "Нет плана расходного бюджета",
              `За выбранные месяцы не найдено запланированных расходных статей: ${selectedBudgetProjectName}.`
            )
          ) : (
            <>
              <Card>
                <CardHeader className="gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-1">
                    <CardTitle>График планируемых расходов: {selectedBudgetProjectName}</CardTitle>
                    <CardDescription>
                      Месяцы собраны из статей расхода. Легенда справа фильтрует график и таблицы ниже.
                    </CardDescription>
                  </div>
                  {selectedBudgetPlanItemName ? (
                    <Button variant="outline" size="sm" onClick={() => setSelectedBudgetPlanItemKey(null)}>
                      Все статьи
                    </Button>
                  ) : null}
                </CardHeader>
                <CardContent>
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="h-[380px] min-w-0" ref={budgetExpenseChartRef}>
                      <ResponsiveBar
                        data={budgetPlanChartRows}
                        keys={budgetPlanChartKeys}
                        indexBy="month"
                        margin={{ top: 12, right: 12, bottom: 44, left: 68 }}
                        padding={0.34}
                        axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: 0 }}
                        axisLeft={{
                          tickSize: 0,
                          tickPadding: 8,
                          format: (value) => formatCompactCurrency(Number(value)),
                        }}
                        enableLabel={false}
                        colors={({ id }) => budgetPlanColorByKey.get(String(id)) || "#94a3b8"}
                        colorBy="id"
                        theme={{
                          axis: {
                            ticks: {
                              text: {
                                fill: "hsl(var(--muted-foreground))",
                                fontSize: 11,
                              },
                            },
                          },
                          grid: {
                            line: {
                              stroke: "hsl(var(--border))",
                              strokeOpacity: 0.45,
                            },
                          },
                          tooltip: {
                            container: {
                              background: "hsl(var(--background))",
                              color: "hsl(var(--foreground))",
                              border: "1px solid hsl(var(--border))",
                              borderRadius: 12,
                              boxShadow: "0 12px 32px rgb(0 0 0 / 0.22)",
                            },
                          },
                        }}
                        tooltip={({ id, value, indexValue }) => {
                          const item = budgetPlanItemByKey.get(String(id))
                          return (
                            <div className="px-2 py-1 text-xs">
                              {String(indexValue)} / {item?.name || String(id)}: {formatCurrency(Number(value))}
                            </div>
                          )
                        }}
                        onClick={(bar) => {
                          const itemKey = String(bar.id)
                          if (budgetPlanItemTotals.has(itemKey)) {
                            setSelectedBudgetPlanItemKey((current) => (current === itemKey ? null : itemKey))
                          }
                        }}
                      />
                    </div>
                    <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold tracking-[-0.02em]">Легенда статей</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Клик по статье фильтрует таблицы.
                          </div>
                        </div>
                        {selectedBudgetPlanItemName ? (
                          <Button variant="ghost" size="sm" onClick={() => setSelectedBudgetPlanItemKey(null)}>
                            Сброс
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-4 max-h-[300px] space-y-2 overflow-y-auto pr-1">
                        {budgetPlanLegendItems.map((item) => {
                          const isSelected = activeSelectedBudgetPlanItemKey === item.key
                          return (
                            <button
                              key={item.key}
                              type="button"
                              className={`w-full rounded-2xl border px-3 py-2 text-left transition ${
                                isSelected
                                  ? "border-primary bg-primary/10"
                                  : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                              }`}
                              onClick={() =>
                                setSelectedBudgetPlanItemKey((current) =>
                                  current === item.key ? null : item.key
                                )
                              }
                            >
                              <span className="flex items-center gap-2">
                                <span
                                  className="h-3 w-3 shrink-0 rounded-full"
                                  style={{ backgroundColor: item.color }}
                                />
                                <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.name}</span>
                                <span className="text-sm font-semibold">{formatCurrency(item.plannedAmount)}</span>
                              </span>
                              <span className="mt-1 block text-xs text-muted-foreground">
                                {item.share.toFixed(1)}% от плана
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="space-y-1">
                    <CardTitle>
                      {selectedBudgetPlanItemName
                        ? `Расшифровка: ${selectedBudgetPlanItemName}`
                        : "Расшифровка плана по месяцам"}
                    </CardTitle>
                    <CardDescription>
                      Проект: {selectedBudgetProjectName}. План, факт и остаток по каждой запланированной статье.
                    </CardDescription>
                  </div>
                  {selectedBudgetPlanItemName ? <Badge variant="secondary">Фильтр по статье</Badge> : null}
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b text-left text-sm text-muted-foreground">
                          <th className="pb-3">Месяц</th>
                          <th className="pb-3">Статья</th>
                          <th className="pb-3 text-right">План</th>
                          <th className="pb-3 text-right">Факт</th>
                          <th className="pb-3 text-right">Остаток</th>
                          <th className="pb-3 text-right">Исполнение</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleBudgetPlanningRows.map((row) => (
                          <tr
                            key={row.key}
                            className="cursor-pointer border-b border-border/60 transition-colors hover:bg-muted/40"
                            onClick={() =>
                              setSelectedBudgetPlanItemKey((current) =>
                                current === row.itemKey ? null : row.itemKey
                              )
                            }
                          >
                            <td className="py-3">{row.monthLabel}</td>
                            <td className="py-3 font-medium">{row.itemName}</td>
                            <td className="py-3 text-right">{formatCurrency(row.plannedAmount)}</td>
                            <td className="py-3 text-right text-rose-600 dark:text-rose-300">
                              {formatCurrency(row.actualAmount)}
                            </td>
                            <td className={`py-3 text-right ${row.balance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(row.balance)}
                            </td>
                            <td className="py-3 text-right">{Math.round(row.executionPercent)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="space-y-3">
                    <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">
                      Строки документов, из которых сложился план
                    </div>
                    {visibleBudgetPlanDetailRows.length === 0 ? (
                      <div className="rounded-[18px] border border-border/70 bg-background/70 p-4 text-sm text-muted-foreground">
                        Для выбранной статьи нет строк графика бюджета.
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full">
                          <thead>
                            <tr className="border-b text-left text-sm text-muted-foreground">
                              <th className="pb-3">Месяц</th>
                              <th className="pb-3">Статья</th>
                              <th className="pb-3">Документ</th>
                              <th className="pb-3 text-right">Сумма</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visibleBudgetPlanDetailRows.map((row) => (
                              <tr key={row.key} className="border-b border-border/60">
                                <td className="py-3">{row.monthLabel}</td>
                                <td className="py-3">{row.itemName}</td>
                                <td className="py-3">
                                  {row.documentHref ? (
                                    <Link className="text-primary hover:underline" href={row.documentHref}>
                                      Открыть
                                    </Link>
                                  ) : (
                                    <span className="text-muted-foreground">—</span>
                                  )}
                                </td>
                                <td className="py-3 text-right font-medium">{formatCurrency(row.amount)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
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
