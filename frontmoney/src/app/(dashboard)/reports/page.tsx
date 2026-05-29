"use client"

import { useEffect, useRef, useState } from "react"
import * as Dialog from "@radix-ui/react-dialog"
import { useRouter, useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { ResponsiveBar } from "@nivo/bar"
import { ResponsiveLine } from "@nivo/line"
import { ResponsivePie } from "@nivo/pie"
import {
  BarChart3,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Landmark,
  TrendingDown,
  TrendingUp,
  Wallet2,
  X,
} from "lucide-react"

import ExportReportButtons from "@/components/reports/export-report-buttons"
import { DocumentEditDialog, type EditableDocumentKind } from "@/components/shared/document-edit-dialog"
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
type RangePreset = "month" | "quarter" | "year" | "ytd" | null
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

type BudgetPlanningGroup = {
  key: string
  label: string
  plannedAmount: number
  actualAmount: number
  balance: number
  executionPercent: number
  rows: BudgetPlanningRow[]
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
  hidden: boolean
  balance: number
  share: number
}

type WalletFlowItem = {
  id: string
  name: string
  income: number
  expense: number
  net: number
  openingBalance: number
  endingBalance: number
  color: string
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

type ReportDocumentBreakdownRow = {
  key: string
  period: string
  documentId: string | null
  documentKind: EditableDocumentKind | null
  documentTypeLabel: string
  entryTypeLabel?: string
  walletName?: string | null
  itemName: string
  income?: number
  expense?: number
  net?: number
  amount?: number
}

type ReportDocumentBreakdown = {
  mode: "cashflow" | "budget"
  title: string
  description: string
  rows: ReportDocumentBreakdownRow[]
  totals: {
    income?: number
    expense?: number
    net?: number
    plan?: number
    actual?: number
    balance?: number
  }
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

const SHORT_MONTH_LABELS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
const MONTH_LABELS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]

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

function formatShortMonthLabel(value: string) {
  const [year, month] = value.split("-").map(Number)
  if (!year || !month || month < 1 || month > 12) {
    return value
  }
  return `${SHORT_MONTH_LABELS[month - 1]} ${String(year).slice(-2)}`
}

function formatShortDateLabel(value: string) {
  const [year, month, day] = getDateKey(value).split("-").map(Number)
  if (!year || !month || !day) {
    return value
  }
  return `${day}.${String(month).padStart(2, "0")}`
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

function getMonthValue(year: number, monthIndex: number) {
  return `${year}-${String(monthIndex + 1).padStart(2, "0")}`
}

function normalizeDateRange(from: string, to: string) {
  return from <= to ? { from, to } : { from: to, to: from }
}

function getReportTabFromParam(value: string | null): ReportTab {
  if (value === "expenses" || value === "categories") {
    return "categories"
  }
  if (value === "budget" || value === "cashflow" || value === "wallets") {
    return value
  }
  return "categories"
}

function getReportTabParam(value: ReportTab) {
  return value === "categories" ? "expenses" : value
}

function getEditableDocumentKind(documentType?: string | null): EditableDocumentKind | null {
  if (documentType === "Receipt") {
    return "receipt"
  }
  if (documentType === "Expenditure") {
    return "expenditure"
  }
  if (documentType === "Transfer") {
    return "transfer"
  }
  if (documentType === "Budget") {
    return "budget"
  }
  if (documentType === "AutoPayment") {
    return "auto-payment"
  }
  return null
}

function formatDocumentTypeLabel(documentType?: string | null) {
  return (
    {
      Receipt: "Приход",
      Expenditure: "Расход",
      Transfer: "Перевод",
      Budget: "Бюджет",
      AutoPayment: "Автосписание",
    }[documentType || ""] || documentType || "Документ"
  )
}

function formatBudgetEntryTypeLabel(entryType?: string | null) {
  return entryType === "budget" ? "План" : "Факт"
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
  const currentYear = new Date().getFullYear()
  const defaultDateFrom = `${currentYear}-01-01`
  const defaultDateTo = `${currentYear}-12-31`
  const hasExplicitPeriod = searchParams.has("date_from") || searchParams.has("date_to")
  const [timelineMode, setTimelineMode] = useState<TimelineMode>("daily")
  const [activeTab, setActiveTab] = useState<ReportTab>(getReportTabFromParam(searchParams.get("tab")))
  const [selectedPreset, setSelectedPreset] = useState<RangePreset>(hasExplicitPeriod ? null : "year")
  const [dateFrom, setDateFrom] = useState(searchParams.get("date_from") || defaultDateFrom)
  const [dateTo, setDateTo] = useState(searchParams.get("date_to") || defaultDateTo)
  const [draftDateFrom, setDraftDateFrom] = useState(searchParams.get("date_from") || defaultDateFrom)
  const [draftDateTo, setDraftDateTo] = useState(searchParams.get("date_to") || defaultDateTo)
  const [monthPickerYear, setMonthPickerYear] = useState(Number((searchParams.get("date_from") || defaultDateFrom).slice(0, 4)) || currentYear)
  const [monthSelectionAnchor, setMonthSelectionAnchor] = useState<string | null>(null)
  const [budgetForecast, setBudgetForecast] = useState(searchParams.get("budget_forecast") !== "false")
  const [budgetProjectId, setBudgetProjectId] = useState(searchParams.get("budget_project") || "")
  const [collapsedMonthlyGroups, setCollapsedMonthlyGroups] = useState<Record<string, boolean>>({})
  const [collapsedBudgetPlanGroups, setCollapsedBudgetPlanGroups] = useState<Record<string, boolean>>({})
  const [selectedWalletKey, setSelectedWalletKey] = useState<string | null>(null)
  const [selectedMonthlyExpenseItemKey, setSelectedMonthlyExpenseItemKey] = useState<string | null>(null)
  const [selectedBudgetPlanItemKey, setSelectedBudgetPlanItemKey] = useState<string | null>(null)
  const [hiddenWalletKeys, setHiddenWalletKeys] = useState<Record<string, boolean>>({})
  const [hiddenMonthlyExpenseItemKeys, setHiddenMonthlyExpenseItemKeys] = useState<Record<string, boolean>>({})
  const [hiddenBudgetPlanItemKeys, setHiddenBudgetPlanItemKeys] = useState<Record<string, boolean>>({})
  const [editingDocument, setEditingDocument] = useState<{ kind: EditableDocumentKind; id: string } | null>(null)
  const [documentBreakdown, setDocumentBreakdown] = useState<ReportDocumentBreakdown | null>(null)
  const [periodDialogOpen, setPeriodDialogOpen] = useState(false)
  const periodFromMonth = getMonthInputValue(draftDateFrom)
  const periodToMonth = getMonthInputValue(draftDateTo)
  const cashFlowChartRef = useRef<HTMLDivElement>(null)
  const walletChartRef = useRef<HTMLDivElement>(null)
  const categoryChartRef = useRef<HTMLDivElement>(null)
  const budgetExpenseChartRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    setDraftDateFrom(dateFrom)
    setDraftDateTo(dateTo)
    setMonthPickerYear(Number(dateFrom.slice(0, 4)) || currentYear)
    setMonthSelectionAnchor(null)
  }, [currentYear, dateFrom, dateTo])

  const projectsQuery = useQuery({
    queryKey: ["projects", "reports-budget"],
    staleTime: 300_000,
    queryFn: () => ProjectService.getProjects(),
  })

  const reportsQuery = useQuery({
    queryKey: [
      "reports-analytics",
      { dateFrom, dateTo, budgetForecast, budgetProjectId },
    ],
    staleTime: 60_000,
    queryFn: async () => {
      const [cashFlow, budgetExpense, overview] = await Promise.all([
        ReportService.getCashFlowReport({ dateFrom, dateTo }),
        ReportService.getBudgetExpenseReport({
          dateFrom,
          dateTo,
          limitByToday: budgetForecast,
          project: budgetProjectId || undefined,
        }),
        DashboardService.getOverview({ date: dateTo, hideHiddenWallets: false }),
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
    params.set("tab", getReportTabParam(activeTab))
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

  const handleSetActiveTab = (value: string) => {
    const nextTab = getReportTabFromParam(value)
    setActiveTab(nextTab)
    const params = new URLSearchParams(searchParams.toString())
    params.set("tab", getReportTabParam(nextTab))
    router.replace(`/reports?${params.toString()}`, { scroll: false })
  }

  const resetReportItemFilters = () => {
    setSelectedWalletKey(null)
    setSelectedMonthlyExpenseItemKey(null)
    setSelectedBudgetPlanItemKey(null)
    setHiddenWalletKeys({})
    setHiddenMonthlyExpenseItemKeys({})
    setHiddenBudgetPlanItemKeys({})
  }

  const handlePeriodDialogOpenChange = (open: boolean) => {
    setPeriodDialogOpen(open)
    if (open) {
      setDraftDateFrom(dateFrom)
      setDraftDateTo(dateTo)
      setMonthPickerYear(Number(dateFrom.slice(0, 4)) || currentYear)
      setMonthSelectionAnchor(null)
    }
  }

  const applyReportPeriod = (
    nextDateFrom = draftDateFrom,
    nextDateTo = draftDateTo,
    nextPreset: RangePreset = null
  ) => {
    if (!nextDateFrom || !nextDateTo) {
      return
    }
    const normalized = normalizeDateRange(nextDateFrom, nextDateTo)
    setDateFrom(normalized.from)
    setDateTo(normalized.to)
    setDraftDateFrom(normalized.from)
    setDraftDateTo(normalized.to)
    setSelectedPreset(nextPreset)
    resetReportItemFilters()
    updateReportUrl(normalized.from, normalized.to, budgetForecast)
    setPeriodDialogOpen(false)
  }

  const handleSelectMonth = (monthValue: string) => {
    if (!monthSelectionAnchor) {
      setMonthSelectionAnchor(monthValue)
      setDraftDateFrom(getMonthStartDate(monthValue))
      setDraftDateTo(getMonthEndDate(monthValue))
      setSelectedPreset(null)
      return
    }

    const fromMonth = monthSelectionAnchor <= monthValue ? monthSelectionAnchor : monthValue
    const toMonth = monthSelectionAnchor <= monthValue ? monthValue : monthSelectionAnchor
    setDraftDateFrom(getMonthStartDate(fromMonth))
    setDraftDateTo(getMonthEndDate(toMonth))
    setMonthSelectionAnchor(null)
    setSelectedPreset(null)
  }

  const setExactDateFrom = (nextDateFrom: string) => {
    setDraftDateFrom(nextDateFrom)
    setSelectedPreset(null)
    setMonthSelectionAnchor(null)
  }

  const setExactDateTo = (nextDateTo: string) => {
    setDraftDateTo(nextDateTo)
    setSelectedPreset(null)
    setMonthSelectionAnchor(null)
  }

  const setPresetRange = (preset: Exclude<RangePreset, null>) => {
    const today = new Date()
    let from = new Date(today)
    let to = new Date(today)

    if (preset === "month") {
      from = new Date(today.getFullYear(), today.getMonth(), 1)
      to = new Date(today.getFullYear(), today.getMonth() + 1, 0)
    }

    if (preset === "quarter") {
      const quarterStartMonth = Math.floor(today.getMonth() / 3) * 3
      from = new Date(today.getFullYear(), quarterStartMonth, 1)
      to = new Date(today.getFullYear(), quarterStartMonth + 3, 0)
    }

    if (preset === "year") {
      from = new Date(today.getFullYear(), 0, 1)
      to = new Date(today.getFullYear(), 11, 31)
    }

    if (preset === "ytd") {
      from = new Date(today.getFullYear(), 0, 1)
      to = today
    }

    const nextDateFrom = formatDateForInput(from)
    const nextDateTo = formatDateForInput(to)
    applyReportPeriod(nextDateFrom, nextDateTo, preset)
  }

  const toggleHiddenMonthlyExpenseItem = (itemKey: string) => {
    setHiddenMonthlyExpenseItemKeys((current) => {
      const next = { ...current }
      if (next[itemKey]) {
        delete next[itemKey]
      } else {
        next[itemKey] = true
      }
      return next
    })
  }

  const toggleHiddenWallet = (walletKey: string) => {
    setHiddenWalletKeys((current) => {
      const next = { ...current }
      if (next[walletKey]) {
        delete next[walletKey]
      } else {
        next[walletKey] = true
      }
      return next
    })
  }

  const toggleHiddenBudgetPlanItem = (itemKey: string) => {
    setHiddenBudgetPlanItemKeys((current) => {
      const next = { ...current }
      if (next[itemKey]) {
        delete next[itemKey]
      } else {
        next[itemKey] = true
      }
      return next
    })
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
  const openingWalletTotal = cashFlow.opening_balance
  const cumulativeEndingBalance = openingWalletTotal + netTotal
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
  const timelineChartRows = timelineRows.map((row) => ({
    ...row,
    chartLabel: timelineMode === "daily" ? formatShortDateLabel(row.key) : formatShortMonthLabel(row.key),
  }))
  let runningNet = openingWalletTotal
  const cumulativeLineData = [
    { x: "Старт", y: openingWalletTotal },
    ...timelineChartRows.map((row) => {
      runningNet += row.net
      return { x: row.chartLabel, y: runningNet }
    }),
  ]

  const cashFlowExportRows = timelineRows.map((row: TimelineRow) => ({
    period: row.label,
    income: row.income,
    expense: row.expense,
    net: row.net,
  }))

  const hiddenWalletKeySet = new Set(Object.keys(hiddenWalletKeys).filter((key) => hiddenWalletKeys[key]))
  const allWalletRows: WalletRow[] = overview.wallets
    .map((wallet: DashboardWalletSummary) => ({
      id: wallet.wallet_id,
      name: wallet.wallet_name,
      hidden: wallet.hidden,
      balance: wallet.balance,
      share: 0,
    }))
    .sort((left: WalletRow, right: WalletRow) => right.balance - left.balance)
  const activeSelectedWalletKey =
    selectedWalletKey &&
    allWalletRows.some((wallet) => wallet.id === selectedWalletKey) &&
    !hiddenWalletKeySet.has(selectedWalletKey)
      ? selectedWalletKey
      : null
  const visibleWalletBaseRows = allWalletRows.filter(
    (wallet) => !hiddenWalletKeySet.has(wallet.id) && (!activeSelectedWalletKey || wallet.id === activeSelectedWalletKey)
  )
  const visibleWalletAbsoluteBalance = visibleWalletBaseRows.reduce(
    (sum: number, wallet: WalletRow) => sum + Math.abs(wallet.balance),
    0
  )
  const walletRows: WalletRow[] = visibleWalletBaseRows.map((wallet) => ({
    ...wallet,
    share: visibleWalletAbsoluteBalance > 0 ? (Math.abs(wallet.balance) / visibleWalletAbsoluteBalance) * 100 : 0,
  }))
  const walletLegendAbsoluteBalance = allWalletRows.reduce(
    (sum: number, wallet: WalletRow) => sum + Math.abs(wallet.balance),
    0
  )
  const walletLegendRows = allWalletRows.map((wallet) => ({
    ...wallet,
    share: walletLegendAbsoluteBalance > 0 ? (Math.abs(wallet.balance) / walletLegendAbsoluteBalance) * 100 : 0,
  }))
  const positiveWalletRows = walletRows.filter((wallet: WalletRow) => wallet.balance > 0)
  const totalWalletBalance = walletRows.reduce((sum: number, wallet: WalletRow) => sum + wallet.balance, 0)
  const positiveWalletBalance = positiveWalletRows.reduce((sum: number, wallet: WalletRow) => sum + wallet.balance, 0)
  const negativeWalletBalance = walletRows.filter((wallet: WalletRow) => wallet.balance < 0).reduce((sum: number, wallet: WalletRow) => sum + wallet.balance, 0)
  const dominantWallet = walletRows[0] || null
  const selectedWalletName = activeSelectedWalletKey
    ? allWalletRows.find((wallet) => wallet.id === activeSelectedWalletKey)?.name ?? null
    : null
  const hiddenWalletCount = hiddenWalletKeySet.size

  const walletExportRows = walletRows.map((wallet: WalletRow) => ({
    name: wallet.name,
    balance: wallet.balance,
    share: wallet.share,
    hidden: wallet.hidden ? "Да" : "Нет",
  }))

  const walletFlowTotals = new Map<string, Omit<WalletFlowItem, "color">>()
  cashFlow.wallet_opening_balances.forEach((wallet) => {
    const walletId = wallet.wallet_id || wallet.wallet_name || "unknown"
    walletFlowTotals.set(walletId, {
      id: walletId,
      name: wallet.wallet_name || "Без кошелька",
      income: 0,
      expense: 0,
      net: 0,
      openingBalance: wallet.opening_balance,
      endingBalance: wallet.opening_balance,
    })
  })
  cashFlow.details.forEach((detail) => {
    const walletId = detail.wallet_id || detail.wallet_name || "unknown"
    const walletName = detail.wallet_name || "Без кошелька"
    const row = walletFlowTotals.get(walletId) || {
      id: walletId,
      name: walletName,
      income: 0,
      expense: 0,
      net: 0,
      openingBalance: 0,
      endingBalance: 0,
    }
    row.income += detail.income
    row.expense += detail.expense
    row.net = row.income - row.expense
    row.endingBalance = row.openingBalance + row.net
    walletFlowTotals.set(walletId, row)
  })
  const walletFlowLegendItems: WalletFlowItem[] = Array.from(walletFlowTotals.values())
    .sort((left, right) => Math.abs(right.net) + right.income + right.expense - (Math.abs(left.net) + left.income + left.expense))
    .map((wallet, index) => ({
      ...wallet,
      color: REPORT_ITEM_COLORS[index % REPORT_ITEM_COLORS.length],
    }))
  const walletFlowColorByName = new Map(walletFlowLegendItems.map((wallet) => [wallet.name, wallet.color]))
  const visibleWalletFlowLegendItems = walletFlowLegendItems
    .filter((wallet) => !hiddenWalletKeySet.has(wallet.id))
    .filter((wallet) => (activeSelectedWalletKey ? wallet.id === activeSelectedWalletKey : true))
  const walletFlowLineData = visibleWalletFlowLegendItems.map((wallet) => {
    let runningWalletBalance = wallet.openingBalance
    return {
      id: wallet.name,
      data: [
        { x: "Старт", y: runningWalletBalance },
        ...timelineChartRows.map((periodRow) => {
          const periodDetails = cashFlow.details.filter((detail) => {
            const detailWalletKey = detail.wallet_id || detail.wallet_name || "unknown"
            const detailPeriodKey = timelineMode === "daily" ? getDateKey(detail.period) : getMonthKey(detail.period)
            return detailWalletKey === wallet.id && detailPeriodKey === periodRow.key
          })
          const periodNet = periodDetails.reduce((sum, detail) => sum + detail.income - detail.expense, 0)
          runningWalletBalance += periodNet
          return {
            x: periodRow.chartLabel,
            y: runningWalletBalance,
          }
        }),
      ],
    }
  })

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
  const hiddenMonthlyExpenseItemKeySet = new Set(
    monthlyExpenseLegendItems.filter((item) => hiddenMonthlyExpenseItemKeys[item.key]).map((item) => item.key)
  )
  const hiddenMonthlyExpenseItemCount = hiddenMonthlyExpenseItemKeySet.size
  const activeSelectedMonthlyExpenseItemKey =
    selectedMonthlyExpenseItemKey &&
    monthlyExpenseItemTotals.has(selectedMonthlyExpenseItemKey) &&
    !hiddenMonthlyExpenseItemKeySet.has(selectedMonthlyExpenseItemKey)
      ? selectedMonthlyExpenseItemKey
      : null
  const selectedMonthlyExpenseItemName =
    activeSelectedMonthlyExpenseItemKey
      ? monthlyExpenseItems.find((item) => item.key === activeSelectedMonthlyExpenseItemKey)?.name ?? null
      : null
  const visibleMonthlyCashFlowGroups = monthlyCashFlowGroups
    .map((group) => {
      const rows = group.rows.filter((row) => {
        if (hiddenMonthlyExpenseItemKeySet.has(row.itemKey)) {
          return false
        }
        return activeSelectedMonthlyExpenseItemKey ? row.itemKey === activeSelectedMonthlyExpenseItemKey : true
      })
      const income = rows.reduce((sum, row) => sum + row.income, 0)
      const expense = rows.reduce((sum, row) => sum + row.expense, 0)
      return {
        ...group,
        income,
        expense,
        net: income - expense,
        rows,
      }
    })
    .filter((group) => group.rows.length > 0)
  const visibleMonthlyIncomeTotal = visibleMonthlyCashFlowGroups.reduce((sum, group) => sum + group.income, 0)
  const visibleMonthlyExpenseTotal = visibleMonthlyCashFlowGroups.reduce((sum, group) => sum + group.expense, 0)
  const visibleMonthlyNetTotal = visibleMonthlyIncomeTotal - visibleMonthlyExpenseTotal
  const monthlyExpenseChartKeys = monthlyExpenseLegendItems
    .filter((item) => !hiddenMonthlyExpenseItemKeySet.has(item.key))
    .filter((item) => (activeSelectedMonthlyExpenseItemKey ? item.key === activeSelectedMonthlyExpenseItemKey : true))
    .map((item) => item.key)
  const monthlyExpenseChartRows = visibleMonthlyCashFlowGroups.map((group) => {
    const chartRow: Record<string, string | number> = {
      month: formatShortMonthLabel(group.key),
    }
    group.rows
      .filter((row) => row.expense > 0)
      .forEach((row) => {
        chartRow[row.itemKey] = (Number(chartRow[row.itemKey]) || 0) + row.expense
      })
    return chartRow
  })
  const monthlyCashFlowExportRows = visibleMonthlyCashFlowGroups.flatMap((group) => group.rows).map((row) => ({
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
  const hiddenBudgetPlanItemKeySet = new Set(
    budgetPlanLegendItems.filter((item) => hiddenBudgetPlanItemKeys[item.key]).map((item) => item.key)
  )
  const hiddenBudgetPlanItemCount = hiddenBudgetPlanItemKeySet.size
  const activeSelectedBudgetPlanItemKey =
    selectedBudgetPlanItemKey &&
    budgetPlanItemTotals.has(selectedBudgetPlanItemKey) &&
    !hiddenBudgetPlanItemKeySet.has(selectedBudgetPlanItemKey)
      ? selectedBudgetPlanItemKey
      : null
  const selectedBudgetPlanItemName =
    activeSelectedBudgetPlanItemKey
      ? budgetPlanItems.find((item) => item.key === activeSelectedBudgetPlanItemKey)?.name ?? null
      : null
  const visibleBudgetPlanningRows = budgetPlanningRows.filter((row) => {
    if (hiddenBudgetPlanItemKeySet.has(row.itemKey)) {
      return false
    }
    return activeSelectedBudgetPlanItemKey ? row.itemKey === activeSelectedBudgetPlanItemKey : true
  })
  const visibleBudgetPlanningGroupMap = new Map<string, BudgetPlanningGroup>()
  visibleBudgetPlanningRows.forEach((row) => {
    const group = visibleBudgetPlanningGroupMap.get(row.monthKey) || {
      key: row.monthKey,
      label: row.monthLabel,
      plannedAmount: 0,
      actualAmount: 0,
      balance: 0,
      executionPercent: 0,
      rows: [],
    }
    group.plannedAmount += row.plannedAmount
    group.actualAmount += row.actualAmount
    group.balance = group.plannedAmount - group.actualAmount
    group.executionPercent =
      group.plannedAmount > 0 ? (group.actualAmount / group.plannedAmount) * 100 : 0
    group.rows.push(row)
    visibleBudgetPlanningGroupMap.set(row.monthKey, group)
  })
  const visibleBudgetPlanningGroups = Array.from(visibleBudgetPlanningGroupMap.values()).sort((left, right) =>
    left.key.localeCompare(right.key)
  )
  const visibleBudgetPlannedTotal = visibleBudgetPlanningRows.reduce((sum, row) => sum + row.plannedAmount, 0)
  const visibleBudgetActualTotal = visibleBudgetPlanningRows.reduce((sum, row) => sum + row.actualAmount, 0)
  const visibleBudgetBalanceTotal = visibleBudgetPlannedTotal - visibleBudgetActualTotal
  const visibleBudgetExecutionPercent =
    visibleBudgetPlannedTotal > 0 ? (visibleBudgetActualTotal / visibleBudgetPlannedTotal) * 100 : 0
  const budgetPlanChartKeys = budgetPlanLegendItems
    .filter((item) => !hiddenBudgetPlanItemKeySet.has(item.key))
    .filter((item) => (activeSelectedBudgetPlanItemKey ? item.key === activeSelectedBudgetPlanItemKey : true))
    .map((item) => item.key)
  const budgetPlanChartRows = budgetPlanMonthKeys.map((monthKey) => {
    const chartRow: Record<string, string | number> = {
      month: formatShortMonthLabel(monthKey),
    }
    visibleBudgetPlanningRows
      .filter((row) => row.monthKey === monthKey)
      .forEach((row) => {
        chartRow[row.itemKey] = (Number(chartRow[row.itemKey]) || 0) + row.plannedAmount
    })
    return chartRow
  })
  const budgetPlanExportRows = visibleBudgetPlanningRows.map((row) => ({
    month: row.monthLabel,
    cashFlowItem: row.itemName,
    plannedAmount: row.plannedAmount,
    actualAmount: row.actualAmount,
    balance: row.balance,
    executionPercent: row.executionPercent,
  }))

  const openDocument = (documentId: string | null, documentKind: EditableDocumentKind | null) => {
    if (!documentId || !documentKind) {
      return
    }
    setDocumentBreakdown(null)
    setEditingDocument({ kind: documentKind, id: documentId })
  }

  const openMonthlyCashFlowBreakdown = (row: MonthlyCashFlowItemRow) => {
    const rows: ReportDocumentBreakdownRow[] = cashFlow.details
      .filter((detail) => getMonthKey(detail.period) === row.monthKey)
      .filter((detail) => (detail.cash_flow_item_id || detail.cash_flow_item_name || "unknown") === row.itemKey)
      .map((detail, index) => {
        const documentKind = getEditableDocumentKind(detail.document_type)
        const net = detail.income - detail.expense
        return {
          key: `${detail.document_id || "unknown"}:${detail.period}:${index}:${detail.income}:${detail.expense}`,
          period: detail.period,
          documentId: detail.document_id ?? null,
          documentKind,
          documentTypeLabel: formatDocumentTypeLabel(detail.document_type),
          walletName: detail.wallet_name,
          itemName: detail.cash_flow_item_name || "Неизвестная статья",
          income: detail.income,
          expense: detail.expense,
          net,
        }
      })

    const income = rows.reduce((sum, detail) => sum + (detail.income || 0), 0)
    const expense = rows.reduce((sum, detail) => sum + (detail.expense || 0), 0)
    setDocumentBreakdown({
      mode: "cashflow",
      title: `Документы: ${row.itemName}`,
      description: `${row.monthLabel} · приход ${formatCurrency(income)} · расход ${formatCurrency(expense)}`,
      rows,
      totals: {
        income,
        expense,
        net: income - expense,
      },
    })
  }

  const openBudgetPlanBreakdown = (row: BudgetPlanningRow) => {
    const rows: ReportDocumentBreakdownRow[] = budgetExpense.details
      .filter((detail) => getMonthKey(detail.period) === row.monthKey)
      .filter((detail) => (detail.cash_flow_item_id || detail.cash_flow_item_name || "unknown") === row.itemKey)
      .map((detail, index) => {
        const documentKind = getEditableDocumentKind(detail.document_type)
        return {
          key: `${detail.entry_type}:${detail.document_id || "unknown"}:${detail.period}:${index}:${detail.amount}`,
          period: detail.period,
          documentId: detail.document_id ?? null,
          documentKind,
          documentTypeLabel: formatDocumentTypeLabel(detail.document_type),
          entryTypeLabel: formatBudgetEntryTypeLabel(detail.entry_type),
          itemName: detail.cash_flow_item_name || "Неизвестная статья",
          amount: detail.amount,
        }
      })

    const plan = rows
      .filter((detail) => detail.entryTypeLabel === "План")
      .reduce((sum, detail) => sum + (detail.amount || 0), 0)
    const actual = rows
      .filter((detail) => detail.entryTypeLabel !== "План")
      .reduce((sum, detail) => sum + (detail.amount || 0), 0)

    setDocumentBreakdown({
      mode: "budget",
      title: `Документы: ${row.itemName}`,
      description: `${row.monthLabel} · план ${formatCurrency(plan)} · факт ${formatCurrency(actual)}`,
      rows,
      totals: {
        plan,
        actual,
        balance: plan - actual,
      },
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Отчеты"
        title="Аналитика денег"
        description="Расходы, бюджет, чистый поток и кошельки за выбранный период."
        compact
        actions={
          <Button
            type="button"
            variant="outline"
            className="h-auto max-w-full rounded-full px-4 py-2.5 text-sm font-semibold tracking-[-0.02em] shadow-sm"
            onClick={() => handlePeriodDialogOpenChange(true)}
          >
            <CalendarDays className="mr-2 h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 truncate">
              Период: {formatDate(dateFrom)} — {formatDate(dateTo)}
            </span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 text-muted-foreground" />
          </Button>
        }
      />

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

      <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Доходы за период" value={formatCurrency(incomeTotal)} hint="Все зафиксированные поступления" icon={TrendingUp} tone="positive" />
        <StatCard label="Расходы за период" value={formatCurrency(expenseTotal)} hint="Все списания по выбранному периоду" icon={TrendingDown} tone="danger" />
        <StatCard
          label="Чистый поток"
          value={formatCurrency(netTotal)}
          hint={`Начальный остаток: ${formatCurrency(openingWalletTotal)} · итог: ${formatCurrency(cumulativeEndingBalance)}`}
          icon={BarChart3}
          tone={netTotal >= 0 ? "positive" : "danger"}
        />
        <StatCard label="Бюджетный факт" value={formatCurrency(includedExpenseTotal)} hint={`${plannedBudgetCount} строк отчета по расходному бюджету`} icon={Landmark} />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={handleSetActiveTab}
        className="space-y-5"
      >
        <TabsList className="grid h-auto grid-cols-2 gap-2 rounded-[18px] bg-muted/60 p-1.5 xl:grid-cols-4">
          <TabsTrigger value="categories" className="rounded-[14px] py-2.5">
            Расходы
          </TabsTrigger>
          <TabsTrigger value="budget" className="rounded-[14px] py-2.5">
            Бюджет
          </TabsTrigger>
          <TabsTrigger value="cashflow" className="rounded-[14px] py-2.5">
            Поток денег
          </TabsTrigger>
          <TabsTrigger value="wallets" className="rounded-[14px] py-2.5">
            Кошельки
          </TabsTrigger>
        </TabsList>

        {isBudgetTab ? (
          <Card>
            <CardContent className="space-y-4 p-4">
              <div className="grid gap-4 lg:grid-cols-[minmax(260px,0.8fr)_minmax(0,1fr)]">
                <div className="space-y-2">
                  <Label htmlFor="budget-project">Проект бюджета</Label>
                  <Select
                    value={budgetProjectId || "none"}
                    onValueChange={(value) => {
                      const nextBudgetProjectId = value === "none" ? "" : value
                      setBudgetProjectId(nextBudgetProjectId)
                      setSelectedBudgetPlanItemKey(null)
                      setHiddenBudgetPlanItemKeys({})
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
                <div className="flex flex-col gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="space-y-1">
                    <Label htmlFor="budget-forecast-mode" className="cursor-pointer">
                      Прогноз бюджета
                    </Label>
                    <div className="text-sm leading-5 text-muted-foreground">
                      План до даты окончания, факт можно ограничить сегодняшним днем.
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
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">Проект: {selectedBudgetProjectName}</Badge>
                {isFutureReportDate && budgetForecast ? <Badge variant="secondary">Прогноз включен</Badge> : null}
              </div>
            </CardContent>
          </Card>
        ) : null}

        <Dialog.Root open={periodDialogOpen} onOpenChange={handlePeriodDialogOpenChange}>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-sm" />
            <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(calc(100vw-18px),1040px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[28px] border border-border/70 bg-background shadow-[0_35px_120px_-45px_rgba(15,23,42,0.85)]">
              <div className="flex items-start justify-between gap-4 border-b border-border/60 px-5 py-4 sm:px-6">
                <div className="min-w-0">
                  <Dialog.Title className="text-xl font-semibold tracking-[-0.03em] text-foreground">
                    Период отчета
                  </Dialog.Title>
                  <Dialog.Description className="mt-1 text-sm leading-5 text-muted-foreground">
                    Быстрый выбор диапазона месяцев, точные даты можно уточнить ниже.
                  </Dialog.Description>
                </div>
                <Dialog.Close asChild>
                  <Button variant="ghost" size="icon" className="shrink-0 rounded-2xl" aria-label="Закрыть">
                    <X className="h-4 w-4" />
                  </Button>
                </Dialog.Close>
              </div>

              <div className="max-h-[calc(92vh-92px)] overflow-y-auto px-4 py-4 sm:px-6">
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2">
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

                  <div className="grid gap-4 xl:grid-cols-[minmax(280px,0.8fr)_minmax(0,1fr)]">
                    <div className="rounded-[22px] border border-border/70 bg-background/70 p-3">
                      <div className="flex items-center justify-between gap-3">
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="h-9 w-9 rounded-2xl"
                          onClick={() => setMonthPickerYear((year) => year - 1)}
                          aria-label="Предыдущий год"
                        >
                          <ChevronLeft className="h-4 w-4" />
                        </Button>
                        <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">{monthPickerYear}</div>
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          className="h-9 w-9 rounded-2xl"
                          onClick={() => setMonthPickerYear((year) => year + 1)}
                          aria-label="Следующий год"
                        >
                          <ChevronRight className="h-4 w-4" />
                        </Button>
                      </div>
                      <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4 xl:grid-cols-3">
                        {MONTH_LABELS.map((label, index) => {
                          const monthValue = getMonthValue(monthPickerYear, index)
                          const isInRange = monthValue >= periodFromMonth && monthValue <= periodToMonth
                          const isEdge = monthValue === periodFromMonth || monthValue === periodToMonth
                          const isAnchor = monthSelectionAnchor === monthValue

                          return (
                            <button
                              key={monthValue}
                              type="button"
                              className={`rounded-2xl border px-3 py-2 text-sm font-medium transition ${
                                isEdge || isAnchor
                                  ? "border-primary bg-primary text-primary-foreground"
                                  : isInRange
                                    ? "border-primary/40 bg-primary/10 text-foreground"
                                    : "border-border/60 bg-card/50 text-muted-foreground hover:border-primary/60 hover:text-foreground"
                              }`}
                              onClick={() => handleSelectMonth(monthValue)}
                            >
                              {label}
                            </button>
                          )
                        })}
                      </div>
                      <div className="mt-3 text-xs leading-5 text-muted-foreground">
                        Выбери начальный и конечный месяц. Точный день можно поправить справа.
                      </div>
                    </div>

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label htmlFor="reports-date-from">Дата с</Label>
                        <Input
                          id="reports-date-from"
                          type="date"
                          value={draftDateFrom}
                          onChange={(event) => setExactDateFrom(event.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="reports-date-to">Дата по</Label>
                        <Input
                          id="reports-date-to"
                          type="date"
                          value={draftDateTo}
                          onChange={(event) => setExactDateTo(event.target.value)}
                        />
                      </div>
                      <div className="md:col-span-2">
                        <Button
                          type="button"
                          onClick={() => applyReportPeriod()}
                          disabled={!draftDateFrom || !draftDateTo || (draftDateFrom === dateFrom && draftDateTo === dateTo)}
                          className="w-full sm:w-auto"
                        >
                          Применить период
                        </Button>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-[18px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
                    Будет применено: с {formatDate(draftDateFrom)} по {formatDate(draftDateTo)}
                  </div>
                </div>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>

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
                      data={timelineChartRows}
                      keys={["income", "expense"]}
                      indexBy="chartLabel"
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
                <CardDescription>
                  Показывает все кошельки, включая скрытые. Клик по названию фильтрует отчет, глаз исключает кошелек.
                </CardDescription>
              </div>
              <ExportReportButtons
                data={walletExportRows}
                columns={[
                  { key: "name", header: "Кошелек" },
                  { key: "balance", header: "Баланс", formatter: exportFormatters.currency },
                  { key: "share", header: "Доля", formatter: exportFormatters.percent },
                  { key: "hidden", header: "Скрытый" },
                ]}
                filename="wallet-structure-report"
                title="Структура балансов по кошелькам"
                chartRef={walletChartRef}
              />
            </CardHeader>
          </Card>

          <div className="grid gap-4 md:grid-cols-3">
            <StatCard label="Общий баланс" value={formatCurrency(totalWalletBalance)} hint="Сумма по кошелькам в отчете" icon={Wallet2} tone={totalWalletBalance >= 0 ? "positive" : "danger"} />
            <StatCard label="Положительные балансы" value={formatCurrency(positiveWalletBalance)} hint="Включенные кошельки с положительным остатком" icon={TrendingUp} tone="positive" />
            <StatCard label="Отрицательные балансы" value={formatCurrency(negativeWalletBalance)} hint="Включенные кошельки в минусе или долге" icon={TrendingDown} tone="danger" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Кумулятивный поток по кошелькам</CardTitle>
              <CardDescription>
                Та же динамика, что в потоке денег, но отдельной линией по каждому кошельку.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {walletFlowLegendItems.length === 0 ? (
                <div className="py-16 text-center text-sm text-muted-foreground">
                  За выбранный период нет движений по кошелькам.
                </div>
              ) : (
                <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                  <div className="h-[360px] min-w-0 rounded-[22px] border border-border/70 bg-background/70 p-3">
                    {walletFlowLineData.length === 0 ? (
                      <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
                        Все кошельки скрыты или выбранный кошелек исключен из отчета.
                      </div>
                    ) : (
                      <ResponsiveLine
                        data={walletFlowLineData}
                        margin={{ top: 22, right: 20, bottom: 56, left: 64 }}
                        xScale={{ type: "point" }}
                        yScale={{ type: "linear", stacked: false }}
                        axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -25 }}
                        axisLeft={{ tickSize: 0, tickPadding: 8, format: (value) => formatCompactCurrency(Number(value)) }}
                        enableGridX={false}
                        curve="monotoneX"
                        pointSize={7}
                        pointBorderWidth={2}
                        pointBorderColor={{ from: "serieColor" }}
                        colors={(series) => walletFlowColorByName.get(String(series.id)) ?? REPORT_ITEM_COLORS[0]}
                        useMesh
                        tooltip={({ point }) => (
                          <div className="rounded border bg-background px-2 py-1 text-xs shadow-sm">
                            {String(point.seriesId)} · {String(point.data.x)}: {formatCurrency(Number(point.data.y))}
                          </div>
                        )}
                      />
                    )}
                  </div>
                  <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold tracking-[-0.02em]">Легенда кошельков</div>
                        <div className="mt-1 text-xs text-muted-foreground">Название — отбор. Глаз — исключить.</div>
                      </div>
                      {selectedWalletName || hiddenWalletCount > 0 ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setSelectedWalletKey(null)
                            setHiddenWalletKeys({})
                          }}
                        >
                          Сбросить
                        </Button>
                      ) : null}
                    </div>
                    <div className="mt-4 max-h-[300px] space-y-2 overflow-y-auto pr-1">
                      {walletFlowLegendItems.map((wallet) => {
                        const isSelected = activeSelectedWalletKey === wallet.id
                        const isHidden = hiddenWalletKeySet.has(wallet.id)
                        return (
                          <div
                            key={wallet.id}
                            className={`flex items-stretch gap-2 rounded-2xl border px-3 py-2 transition ${
                              isSelected
                                ? "border-primary bg-primary/10"
                                : isHidden
                                  ? "border-border/40 bg-muted/30 opacity-60"
                                  : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                            }`}
                          >
                            <button
                              type="button"
                              className="min-w-0 flex-1 text-left"
                              onClick={() => setSelectedWalletKey((current) => (current === wallet.id ? null : wallet.id))}
                            >
                              <div className="flex items-center gap-2">
                                <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: wallet.color }} />
                                <span className={`min-w-0 flex-1 truncate text-sm font-medium ${isHidden ? "line-through" : ""}`}>
                                  {wallet.name}
                                </span>
                              </div>
                              <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                <span>Поток {formatCurrency(wallet.net)}</span>
                                <span className={wallet.net >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}>
                                  {formatCurrency(wallet.endingBalance)}
                                </span>
                              </div>
                            </button>
                            <button
                              type="button"
                              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background/80 text-muted-foreground transition hover:border-primary/60 hover:text-primary"
                              aria-label={isHidden ? "Вернуть кошелек в отчет" : "Исключить кошелек из отчета"}
                              title={isHidden ? "Вернуть кошелек" : "Исключить кошелек"}
                              onClick={() => {
                                if (!isHidden && isSelected) {
                                  setSelectedWalletKey(null)
                                }
                                toggleHiddenWallet(wallet.id)
                              }}
                            >
                              {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {allWalletRows.length === 0 ? (
            renderNoData("Нет данных по кошелькам", "В системе пока нет кошельков с доступными балансами.")
          ) : (
            <div className="grid gap-6 xl:grid-cols-2">
              <Card>
                <CardHeader>
                  <CardTitle>Распределение положительных балансов</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
                    {positiveWalletRows.length === 0 ? (
                      <div className="py-20 text-center text-sm text-muted-foreground">
                        Нет включенных кошельков с положительным балансом для круговой диаграммы.
                      </div>
                    ) : (
                      <div className="h-[380px]" ref={walletChartRef}>
                        <ResponsivePie
                          data={positiveWalletRows.map((wallet) => ({
                            id: wallet.name,
                            label: wallet.name,
                            value: wallet.balance,
                          }))}
                          margin={{ top: 20, right: 20, bottom: 20, left: 20 }}
                          innerRadius={0.58}
                          padAngle={1}
                          cornerRadius={4}
                          activeOuterRadiusOffset={8}
                          tooltip={({ datum }) => (
                            <div className="rounded border bg-background px-2 py-1 text-xs">
                              {String(datum.label)}: {formatCurrency(Number(datum.value))}
                            </div>
                          )}
                          colors={{ scheme: "category10" }}
                        />
                      </div>
                    )}
                    <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold tracking-[-0.02em]">Легенда кошельков</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Название — отбор. Глаз — исключить из отчета.
                          </div>
                        </div>
                        {selectedWalletName || hiddenWalletCount > 0 ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedWalletKey(null)
                              setHiddenWalletKeys({})
                            }}
                          >
                            Сбросить
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-4 max-h-[300px] space-y-2 overflow-y-auto pr-1">
                        {walletLegendRows.map((wallet) => {
                          const isSelected = activeSelectedWalletKey === wallet.id
                          const isHidden = hiddenWalletKeySet.has(wallet.id)
                          return (
                            <div
                              key={wallet.id}
                              className={`flex items-stretch gap-2 rounded-2xl border px-3 py-2 transition ${
                                isSelected
                                  ? "border-primary bg-primary/10"
                                  : isHidden
                                    ? "border-border/40 bg-muted/30 opacity-60"
                                    : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                              }`}
                            >
                              <button
                                type="button"
                                className="min-w-0 flex-1 text-left"
                                onClick={() =>
                                  setSelectedWalletKey((current) => (current === wallet.id ? null : wallet.id))
                                }
                              >
                                <div className="flex items-center gap-2">
                                  <span
                                    className={`min-w-0 flex-1 truncate text-sm font-medium ${isHidden ? "line-through" : ""}`}
                                  >
                                    {wallet.name}
                                  </span>
                                  {wallet.hidden ? <Badge variant="outline">скрыт</Badge> : null}
                                </div>
                                <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                  <span>{isHidden ? "Исключен" : `${wallet.share.toFixed(1)}% от баланса`}</span>
                                  <span className={wallet.balance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}>
                                    {formatCurrency(wallet.balance)}
                                  </span>
                                </div>
                              </button>
                              <button
                                type="button"
                                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background/80 text-muted-foreground transition hover:border-primary/60 hover:text-primary"
                                aria-label={isHidden ? "Вернуть кошелек в отчет" : "Исключить кошелек из отчета"}
                                title={isHidden ? "Вернуть кошелек" : "Исключить кошелек"}
                                onClick={() => {
                                  if (!isHidden && isSelected) {
                                    setSelectedWalletKey(null)
                                  }
                                  toggleHiddenWallet(wallet.id)
                                }}
                              >
                                {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Детализация балансов</CardTitle>
                  {selectedWalletName ? <CardDescription>Фильтр: {selectedWalletName}</CardDescription> : null}
                </CardHeader>
                <CardContent>
                  {walletRows.length === 0 ? (
                    <div className="py-16 text-center text-sm text-muted-foreground">
                      Все кошельки исключены из отчета. Верни кошелек через легенду или сбрось фильтры.
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                    <table className="w-full text-[13px] sm:text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs text-muted-foreground">
                          <th className="pb-3">Кошелек</th>
                          <th className="pb-3 text-right">Баланс</th>
                          <th className="pb-3 text-right">Доля</th>
                          <th className="pb-3 text-right">Видимость</th>
                        </tr>
                      </thead>
                      <tbody>
                        {walletRows.map((wallet) => (
                          <tr key={wallet.id} className="border-b border-border/60">
                            <td className="py-2.5">
                              <span className="inline-flex items-center gap-2">
                                {wallet.name}
                                {wallet.hidden ? <Badge variant="outline">скрыт</Badge> : null}
                              </span>
                            </td>
                            <td className={`py-2.5 text-right font-medium ${wallet.balance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(wallet.balance)}
                            </td>
                            <td className="py-2.5 text-right text-muted-foreground">{wallet.share.toFixed(1)}%</td>
                            <td className="py-2.5 text-right">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8"
                                aria-label="Исключить кошелек из отчета"
                                title="Исключить кошелек"
                                onClick={() => {
                                  if (activeSelectedWalletKey === wallet.id) {
                                    setSelectedWalletKey(null)
                                  }
                                  toggleHiddenWallet(wallet.id)
                                }}
                              >
                                <Eye className="h-4 w-4" />
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr className="border-t bg-muted/40 text-sm font-semibold">
                          <td className="py-3">Итого по отчету</td>
                          <td className={`py-3 text-right ${totalWalletBalance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                            {formatCurrency(totalWalletBalance)}
                          </td>
                          <td className="py-3 text-right text-muted-foreground">100%</td>
                          <td />
                        </tr>
                      </tfoot>
                    </table>
                    </div>
                  )}
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
                      Клик по легенде включает отбор, глаз исключает статью. Клик по строке таблицы открывает документы.
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedMonthlyExpenseItemName ? (
                      <Button variant="outline" size="sm" onClick={() => setSelectedMonthlyExpenseItemKey(null)}>
                        Снять отбор
                      </Button>
                    ) : null}
                    {hiddenMonthlyExpenseItemCount > 0 ? (
                      <Button variant="outline" size="sm" onClick={() => setHiddenMonthlyExpenseItemKeys({})}>
                        Показать все
                      </Button>
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="h-[420px] min-w-0" ref={categoryChartRef}>
                      {monthlyExpenseChartKeys.length === 0 ? (
                        <div className="flex h-full items-center justify-center rounded-[22px] border border-dashed border-border/70 text-sm text-muted-foreground">
                          Нет видимых статей для графика. Сними отбор или верни скрытые статьи.
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
                          onClick={(bar) => {
                            const itemKey = String(bar.id)
                            if (monthlyExpenseItemTotals.has(itemKey)) {
                              setSelectedMonthlyExpenseItemKey((current) => (current === itemKey ? null : itemKey))
                            }
                          }}
                        />
                      )}
                    </div>
                    <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold tracking-[-0.02em]">Легенда расходных статей</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Название — отбор. Глаз — исключить из отчета.
                          </div>
                        </div>
                        {selectedMonthlyExpenseItemName || hiddenMonthlyExpenseItemCount > 0 ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedMonthlyExpenseItemKey(null)
                              setHiddenMonthlyExpenseItemKeys({})
                            }}
                          >
                            Сбросить
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
                            const isHidden = hiddenMonthlyExpenseItemKeySet.has(item.key)
                            return (
                              <div
                                key={item.key}
                                className={`flex items-stretch gap-2 rounded-2xl border px-3 py-2 transition ${
                                  isSelected
                                    ? "border-primary bg-primary/10"
                                    : isHidden
                                      ? "border-border/40 bg-muted/30 opacity-60"
                                      : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                                }`}
                              >
                                <button
                                  type="button"
                                  className="min-w-0 flex-1 text-left"
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
                                    <span className={`min-w-0 flex-1 truncate text-sm font-medium ${isHidden ? "line-through" : ""}`}>
                                      {item.name}
                                    </span>
                                    <span className="text-sm font-semibold text-rose-600 dark:text-rose-300">
                                      {formatCurrency(item.expense)}
                                    </span>
                                  </div>
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    {isHidden ? "Исключена" : `${item.share.toFixed(1)}% от расходов`}
                                  </div>
                                </button>
                                <button
                                  type="button"
                                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background/80 text-muted-foreground transition hover:border-primary/60 hover:text-primary"
                                  aria-label={isHidden ? "Вернуть статью в отчет" : "Исключить статью из отчета"}
                                  title={isHidden ? "Вернуть статью" : "Исключить статью"}
                                  onClick={() => {
                                    if (!isHidden && isSelected) {
                                      setSelectedMonthlyExpenseItemKey(null)
                                    }
                                    toggleHiddenMonthlyExpenseItem(item.key)
                                  }}
                                >
                                  {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                </button>
                              </div>
                            )
                          })
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
                  {hiddenMonthlyExpenseItemCount > 0 ? (
                    <Badge variant="secondary">Исключено: {hiddenMonthlyExpenseItemCount}</Badge>
                  ) : null}
                </CardHeader>
                <CardContent>
                  {visibleMonthlyCashFlowGroups.length === 0 ? (
                    <div className="rounded-[18px] border border-border/70 bg-background/70 p-4 text-sm text-muted-foreground">
                      Нет видимых строк. Сними отбор или верни скрытые статьи.
                    </div>
                  ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-[13px] sm:text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs text-muted-foreground">
                          <th className="pb-3">Месяц / статья</th>
                          <th className="pb-3 text-right">Приход</th>
                          <th className="pb-3 text-right">Расход</th>
                          <th className="pb-3 text-right">Итог</th>
                        </tr>
                      </thead>
                      {visibleMonthlyCashFlowGroups.map((group) => {
                        const isCollapsed = collapsedMonthlyGroups[group.key] ?? true

                        return (
                        <tbody key={group.key}>
                          <tr
                            className="cursor-pointer border-b border-border bg-muted/40 font-semibold transition-colors hover:bg-muted/60"
                            onClick={() =>
                              setCollapsedMonthlyGroups((current) => ({
                                ...current,
                                [group.key]: !(current[group.key] ?? true),
                              }))
                            }
                          >
                            <td className="py-2.5">
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
                            <td className="py-2.5 text-right text-emerald-600 dark:text-emerald-300">
                              {formatCurrency(group.income)}
                            </td>
                            <td className="py-2.5 text-right text-rose-600 dark:text-rose-300">
                              {formatCurrency(group.expense)}
                            </td>
                            <td className={`py-2.5 text-right ${group.net >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(group.net)}
                            </td>
                          </tr>
                          {isCollapsed ? null : group.rows.map((row) => (
                            <tr
                              key={row.key}
                              className="cursor-pointer border-b border-border/60 transition-colors hover:bg-muted/40"
                              onClick={() => openMonthlyCashFlowBreakdown(row)}
                            >
                              <td className="py-2.5 pl-5 font-medium">{row.itemName}</td>
                              <td className="py-2.5 text-right text-emerald-600 dark:text-emerald-300">
                                {row.income > 0 ? formatCurrency(row.income) : "—"}
                              </td>
                              <td className="py-2.5 text-right text-rose-600 dark:text-rose-300">
                                {row.expense > 0 ? formatCurrency(row.expense) : "—"}
                              </td>
                              <td className={`py-2.5 text-right ${row.net >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                {formatCurrency(row.net)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      )})}
                      <tfoot>
                        <tr className="border-t bg-muted/40 text-sm font-semibold">
                          <td className="py-3">Итого по отчету</td>
                          <td className="py-3 text-right text-emerald-600 dark:text-emerald-300">
                            {formatCurrency(visibleMonthlyIncomeTotal)}
                          </td>
                          <td className="py-3 text-right text-rose-600 dark:text-rose-300">
                            {formatCurrency(visibleMonthlyExpenseTotal)}
                          </td>
                          <td className={`py-3 text-right ${visibleMonthlyNetTotal >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                            {formatCurrency(visibleMonthlyNetTotal)}
                          </td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                  )}
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
                  Месячный диапазон быстро выставляет границы, точные даты можно уточнить в периоде отчета.
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
                      Клик по легенде включает отбор, глаз исключает статью. Клик по строке таблицы открывает документы.
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {selectedBudgetPlanItemName ? (
                      <Button variant="outline" size="sm" onClick={() => setSelectedBudgetPlanItemKey(null)}>
                        Снять отбор
                      </Button>
                    ) : null}
                    {hiddenBudgetPlanItemCount > 0 ? (
                      <Button variant="outline" size="sm" onClick={() => setHiddenBudgetPlanItemKeys({})}>
                        Показать все
                      </Button>
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                    <div className="h-[380px] min-w-0" ref={budgetExpenseChartRef}>
                      {budgetPlanChartKeys.length === 0 ? (
                        <div className="flex h-full items-center justify-center rounded-[22px] border border-dashed border-border/70 text-sm text-muted-foreground">
                          Нет видимых статей для графика. Сними отбор или верни скрытые статьи.
                        </div>
                      ) : (
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
                      )}
                    </div>
                    <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold tracking-[-0.02em]">Легенда статей</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            Название — отбор. Глаз — исключить из отчета.
                          </div>
                        </div>
                        {selectedBudgetPlanItemName || hiddenBudgetPlanItemCount > 0 ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedBudgetPlanItemKey(null)
                              setHiddenBudgetPlanItemKeys({})
                            }}
                          >
                            Сбросить
                          </Button>
                        ) : null}
                      </div>
                      <div className="mt-4 max-h-[300px] space-y-2 overflow-y-auto pr-1">
                        {budgetPlanLegendItems.map((item) => {
                          const isSelected = activeSelectedBudgetPlanItemKey === item.key
                          const isHidden = hiddenBudgetPlanItemKeySet.has(item.key)
                          return (
                            <div
                              key={item.key}
                              className={`flex items-stretch gap-2 rounded-2xl border px-3 py-2 transition ${
                                isSelected
                                  ? "border-primary bg-primary/10"
                                  : isHidden
                                    ? "border-border/40 bg-muted/30 opacity-60"
                                    : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                              }`}
                            >
                              <button
                                type="button"
                                className="min-w-0 flex-1 text-left"
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
                                  <span className={`min-w-0 flex-1 truncate text-sm font-medium ${isHidden ? "line-through" : ""}`}>
                                    {item.name}
                                  </span>
                                  <span className="text-sm font-semibold">{formatCurrency(item.plannedAmount)}</span>
                                </span>
                                <span className="mt-1 block text-xs text-muted-foreground">
                                  {isHidden ? "Исключена" : `${item.share.toFixed(1)}% от плана`}
                                </span>
                              </button>
                              <button
                                type="button"
                                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background/80 text-muted-foreground transition hover:border-primary/60 hover:text-primary"
                                aria-label={isHidden ? "Вернуть статью в отчет" : "Исключить статью из отчета"}
                                title={isHidden ? "Вернуть статью" : "Исключить статью"}
                                onClick={() => {
                                  if (!isHidden && isSelected) {
                                    setSelectedBudgetPlanItemKey(null)
                                  }
                                  toggleHiddenBudgetPlanItem(item.key)
                                }}
                              >
                                {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                              </button>
                            </div>
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
                  <div className="flex flex-wrap gap-2">
                    {selectedBudgetPlanItemName ? <Badge variant="secondary">Фильтр по статье</Badge> : null}
                    {hiddenBudgetPlanItemCount > 0 ? (
                      <Badge variant="secondary">Исключено: {hiddenBudgetPlanItemCount}</Badge>
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent className="space-y-6">
                  {visibleBudgetPlanningGroups.length === 0 ? (
                    <div className="rounded-[18px] border border-border/70 bg-background/70 p-4 text-sm text-muted-foreground">
                      Нет видимых строк. Сними отбор или верни скрытые статьи.
                    </div>
                  ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-[13px] sm:text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs text-muted-foreground">
                          <th className="pb-3">Месяц / статья</th>
                          <th className="pb-3 text-right">План</th>
                          <th className="pb-3 text-right">Факт</th>
                          <th className="pb-3 text-right">Остаток</th>
                          <th className="pb-3 text-right">Исполнение</th>
                        </tr>
                      </thead>
                      {visibleBudgetPlanningGroups.map((group) => {
                        const isCollapsed = collapsedBudgetPlanGroups[group.key] ?? true

                        return (
                          <tbody key={group.key}>
                            <tr
                              className="cursor-pointer border-b border-border bg-muted/40 font-semibold transition-colors hover:bg-muted/60"
                              onClick={() =>
                                setCollapsedBudgetPlanGroups((current) => ({
                                  ...current,
                                  [group.key]: !(current[group.key] ?? true),
                                }))
                              }
                            >
                              <td className="py-2.5">
                                <span className="flex items-center gap-2 text-sm font-semibold">
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
                              <td className="py-2.5 text-right">{formatCurrency(group.plannedAmount)}</td>
                              <td className="py-2.5 text-right text-rose-600 dark:text-rose-300">
                                {formatCurrency(group.actualAmount)}
                              </td>
                              <td className={`py-2.5 text-right ${group.balance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                {formatCurrency(group.balance)}
                              </td>
                              <td className="py-2.5 text-right">{Math.round(group.executionPercent)}%</td>
                            </tr>
                            {isCollapsed ? null : group.rows.map((row) => (
                              <tr
                                key={row.key}
                                className="cursor-pointer border-b border-border/60 transition-colors hover:bg-muted/40"
                                onClick={() => openBudgetPlanBreakdown(row)}
                              >
                                <td className="py-2.5 pl-5 font-medium">{row.itemName}</td>
                                <td className="py-2.5 text-right">{formatCurrency(row.plannedAmount)}</td>
                                <td className="py-2.5 text-right text-rose-600 dark:text-rose-300">
                                  {formatCurrency(row.actualAmount)}
                                </td>
                                <td className={`py-2.5 text-right ${row.balance >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                  {formatCurrency(row.balance)}
                                </td>
                                <td className="py-2.5 text-right">{Math.round(row.executionPercent)}%</td>
                              </tr>
                            ))}
                          </tbody>
                        )
                      })}
                      <tfoot>
                        <tr className="border-t bg-muted/40 text-sm font-semibold">
                          <td className="py-3">Итого по отчету</td>
                          <td className="py-3 text-right">{formatCurrency(visibleBudgetPlannedTotal)}</td>
                          <td className="py-3 text-right text-rose-600 dark:text-rose-300">
                            {formatCurrency(visibleBudgetActualTotal)}
                          </td>
                          <td className={`py-3 text-right ${visibleBudgetBalanceTotal >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                            {formatCurrency(visibleBudgetBalanceTotal)}
                          </td>
                          <td className="py-3 text-right">{Math.round(visibleBudgetExecutionPercent)}%</td>
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>
      </Tabs>

      <Dialog.Root
        open={Boolean(documentBreakdown)}
        onOpenChange={(open) => {
          if (!open) {
            setDocumentBreakdown(null)
          }
        }}
      >
        {documentBreakdown ? (
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-sm" />
            <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(calc(100vw-18px),980px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[28px] border border-border/70 bg-background shadow-[0_35px_120px_-45px_rgba(15,23,42,0.85)]">
              <div className="flex items-start justify-between gap-4 border-b border-border/60 px-5 py-4 sm:px-6">
                <div className="min-w-0">
                  <Dialog.Title className="truncate text-xl font-semibold tracking-[-0.03em] text-foreground">
                    {documentBreakdown.title}
                  </Dialog.Title>
                  <Dialog.Description className="mt-1 text-sm leading-5 text-muted-foreground">
                    {documentBreakdown.description}
                  </Dialog.Description>
                </div>
                <Dialog.Close asChild>
                  <Button variant="ghost" size="icon" className="shrink-0 rounded-2xl" aria-label="Закрыть">
                    <X className="h-4 w-4" />
                  </Button>
                </Dialog.Close>
              </div>

              <div className="max-h-[calc(92vh-92px)] overflow-y-auto px-4 py-4 sm:px-6">
                {documentBreakdown.rows.length === 0 ? (
                  <div className="rounded-[18px] border border-border/70 bg-background/70 p-4 text-sm text-muted-foreground">
                    Документы для этой строки не найдены.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-[13px] sm:text-sm">
                      <thead>
                        {documentBreakdown.mode === "cashflow" ? (
                          <tr className="border-b text-left text-xs text-muted-foreground">
                            <th className="pb-3">Дата</th>
                            <th className="pb-3">Документ</th>
                            <th className="pb-3">Кошелек</th>
                            <th className="pb-3 text-right">Приход</th>
                            <th className="pb-3 text-right">Расход</th>
                            <th className="pb-3 text-right">Итог</th>
                            <th className="pb-3 text-right">Действие</th>
                          </tr>
                        ) : (
                          <tr className="border-b text-left text-xs text-muted-foreground">
                            <th className="pb-3">Дата</th>
                            <th className="pb-3">Вид</th>
                            <th className="pb-3">Документ</th>
                            <th className="pb-3 text-right">Сумма</th>
                            <th className="pb-3 text-right">Действие</th>
                          </tr>
                        )}
                      </thead>
                      <tbody>
                        {documentBreakdown.rows.map((row) =>
                          documentBreakdown.mode === "cashflow" ? (
                            <tr key={row.key} className="border-b border-border/60">
                              <td className="py-2.5 whitespace-nowrap">{formatDate(row.period)}</td>
                              <td className="py-2.5">
                                <div className="font-medium">{row.documentTypeLabel}</div>
                                <div className="text-xs text-muted-foreground">{row.itemName}</div>
                              </td>
                              <td className="py-2.5 text-muted-foreground">{row.walletName || "—"}</td>
                              <td className="py-2.5 text-right text-emerald-600 dark:text-emerald-300">
                                {(row.income || 0) > 0 ? formatCurrency(row.income || 0) : "—"}
                              </td>
                              <td className="py-2.5 text-right text-rose-600 dark:text-rose-300">
                                {(row.expense || 0) > 0 ? formatCurrency(row.expense || 0) : "—"}
                              </td>
                              <td className={`py-2.5 text-right ${(row.net || 0) >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                                {formatCurrency(row.net || 0)}
                              </td>
                              <td className="py-2.5 text-right">
                                {row.documentId && row.documentKind ? (
                                  <Button variant="outline" size="sm" onClick={() => openDocument(row.documentId, row.documentKind)}>
                                    Открыть
                                  </Button>
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </td>
                            </tr>
                          ) : (
                            <tr key={row.key} className="border-b border-border/60">
                              <td className="py-2.5 whitespace-nowrap">{formatDate(row.period)}</td>
                              <td className="py-2.5">
                                <Badge variant={row.entryTypeLabel === "План" ? "outline" : "secondary"}>
                                  {row.entryTypeLabel}
                                </Badge>
                              </td>
                              <td className="py-2.5">
                                <div className="font-medium">{row.documentTypeLabel}</div>
                                <div className="text-xs text-muted-foreground">{row.itemName}</div>
                              </td>
                              <td className="py-2.5 text-right font-medium">{formatCurrency(row.amount || 0)}</td>
                              <td className="py-2.5 text-right">
                                {row.documentId && row.documentKind ? (
                                  <Button variant="outline" size="sm" onClick={() => openDocument(row.documentId, row.documentKind)}>
                                    Открыть
                                  </Button>
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </td>
                            </tr>
                          )
                        )}
                      </tbody>
                      <tfoot>
                        {documentBreakdown.mode === "cashflow" ? (
                          <tr className="border-t bg-muted/40 text-sm font-semibold">
                            <td className="py-3" colSpan={3}>
                              Итого
                            </td>
                            <td className="py-3 text-right text-emerald-600 dark:text-emerald-300">
                              {formatCurrency(documentBreakdown.totals.income || 0)}
                            </td>
                            <td className="py-3 text-right text-rose-600 dark:text-rose-300">
                              {formatCurrency(documentBreakdown.totals.expense || 0)}
                            </td>
                            <td className={`py-3 text-right ${(documentBreakdown.totals.net || 0) >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(documentBreakdown.totals.net || 0)}
                            </td>
                            <td />
                          </tr>
                        ) : (
                          <tr className="border-t bg-muted/40 text-sm font-semibold">
                            <td className="py-3" colSpan={3}>
                              План {formatCurrency(documentBreakdown.totals.plan || 0)} · факт {formatCurrency(documentBreakdown.totals.actual || 0)}
                            </td>
                            <td className={`py-3 text-right ${(documentBreakdown.totals.balance || 0) >= 0 ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"}`}>
                              {formatCurrency(documentBreakdown.totals.balance || 0)}
                            </td>
                            <td />
                          </tr>
                        )}
                      </tfoot>
                    </table>
                  </div>
                )}
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        ) : null}
      </Dialog.Root>

      <DocumentEditDialog
        document={editingDocument}
        onOpenChange={(open) => {
          if (!open) {
            setEditingDocument(null)
          }
        }}
        onSaved={() => reportsQuery.refetch()}
      />
    </div>
  )
}
