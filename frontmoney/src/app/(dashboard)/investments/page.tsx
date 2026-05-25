"use client"

import * as Dialog from "@radix-ui/react-dialog"
import { ResponsiveLine } from "@nivo/line"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BarChart3, ChevronDown, Coins, Landmark, LineChart, PencilLine, Plus, RefreshCw, Target, Trash2, TrendingUp, X } from "lucide-react"
import Link from "next/link"
import { useEffect, useMemo, useState, type FormEvent } from "react"

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
import { formatDate } from "@/lib/formatters"
import {
  readInvestmentDisplayCurrency,
  readSelectedInvestmentPortfolioId,
  writeInvestmentDisplayCurrency,
  writeSelectedInvestmentPortfolioId,
} from "@/lib/investment-preferences"
import {
  InvestmentService,
  type FxRateSnapshot,
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
  type InvestmentTargetAllocation,
  type InvestmentTargetAllocationPayload,
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

const instrumentTypeLabels: Record<InstrumentType, string> = {
  crypto: "Крипто",
  stock: "Акция",
  bond: "Облигация",
}

const rebalanceActionLabels: Record<string, string> = {
  buy: "Докупка",
  sell: "Сократить",
  hold: "В норме",
}

type DisplayCurrency = "RUB" | "USD" | "EUR"
type InvestmentSectionId = "rebalance" | "positions" | "operations" | "directories"

const displayCurrencies: DisplayCurrency[] = ["USD", "EUR", "RUB"]
const currencyOptions = displayCurrencies
const instrumentChartColors = ["#0f8b8d", "#f97316", "#8b5cf6", "#10b981", "#ef4444", "#3b82f6", "#f59e0b", "#ec4899"]

type InvestmentDialogState =
  | { type: "portfolio"; mode: "create" | "edit"; item?: InvestmentPortfolio }
  | { type: "instrument"; mode: "create" | "edit"; item?: Instrument }
  | { type: "price"; mode: "create"; item?: Instrument }
  | { type: "account"; mode: "create" | "edit"; item?: InvestmentAccount }
  | { type: "operation"; mode: "create" | "edit"; item?: InvestmentOperation }
  | { type: "target-allocation"; mode: "create" | "edit"; item?: InvestmentTargetAllocation }
  | null

const INVESTMENT_QUERY_KEYS = [
  ["investment-overview"],
  ["investment-performance"],
  ["investment-portfolios"],
  ["investment-instruments"],
  ["investment-accounts"],
  ["investment-operations"],
  ["investment-performance-operations"],
  ["investment-target-allocations"],
  ["investment-rebalance"],
]
const showInlinePerformanceReports = false

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

function formatCalculatedAmount(value: number) {
  return Number(value.toFixed(8)).toString()
}

function formatCalculatedPrice(value: number) {
  return Number(value.toFixed(8)).toString()
}

function isUsdCurrency(currency?: string | null) {
  return (currency || "USD").trim().toUpperCase() === "USD"
}

function isOperationAmountEditedManually(operation?: InvestmentOperation) {
  if (!operation || (operation.operation_type !== "buy" && operation.operation_type !== "sell")) {
    return false
  }
  if (operation.price_usd === undefined || operation.price_usd === null) {
    return Boolean(operation.amount_usd)
  }
  const calculatedAmount = operation.quantity * operation.price_usd
  return Math.abs(operation.amount_usd - calculatedAmount) > 0.00000001
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

function yearDateRange() {
  const year = new Date().getFullYear()
  return {
    dateFrom: `${year}-01-01`,
    dateTo: `${year}-12-31`,
  }
}

function formatShortPerformanceLabel(value: string, groupBy: "day" | "month") {
  if (!value) {
    return ""
  }
  if (groupBy === "month") {
    const [year, month] = value.split("-")
    const date = new Date(Number(year), Number(month) - 1, 1)
    return new Intl.DateTimeFormat("ru-RU", { month: "short" }).format(date).replace(".", "")
  }
  const date = new Date(value)
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit" }).format(date)
}

function getDisplayRate(currency: DisplayCurrency, fxRates: FxRateSnapshot[]) {
  if (currency === "USD") {
    return 1
  }
  return fxRates.find((rate) => rate.base_currency === "USD" && rate.quote_currency === currency)?.rate ?? null
}

function convertUsdAmount(amount: number | null | undefined, currency: DisplayCurrency, fxRates: FxRateSnapshot[]) {
  if (amount === null || amount === undefined) {
    return null
  }
  const rate = getDisplayRate(currency, fxRates)
  if (!rate) {
    return null
  }
  return currency === "USD" ? amount : amount * rate
}

function formatCurrencyValue(amount: number, currency: DisplayCurrency) {
  const digits = currency === "RUB" ? 0 : 2
  return `${new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount)} ${currency}`
}

function formatCompactChartValue(amount: number) {
  return new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(amount)
}

function getChartTickValues(data: Array<{ x: string; y: number }>) {
  if (data.length <= 8) {
    return data.map((point) => point.x)
  }
  const step = Math.ceil(data.length / 7)
  return data
    .filter((_, index) => index === 0 || index === data.length - 1 || index % step === 0)
    .map((point) => point.x)
}

function getChartYDomain(data: Array<{ x: string; y: number }>, includeZero = false) {
  const values = data.map((point) => point.y).filter((value) => Number.isFinite(value))
  if (values.length === 0) {
    return { min: 0, max: 1 }
  }
  const minValue = Math.min(...values, includeZero ? 0 : values[0])
  const maxValue = Math.max(...values, includeZero ? 0 : values[0])
  const span = maxValue - minValue
  const padding = span === 0 ? Math.max(Math.abs(maxValue) * 0.1, 1) : span * 0.12
  return {
    min: minValue - padding,
    max: maxValue + padding,
  }
}

type OperationChartMarker = {
  key: string
  x: string
  y: number
  type: "buy" | "sell"
  count: number
  amountUsd: number
  amountDisplay: number | null
  quantity: number
  tickers: string[]
}

function getOperationMarkerLabel(operation: InvestmentOperation, groupBy: "day" | "month") {
  return formatShortPerformanceLabel(operation.date, groupBy)
}

function buildOperationMarkers(
  points: Array<{ x: string; y: number }>,
  operations: InvestmentOperation[],
  groupBy: "day" | "month",
  options?: { instrumentId?: string },
) {
  const pointByLabel = new Map(points.map((point) => [point.x, point]))
  const grouped = new Map<string, OperationChartMarker>()

  operations
    .filter((operation) => operation.posted && !operation.deleted)
    .filter((operation) => operation.operation_type === "buy" || operation.operation_type === "sell")
    .filter((operation) => !options?.instrumentId || operation.instrument === options.instrumentId)
    .forEach((operation) => {
      const x = getOperationMarkerLabel(operation, groupBy)
      const point = pointByLabel.get(x)
      if (!point) {
        return
      }
      const type = operation.operation_type as "buy" | "sell"
      const key = `${x}:${type}:${options?.instrumentId ?? "portfolio"}`
      const marker = grouped.get(key) ?? {
        key,
        x,
        y: point.y,
        type,
        count: 0,
        amountUsd: 0,
        amountDisplay: 0,
        quantity: 0,
        tickers: [],
      }
      marker.count += 1
      marker.amountUsd += operation.amount_usd
      if (operation.amount_display === null || operation.amount_display === undefined) {
        marker.amountDisplay = null
      } else if (marker.amountDisplay !== null) {
        marker.amountDisplay += operation.amount_display
      }
      marker.quantity += operation.quantity
      if (operation.instrument_ticker && !marker.tickers.includes(operation.instrument_ticker)) {
        marker.tickers.push(operation.instrument_ticker)
      }
      grouped.set(key, marker)
    })

  return Array.from(grouped.values())
}

function formatMoneyInCurrency(amount: number | null | undefined, currency: DisplayCurrency, fxRates: FxRateSnapshot[]) {
  const converted = convertUsdAmount(amount, currency, fxRates)
  if (converted === null) {
    if (amount === null || amount === undefined) {
      return "нет цены"
    }
    return "нет курса"
  }
  return formatCurrencyValue(converted, currency)
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

function escapeCsvValue(value: string | number | null | undefined) {
  const text = value === null || value === undefined ? "" : String(value)
  return `"${text.replace(/"/g, '""')}"`
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-xs uppercase tracking-[0.12em] text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function CurrencySelect({ value, onChange }: { value: string; onChange: (value: DisplayCurrency) => void }) {
  return (
    <Select value={value || "USD"} onValueChange={(nextValue) => onChange(nextValue as DisplayCurrency)}>
      <SelectTrigger>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {currencyOptions.map((currency) => (
          <SelectItem key={currency} value={currency}>
            {currency}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function CollapsibleSection({
  title,
  description,
  actions,
  collapsed,
  onToggle,
  children,
  contentClassName,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  collapsed: boolean
  onToggle: () => void
  children: React.ReactNode
  contentClassName?: string
}) {
  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={onToggle}
            aria-label={collapsed ? `Показать ${title}` : `Скрыть ${title}`}
          >
            <ChevronDown className={collapsed ? "h-4 w-4 -rotate-90 transition-transform" : "h-4 w-4 rotate-0 transition-transform"} />
          </Button>
        </div>
      </CardHeader>
      {collapsed ? null : <CardContent className={contentClassName}>{children}</CardContent>}
    </Card>
  )
}

export default function InvestmentsPage() {
  const queryClient = useQueryClient()
  const [dialog, setDialog] = useState<InvestmentDialogState>(null)
  const [dialogError, setDialogError] = useState("")
  const [performanceGroupBy, setPerformanceGroupBy] = useState<"day" | "month">("month")
  const [hiddenPlInstruments, setHiddenPlInstruments] = useState<string[]>([])
  const [collapsedSections, setCollapsedSections] = useState<InvestmentSectionId[]>([])
  const [operationDateFrom, setOperationDateFrom] = useState("")
  const [operationDateTo, setOperationDateTo] = useState("")
  const [operationInstrument, setOperationInstrument] = useState("all")
  const [operationAccount, setOperationAccount] = useState("all")
  const [displayCurrency, setDisplayCurrency] = useState<DisplayCurrency>(() => readInvestmentDisplayCurrency())
  const [selectedPortfolioId, setSelectedPortfolioId] = useState(() => readSelectedInvestmentPortfolioId())
  const performancePeriod = useMemo(() => yearDateRange(), [])
  const isSectionCollapsed = (section: InvestmentSectionId) => collapsedSections.includes(section)
  const toggleInvestmentSection = (section: InvestmentSectionId) => {
    setCollapsedSections((current) =>
      current.includes(section) ? current.filter((item) => item !== section) : [...current, section],
    )
  }

  const portfoliosQuery = useQuery({
    queryKey: ["investment-portfolios"],
    queryFn: InvestmentService.getPortfolios,
  })
  const portfolios = portfoliosQuery.data ?? []
  const activePortfolioId =
    selectedPortfolioId ||
    portfolios.find((portfolio) => portfolio.is_default)?.id ||
    portfolios[0]?.id ||
    ""
  const overviewQuery = useQuery({
    queryKey: ["investment-overview", activePortfolioId, displayCurrency],
    queryFn: () =>
      InvestmentService.getOverview({
        portfolio: activePortfolioId || undefined,
        display_currency: displayCurrency,
      }),
    enabled: !portfoliosQuery.isLoading,
  })
  const performanceQuery = useQuery({
    queryKey: ["investment-performance", activePortfolioId, performanceGroupBy, performancePeriod.dateFrom, performancePeriod.dateTo, displayCurrency],
    queryFn: () =>
      InvestmentService.getPortfolioPerformance(activePortfolioId, {
        date_from: performancePeriod.dateFrom,
        date_to: performancePeriod.dateTo,
        group_by: performanceGroupBy,
        display_currency: displayCurrency,
        scope: "all",
      }),
    enabled: Boolean(activePortfolioId && showInlinePerformanceReports),
  })
  const instrumentsQuery = useQuery({
    queryKey: ["investment-instruments"],
    queryFn: InvestmentService.getInstruments,
  })
  const accountsQuery = useQuery({
    queryKey: ["investment-accounts"],
    queryFn: InvestmentService.getAccounts,
  })
  const fxRatesQuery = useQuery({
    queryKey: ["investment-fx-rates", displayCurrency],
    queryFn: () => InvestmentService.getFxRates({ base_currency: "USD", quote_currency: displayCurrency }),
    enabled: displayCurrency !== "USD",
  })
  const performanceOperationsQuery = useQuery({
    queryKey: ["investment-performance-operations", activePortfolioId, performancePeriod.dateFrom, performancePeriod.dateTo, displayCurrency],
    queryFn: () =>
      InvestmentService.getOperations({
        portfolio: activePortfolioId,
        date_from: performancePeriod.dateFrom,
        date_to: performancePeriod.dateTo,
        display_currency: displayCurrency,
      }),
    enabled: Boolean(activePortfolioId && showInlinePerformanceReports),
  })
  const targetAllocationsQuery = useQuery({
    queryKey: ["investment-target-allocations", activePortfolioId],
    queryFn: () => InvestmentService.getTargetAllocations({ portfolio: activePortfolioId }),
    enabled: Boolean(activePortfolioId),
  })
  const rebalanceQuery = useQuery({
    queryKey: ["investment-rebalance", activePortfolioId],
    queryFn: () => InvestmentService.getPortfolioRebalance(activePortfolioId),
    enabled: Boolean(activePortfolioId),
  })
  const operationsQuery = useQuery({
    queryKey: ["investment-operations", activePortfolioId, operationDateFrom, operationDateTo, operationInstrument, operationAccount, displayCurrency],
    queryFn: () =>
      InvestmentService.getOperations({
        portfolio: activePortfolioId,
        date_from: operationDateFrom || undefined,
        date_to: operationDateTo || undefined,
        instrument: operationInstrument === "all" ? undefined : operationInstrument,
        account: operationAccount === "all" ? undefined : operationAccount,
        display_currency: displayCurrency,
      }),
    enabled: Boolean(activePortfolioId),
  })

  useEffect(() => {
    if (portfoliosQuery.isLoading || portfolios.length === 0) {
      return
    }
    if (selectedPortfolioId && portfolios.some((portfolio) => portfolio.id === selectedPortfolioId)) {
      return
    }
    setSelectedPortfolioId(portfolios.find((portfolio) => portfolio.is_default)?.id ?? portfolios[0]?.id ?? "")
  }, [portfolios, portfoliosQuery.isLoading, selectedPortfolioId])

  useEffect(() => {
    writeInvestmentDisplayCurrency(displayCurrency)
  }, [displayCurrency])

  useEffect(() => {
    writeSelectedInvestmentPortfolioId(selectedPortfolioId)
  }, [selectedPortfolioId])

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
    onSuccess: (portfolio) => {
      setSelectedPortfolioId(portfolio.id)
      handleSaved()
    },
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

  const saveTargetAllocationMutation = useMutation({
    mutationFn: ({ id, payload }: { id?: string; payload: InvestmentTargetAllocationPayload | Partial<InvestmentTargetAllocationPayload> }) =>
      id
        ? InvestmentService.updateTargetAllocation(id, payload)
        : InvestmentService.createTargetAllocation(payload as InvestmentTargetAllocationPayload),
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
  const instruments = instrumentsQuery.data ?? []
  const accounts = accountsQuery.data ?? []
  const operations = operationsQuery.data ?? []
  const activeInstruments = instruments.filter((instrument) => instrument.is_active)
  const currentPortfolio = overview.portfolio ?? portfolios.find((portfolio) => portfolio.id === activePortfolioId) ?? null
  const currentPortfolioAccounts = currentPortfolio ? accounts.filter((account) => account.portfolio === currentPortfolio.id) : []
  const visibleAccounts = currentPortfolioAccounts.filter((account) => !account.hidden)
  const canCreateOperation = Boolean(currentPortfolio && activeInstruments.length > 0 && currentPortfolioAccounts.length > 0)
  const fxRates = fxRatesQuery.data ?? []
  const money = (amount: number | null | undefined) => formatMoneyInCurrency(amount, displayCurrency, fxRates)
  const displayMoney = (amount: number | null | undefined, empty = "нет курса") =>
    amount === null || amount === undefined ? empty : formatCurrencyValue(amount, displayCurrency)
  const targetAllocations = targetAllocationsQuery.data ?? []
  const rebalanceStatus = rebalanceQuery.data
  const targetAllocationByInstrument = new Map(targetAllocations.map((allocation) => [allocation.instrument, allocation]))
  const targetAllocationSum = targetAllocations.reduce((sum, allocation) => sum + allocation.target_percent, 0)
  const offTargetPositions = rebalanceStatus?.positions.filter(
    (position) => position.target_allocation_percent !== null && position.target_allocation_percent !== undefined && position.is_within_tolerance === false,
  ) ?? []
  const rebalancePositions = rebalanceStatus?.positions.filter(
    (position) =>
      position.target_allocation_percent !== null ||
      (position.current_value_usd !== null && position.current_value_usd !== undefined && position.current_value_usd > 0),
  ) ?? []
  const performance = performanceQuery.data
  const performanceOperations = performanceOperationsQuery.data ?? []
  const performancePoints = performance?.points ?? []
  const valueLineData = performancePoints.map((point) => ({
    x: point.label === "Старт" ? "Старт" : formatShortPerformanceLabel(point.date, performanceGroupBy),
    y: point.current_value_display ?? point.current_value_usd,
  }))
  const plLineData = performancePoints.map((point) => ({
    x: point.label === "Старт" ? "Старт" : formatShortPerformanceLabel(point.date, performanceGroupBy),
    y: point.total_pl_display ?? point.total_pl_usd,
  }))
  const valueChartTicks = getChartTickValues(valueLineData)
  const plChartTicks = getChartTickValues(plLineData)
  const valueChartDomain = getChartYDomain(valueLineData)
  const plChartDomain = getChartYDomain(plLineData, true)
  const performancePointSize = performancePoints.length > 60 ? 0 : 7
  const valueOperationMarkers = buildOperationMarkers(valueLineData, performanceOperations, performanceGroupBy)
  const plOperationMarkers = buildOperationMarkers(plLineData, performanceOperations, performanceGroupBy)
  const instrumentPlSeries = performance?.instrument_series.filter((series) => series.points.length > 0) ?? []
  const instrumentPlColorByTicker = new Map(
    instrumentPlSeries.map((series, index) => [
      series.instrument_ticker,
      instrumentChartColors[index % instrumentChartColors.length],
    ]),
  )
  const activeInstrumentPlSeries = instrumentPlSeries.filter((series) => !hiddenPlInstruments.includes(series.instrument_id))
  const instrumentPlLineData = activeInstrumentPlSeries.map((series) => ({
    id: series.instrument_ticker,
    data: series.points.map((point) => ({
      x: point.label === "Старт" ? "Старт" : formatShortPerformanceLabel(point.date, performanceGroupBy),
      y: point.total_pl_display ?? point.total_pl_usd,
      realized: point.realized_pl_display ?? point.realized_pl_usd,
      unrealized: point.unrealized_pl_display ?? point.unrealized_pl_usd,
      total: point.total_pl_display ?? point.total_pl_usd,
    })),
  }))
  const instrumentPlTicks = getChartTickValues(instrumentPlLineData[0]?.data ?? [])
  const instrumentPlDomain = getChartYDomain(instrumentPlLineData.flatMap((series) => series.data), true)
  const instrumentPlPointSize = performancePoints.length > 60 ? 0 : 6
  const instrumentPlOperationMarkers = activeInstrumentPlSeries.flatMap((series) =>
    buildOperationMarkers(
      series.points.map((point) => ({
        x: point.label === "Старт" ? "Старт" : formatShortPerformanceLabel(point.date, performanceGroupBy),
        y: point.total_pl_display ?? point.total_pl_usd,
      })),
      performanceOperations,
      performanceGroupBy,
      { instrumentId: series.instrument_id },
    ),
  )
  const renderOperationMarkers = (markers: OperationChartMarker[]) => ({ xScale, yScale, innerHeight }: any) => (
    <g pointerEvents="none">
      {markers.map((marker, index) => {
        const rawX = xScale(marker.x)
        const rawY = yScale(marker.y)
        const x = Number(rawX)
        const baseY = Number(rawY)
        if (!Number.isFinite(x) || !Number.isFinite(baseY)) {
          return null
        }
        const isBuy = marker.type === "buy"
        const color = isBuy ? "#10b981" : "#ef4444"
        const yOffset = isBuy ? -16 : 16
        const y = Math.min(Math.max(baseY + yOffset, 10), Math.max(Number(innerHeight) - 10, 10))
        const title = [
          isBuy ? "Покупка" : "Продажа",
          marker.x,
          marker.tickers.join(", "),
          `${marker.count} сделк.`,
          marker.amountDisplay === null ? "нет курса" : formatCurrencyValue(marker.amountDisplay, displayCurrency),
        ].filter(Boolean).join(" · ")
        return (
          <g key={`${marker.key}-${index}`} transform={`translate(${x}, ${y})`}>
            <title>{title}</title>
            <line y1={isBuy ? 8 : -8} y2={isBuy ? 18 : -18} stroke={color} strokeWidth={1.5} strokeDasharray="3 3" />
            <circle r={8} fill={color} stroke="hsl(var(--background))" strokeWidth={2} />
            <text
              dy="0.36em"
              textAnchor="middle"
              fill="#fff"
              fontSize={11}
              fontWeight={800}
            >
              {isBuy ? "+" : "−"}
            </text>
          </g>
        )
      })}
    </g>
  )
  const operationTotals = operations.reduce(
    (totals, operation) => {
      if (operation.operation_type === "buy") {
        if (operation.amount_display === null || operation.amount_display === undefined) {
          totals.buyComplete = false
        } else {
          totals.buy += operation.amount_display
        }
      }
      if (operation.operation_type === "sell") {
        if (operation.amount_display === null || operation.amount_display === undefined) {
          totals.sellComplete = false
        } else {
          totals.sell += operation.amount_display
        }
      }
      if (operation.fee_display === null || operation.fee_display === undefined) {
        totals.feeComplete = false
      } else {
        totals.fee += operation.fee_display
      }
      return totals
    },
    { buy: 0, buyComplete: true, sell: 0, sellComplete: true, fee: 0, feeComplete: true },
  )
  const exportOperationsCsv = () => {
    const header = ["Дата", "Номер", "Тип", "Инструмент", "Счет", "Количество", "Сумма USD", "Комиссия USD", "Комментарий"]
    const rows = operations.map((operation) => [
      formatDate(operation.date),
      operation.number ?? "",
      operationLabels[operation.operation_type] ?? operation.operation_type,
      operation.instrument_ticker ?? "",
      operation.account_name ?? "",
      operation.quantity,
      operation.amount_usd,
      operation.fee_usd,
      operation.comment ?? "",
    ])
    const csv = [header, ...rows].map((row) => row.map(escapeCsvValue).join(";")).join("\n")
    const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = "investment-operations.csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  const openDialog = (nextDialog: InvestmentDialogState) => {
    setDialogError("")
    setDialog(nextDialog)
  }

  const togglePlInstrument = (instrumentId: string) => {
    setHiddenPlInstruments((current) =>
      current.includes(instrumentId)
        ? current.filter((id) => id !== instrumentId)
        : [...current, instrumentId],
    )
  }

  const handleDelete = async (kind: "portfolio" | "instrument" | "account" | "operation" | "target-allocation", id: string, label: string) => {
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
      if (kind === "target-allocation") {
        await InvestmentService.deleteTargetAllocation(id)
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
            <Button variant="outline" asChild>
              <Link href="/investments/reports">
                <LineChart className="mr-2 h-4 w-4" />
                Отчеты
              </Link>
            </Button>
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

      <div className="flex flex-wrap items-center gap-2 rounded-[22px] border border-border/70 bg-card/70 px-4 py-3">
        {portfolios.length > 0 ? (
          <>
            <span className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Портфель</span>
            <Select
              value={activePortfolioId}
              onValueChange={(value) => {
                setSelectedPortfolioId(value)
                setOperationAccount("all")
              }}
            >
              <SelectTrigger className="h-10 w-[220px] rounded-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {portfolios.map((portfolio) => (
                  <SelectItem key={portfolio.id} value={portfolio.id}>
                    {portfolio.name}{portfolio.is_default ? " · по умолчанию" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        ) : null}
        <span className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Валюта отображения</span>
        <div className="flex rounded-full border border-border/70 bg-muted/40 p-1">
          {displayCurrencies.map((currency) => (
            <Button
              key={currency}
              type="button"
              size="sm"
              variant={displayCurrency === currency ? "default" : "ghost"}
              className="rounded-full"
              onClick={() => setDisplayCurrency(currency)}
            >
              {currency}
            </Button>
          ))}
        </div>
        {displayCurrency !== "USD" ? (
          <span className="text-sm text-muted-foreground">
            {fxRatesQuery.isLoading
              ? "Загружаем курс..."
              : getDisplayRate(displayCurrency, fxRates)
                ? `1 USD = ${formatCurrencyValue(getDisplayRate(displayCurrency, fxRates) ?? 0, displayCurrency)}`
                : "Курс не найден, обнови FX snapshots"}
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">Базовая учетная валюта: USD.</span>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Текущая стоимость" value={displayMoney(overview.current_value_display, overview.valuation_complete ? "нет курса" : "нет цены")} hint={overview.valuation_complete ? "По последним ценам" : "Есть позиции без цены"} icon={Coins} variant="compact" />
        <StatCard label="Себестоимость" value={displayMoney(overview.cost_basis_display)} hint="Остаток позиций, по курсам дат покупки" icon={Landmark} variant="compact" />
        <StatCard label="Total P/L" value={displayMoney(overview.total_pl_display)} hint={`Доходность: ${formatPercent(overview.return_percent)}`} icon={LineChart} tone={(overview.total_pl_display ?? overview.total_pl_usd) < 0 ? "danger" : "positive"} variant="compact" />
        <StatCard label="Unrealized P/L" value={displayMoney(overview.unrealized_pl_display)} hint={`Realized: ${displayMoney(overview.realized_pl_display)}`} icon={BarChart3} tone={(overview.unrealized_pl_display ?? overview.unrealized_pl_usd) < 0 ? "danger" : "positive"} variant="compact" />
      </div>

      {showInlinePerformanceReports && currentPortfolio ? (
        <Card>
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>Динамика портфеля</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Текущий год. Начальная точка учитывает операции до начала периода.
              </p>
            </div>
            <div className="flex rounded-full border border-border/70 bg-muted/40 p-1">
              <Button
                type="button"
                size="sm"
                variant={performanceGroupBy === "day" ? "default" : "ghost"}
                className="rounded-full"
                onClick={() => setPerformanceGroupBy("day")}
              >
                По дням
              </Button>
              <Button
                type="button"
                size="sm"
                variant={performanceGroupBy === "month" ? "default" : "ghost"}
                className="rounded-full"
                onClick={() => setPerformanceGroupBy("month")}
              >
                По месяцам
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {performanceQuery.isLoading ? (
              <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">Загружаем графики...</div>
            ) : performanceQuery.isError || !performance ? (
              <EmptyState
                icon={LineChart}
                title="График пока недоступен"
                description="Не удалось получить performance API. Остальные данные портфеля доступны."
                action={<Button variant="outline" onClick={() => void performanceQuery.refetch()}>Повторить</Button>}
              />
            ) : performance.points.length === 0 ? (
              <EmptyState
                icon={LineChart}
                title="Нет точек графика"
                description="За выбранный период нет данных для динамики."
              />
            ) : (
              <div className="grid gap-6 xl:grid-cols-2">
                <div className="min-w-0 rounded-[22px] border border-border/70 bg-background/70 p-4">
                  <div className="mb-3 text-sm font-semibold text-foreground">Стоимость</div>
                  <div className="h-[320px]">
                    <ResponsiveLine
                      data={[{ id: "Стоимость", data: valueLineData }]}
                      margin={{ top: 22, right: 18, bottom: 50, left: 64 }}
                      xScale={{ type: "point" }}
                      yScale={{ type: "linear", stacked: false, min: valueChartDomain.min, max: valueChartDomain.max }}
                      axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -25, tickValues: valueChartTicks }}
                      axisLeft={{ tickSize: 0, tickPadding: 8, format: (value) => formatCompactChartValue(Number(value)) }}
                      enableGridX={false}
                      curve="monotoneX"
                      pointSize={performancePointSize}
                      pointBorderWidth={2}
                      pointBorderColor={{ from: "serieColor" }}
                      enableArea={performancePoints.length <= 60}
                      areaOpacity={0.08}
                      colors={["hsl(var(--primary))"]}
                      useMesh
                      layers={["grid", "markers", "axes", "areas", "crosshair", "lines", "points", renderOperationMarkers(valueOperationMarkers), "mesh", "legends"]}
                      tooltip={({ point }) => (
                        <div className="rounded border bg-background px-2 py-1 text-xs">
                          {String(point.data.x)}: {formatCurrencyValue(Number(point.data.y), displayCurrency)}
                        </div>
                      )}
                    />
                  </div>
                </div>
                <div className="min-w-0 rounded-[22px] border border-border/70 bg-background/70 p-4">
                  <div className="mb-3 text-sm font-semibold text-foreground">Total P/L</div>
                  <div className="h-[320px]">
                    <ResponsiveLine
                      data={[{ id: "Total P/L", data: plLineData }]}
                      margin={{ top: 22, right: 18, bottom: 50, left: 64 }}
                      xScale={{ type: "point" }}
                      yScale={{ type: "linear", stacked: false, min: plChartDomain.min, max: plChartDomain.max }}
                      axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -25, tickValues: plChartTicks }}
                      axisLeft={{ tickSize: 0, tickPadding: 8, format: (value) => formatCompactChartValue(Number(value)) }}
                      enableGridX={false}
                      curve="monotoneX"
                      pointSize={performancePointSize}
                      pointBorderWidth={2}
                      pointBorderColor={{ from: "serieColor" }}
                      colors={[overview.total_pl_usd < 0 ? "#ef4444" : "#10b981"]}
                      useMesh
                      layers={["grid", "markers", "axes", "crosshair", "lines", "points", renderOperationMarkers(plOperationMarkers), "mesh", "legends"]}
                      tooltip={({ point }) => (
                        <div className="rounded border bg-background px-2 py-1 text-xs">
                          {String(point.data.x)}: {formatCurrencyValue(Number(point.data.y), displayCurrency)}
                        </div>
                      )}
                    />
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {showInlinePerformanceReports && currentPortfolio ? (
        <Card>
          <CardHeader className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>P/L по инструментам</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Сравнение Total P/L по активам. Клик по легенде скрывает или возвращает инструмент на график.
              </p>
            </div>
          </CardHeader>
          <CardContent>
            {performanceQuery.isLoading ? (
              <div className="flex h-[260px] items-center justify-center text-sm text-muted-foreground">Загружаем P/L по инструментам...</div>
            ) : performanceQuery.isError || !performance ? (
              <EmptyState
                icon={LineChart}
                title="P/L по инструментам недоступен"
                description="Не удалось получить данные performance API."
                action={<Button variant="outline" onClick={() => void performanceQuery.refetch()}>Повторить</Button>}
              />
            ) : instrumentPlSeries.length === 0 ? (
              <EmptyState
                icon={LineChart}
                title="Нет данных P/L по инструментам"
                description="Для выбранного периода нет точек с ценами инструментов."
              />
            ) : instrumentPlLineData.length === 0 ? (
              <EmptyState
                icon={LineChart}
                title="Все инструменты скрыты"
                description="Верни серии на график через кнопку ниже."
                action={<Button variant="outline" onClick={() => setHiddenPlInstruments([])}>Показать все</Button>}
              />
            ) : (
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
                <div className="min-w-0 rounded-[22px] border border-border/70 bg-background/70 p-4">
                  <div className="h-[340px]">
                    <ResponsiveLine
                      data={instrumentPlLineData}
                      margin={{ top: 22, right: 18, bottom: 50, left: 64 }}
                      xScale={{ type: "point" }}
                      yScale={{ type: "linear", stacked: false, min: instrumentPlDomain.min, max: instrumentPlDomain.max }}
                      axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -25, tickValues: instrumentPlTicks }}
                      axisLeft={{ tickSize: 0, tickPadding: 8, format: (value) => formatCompactChartValue(Number(value)) }}
                      enableGridX={false}
                      curve="monotoneX"
                      pointSize={instrumentPlPointSize}
                      pointBorderWidth={2}
                      pointBorderColor={{ from: "serieColor" }}
                      colors={(series) => instrumentPlColorByTicker.get(String(series.id)) ?? instrumentChartColors[0]}
                      useMesh
                      layers={["grid", "markers", "axes", "crosshair", "lines", "points", renderOperationMarkers(instrumentPlOperationMarkers), "mesh", "legends"]}
                      tooltip={({ point }) => {
                        const data = point.data as typeof point.data & {
                          realized?: number | null
                          unrealized?: number | null
                          total?: number | null
                        }
                        return (
                          <div className="rounded border bg-background px-2 py-1 text-xs shadow-sm">
                            <div className="font-semibold">{String(point.seriesId)} · {String(point.data.x)}</div>
                            <div>Total: {formatCurrencyValue(Number(data.total ?? point.data.y), displayCurrency)}</div>
                            <div>Realized: {formatCurrencyValue(Number(data.realized ?? 0), displayCurrency)}</div>
                            <div>Unrealized: {formatCurrencyValue(Number(data.unrealized ?? 0), displayCurrency)}</div>
                          </div>
                        )
                      }}
                    />
                  </div>
                </div>
                <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold text-foreground">Легенда</div>
                    <Button type="button" size="sm" variant="ghost" onClick={() => setHiddenPlInstruments([])}>
                      Все
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {instrumentPlSeries.map((series, index) => {
                      const isHidden = hiddenPlInstruments.includes(series.instrument_id)
                      const lastPoint = series.points[series.points.length - 1]
                      return (
                        <button
                          key={series.instrument_id}
                          type="button"
                          className={
                            isHidden
                              ? "flex w-full items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/30 px-3 py-2 text-left opacity-45"
                              : "flex w-full items-center justify-between gap-3 rounded-2xl border border-border/70 bg-muted/30 px-3 py-2 text-left hover:border-primary/60"
                          }
                          onClick={() => togglePlInstrument(series.instrument_id)}
                        >
                          <span className="flex min-w-0 items-center gap-2">
                            <span
                              className="h-3 w-3 shrink-0 rounded-full"
                              style={{ backgroundColor: instrumentChartColors[index % instrumentChartColors.length] }}
                            />
                            <span className="truncate font-medium">{series.instrument_ticker}</span>
                          </span>
                          <span className={lastPoint.total_pl_usd < 0 ? "shrink-0 text-destructive tabular-nums" : "shrink-0 text-emerald-600 tabular-nums"}>
                            {formatCurrencyValue(lastPoint.total_pl_display ?? lastPoint.total_pl_usd, displayCurrency)}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {currentPortfolio ? (
        <CollapsibleSection
          title="Ребалансировка"
          description="Целевые доли, отклонения и допуски. Операции здесь не создаются автоматически."
          collapsed={isSectionCollapsed("rebalance")}
          onToggle={() => toggleInvestmentSection("rebalance")}
          actions={
            <Button
              variant="outline"
              disabled={activeInstruments.length === 0}
              onClick={() => openDialog({ type: "target-allocation", mode: "create" })}
            >
              <Target className="mr-2 h-4 w-4" />
              Целевая доля
            </Button>
          }
        >
            {rebalanceQuery.isLoading || targetAllocationsQuery.isLoading ? (
              <div className="flex h-[220px] items-center justify-center text-sm text-muted-foreground">Считаем отклонения...</div>
            ) : rebalanceQuery.isError || targetAllocationsQuery.isError || !rebalanceStatus ? (
              <EmptyState
                icon={Target}
                title="Ребалансировка пока недоступна"
                description="Не удалось получить целевые доли или расчет отклонений."
                action={<Button variant="outline" onClick={() => void Promise.all([rebalanceQuery.refetch(), targetAllocationsQuery.refetch()])}>Повторить</Button>}
              />
            ) : targetAllocations.length === 0 ? (
              <EmptyState
                icon={Target}
                title="Целевые доли не заданы"
                description="Добавь целевые проценты по активам, чтобы видеть, что нужно докупить или сократить."
                action={<Button disabled={activeInstruments.length === 0} onClick={() => openDialog({ type: "target-allocation", mode: "create" })}>Добавить цель</Button>}
              />
            ) : (
              <div className="space-y-4">
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Стоимость портфеля</div>
                    <div className="mt-1 text-xl font-semibold tabular-nums">{money(rebalanceStatus.current_value_usd)}</div>
                  </div>
                  <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Вне допуска</div>
                    <div className={offTargetPositions.length > 0 ? "mt-1 text-xl font-semibold text-destructive tabular-nums" : "mt-1 text-xl font-semibold text-emerald-600 tabular-nums"}>
                      {offTargetPositions.length}
                    </div>
                  </div>
                  <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3">
                    <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Целевые доли</div>
                    <div className="mt-1 text-xl font-semibold tabular-nums">{formatPercent(targetAllocationSum)}</div>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1040px] text-left text-sm">
                    <thead className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                      <tr className="border-b border-border/70">
                        <th className="py-3 pr-4">Актив</th>
                        <th className="py-3 pr-4 text-right">Текущая</th>
                        <th className="py-3 pr-4 text-right">Цель</th>
                        <th className="py-3 pr-4 text-right">Допуск</th>
                        <th className="py-3 pr-4 text-right">Отклонение</th>
                        <th className="py-3 pr-4 text-right">Сумма</th>
                        <th className="py-3 pr-4 text-right">Действие</th>
                        <th className="py-3 text-right">Настройки</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rebalancePositions.map((position) => {
                        const allocation = targetAllocationByInstrument.get(position.instrument_id)
                        const isOverTarget = position.allocation_deviation_usd !== null && position.allocation_deviation_usd !== undefined && position.allocation_deviation_usd > 0
                        const actionClass = position.is_within_tolerance
                          ? "text-emerald-600"
                          : isOverTarget
                            ? "text-destructive"
                            : "text-blue-600"
                        return (
                          <tr key={position.instrument_id} className="border-b border-border/50">
                            <td className="py-3 pr-4">
                              <div className="font-medium text-foreground">{position.instrument_ticker}</div>
                              <div className="text-xs text-muted-foreground">{position.instrument_name}</div>
                            </td>
                            <td className="py-3 pr-4 text-right tabular-nums">{formatPercent(position.allocation_percent)}</td>
                            <td className="py-3 pr-4 text-right tabular-nums">{formatPercent(position.target_allocation_percent)}</td>
                            <td className="py-3 pr-4 text-right tabular-nums">{formatPercent(position.tolerance_percent)}</td>
                            <td className={`py-3 pr-4 text-right tabular-nums ${actionClass}`}>
                              {position.allocation_deviation_percent === null || position.allocation_deviation_percent === undefined
                                ? "нет цели"
                                : `${position.allocation_deviation_percent > 0 ? "+" : ""}${formatPercent(position.allocation_deviation_percent)}`}
                            </td>
                            <td className={`py-3 pr-4 text-right tabular-nums ${actionClass}`}>
                              {position.allocation_deviation_usd === null || position.allocation_deviation_usd === undefined
                                ? "нет цели"
                                : `${position.allocation_deviation_usd > 0 ? "+" : ""}${money(position.allocation_deviation_usd)}`}
                            </td>
                            <td className={`py-3 pr-4 text-right font-medium ${actionClass}`}>
                              {rebalanceActionLabels[position.rebalance_action ?? ""] ?? "Нет цели"}
                              {position.rebalance_amount_usd !== null && position.rebalance_amount_usd !== undefined && position.rebalance_amount_usd > 0 ? (
                                <div className="text-xs font-normal tabular-nums">{money(position.rebalance_amount_usd)}</div>
                              ) : null}
                            </td>
                            <td className="py-3 text-right">
                              {allocation ? (
                                <div className="flex justify-end gap-1">
                                  <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "target-allocation", mode: "edit", item: allocation })} aria-label="Редактировать целевую долю">
                                    <PencilLine className="h-4 w-4" />
                                  </Button>
                                  <Button variant="ghost" size="icon" onClick={() => void handleDelete("target-allocation", allocation.id, `целевую долю ${allocation.instrument_ticker ?? position.instrument_ticker}`)} aria-label="Удалить целевую долю">
                                    <Trash2 className="h-4 w-4 text-destructive" />
                                  </Button>
                                </div>
                              ) : (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => openDialog({ type: "target-allocation", mode: "create" })}
                                >
                                  Задать цель
                                </Button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {rebalanceStatus.disclaimer ? (
                  <p className="text-xs text-muted-foreground">{rebalanceStatus.disclaimer}</p>
                ) : null}
              </div>
            )}
        </CollapsibleSection>
      ) : null}

      {currentPortfolio ? (
        <CollapsibleSection
          title="Позиции"
          description="Количество, себестоимость, средняя покупка, текущая оценка и P/L по активам."
          collapsed={isSectionCollapsed("positions")}
          onToggle={() => toggleInvestmentSection("positions")}
          actions={
            <>
              <Badge variant="outline">{currentPortfolio.name}</Badge>
              <Button variant="ghost" size="icon" onClick={() => openDialog({ type: "portfolio", mode: "edit", item: currentPortfolio })} aria-label="Редактировать портфель">
                <PencilLine className="h-4 w-4" />
              </Button>
            </>
          }
        >
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
                        <td className="py-3 pr-4 text-right tabular-nums">{displayMoney(position.cost_basis_display)}</td>
                        <td className="py-3 pr-4 text-right tabular-nums">{displayMoney(position.average_buy_price_display)}</td>
                        <td className="py-3 pr-4 text-right tabular-nums">
                          {position.latest_price_usd === null || position.latest_price_usd === undefined ? (
                            <Button variant="ghost" size="sm" onClick={() => openDialog({ type: "price", mode: "create", item: instruments.find((item) => item.id === position.instrument_id) })}>
                              Добавить
                            </Button>
                          ) : (
                            <div>
                              <div>{displayMoney(position.latest_price_display)}</div>
                              <div className="text-xs text-muted-foreground">{position.latest_price_at ? formatDate(position.latest_price_at) : ""}</div>
                            </div>
                          )}
                        </td>
                        <td className="py-3 pr-4 text-right tabular-nums">
                          {displayMoney(position.current_value_display, position.current_value_usd === null || position.current_value_usd === undefined ? "нет цены" : "нет курса")}
                        </td>
                        <td className={(position.unrealized_pl_display ?? position.unrealized_pl_usd ?? 0) < 0 ? "py-3 pr-4 text-right text-destructive tabular-nums" : "py-3 pr-4 text-right text-emerald-600 tabular-nums"}>
                          {displayMoney(position.unrealized_pl_display)}
                        </td>
                        <td className={(position.total_pl_display ?? position.total_pl_usd) < 0 ? "py-3 pr-4 text-right text-destructive tabular-nums" : "py-3 pr-4 text-right text-emerald-600 tabular-nums"}>
                          {displayMoney(position.total_pl_display)}
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
        </CollapsibleSection>
      ) : (
        <EmptyState
          icon={Landmark}
          title="Нужен первый портфель"
          description="Создай портфель, затем добавь инвестиционные счета, инструменты и операции."
          action={<Button onClick={() => openDialog({ type: "portfolio", mode: "create" })}>Создать портфель</Button>}
        />
      )}

      <div className="flex flex-col gap-4">
        <div className="order-2">
          <CollapsibleSection
            title="Справочники"
            collapsed={isSectionCollapsed("directories")}
            onToggle={() => toggleInvestmentSection("directories")}
            contentClassName="grid gap-3 lg:grid-cols-2"
          >
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
                    <div key={instrument.id} className="rounded-2xl bg-card px-3 py-3 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="break-words font-medium leading-snug text-foreground">{instrument.ticker}</div>
                          <div className="mt-0.5 break-words text-xs leading-snug text-muted-foreground">{instrument.name}</div>
                        </div>
                        <Badge className="shrink-0" variant={instrument.is_active ? "default" : "outline"}>
                          {instrumentTypeLabels[instrument.type] ?? instrument.type}
                        </Badge>
                      </div>
                      <div className="mt-2 flex items-center justify-end gap-1">
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
          </CollapsibleSection>
        </div>

        <div className="order-1">
          <CollapsibleSection
            title="Операции"
            collapsed={isSectionCollapsed("operations")}
            onToggle={() => toggleInvestmentSection("operations")}
            actions={
              <>
              <Button variant="outline" size="sm" disabled={operations.length === 0} onClick={exportOperationsCsv}>
                CSV
              </Button>
              <Button variant="outline" size="icon" onClick={() => void operationsQuery.refetch()} aria-label="Обновить">
                <RefreshCw className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" disabled={!canCreateOperation} onClick={() => openDialog({ type: "operation", mode: "create" })} aria-label="Добавить операцию">
                <Plus className="h-4 w-4" />
              </Button>
              </>
            }
          >
            <div className="mb-4 grid gap-3 md:grid-cols-4">
              <FormField label="Дата с">
                <Input type="date" value={operationDateFrom} onChange={(event) => setOperationDateFrom(event.target.value)} />
              </FormField>
              <FormField label="Дата по">
                <Input type="date" value={operationDateTo} onChange={(event) => setOperationDateTo(event.target.value)} />
              </FormField>
              <FormField label="Инструмент">
                <Select value={operationInstrument} onValueChange={setOperationInstrument}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все</SelectItem>
                    {instruments.map((instrument) => (
                      <SelectItem key={instrument.id} value={instrument.id}>
                        {instrument.ticker}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField label="Счет">
                <Select value={operationAccount} onValueChange={setOperationAccount}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Все</SelectItem>
                    {currentPortfolioAccounts.map((account) => (
                      <SelectItem key={account.id} value={account.id}>
                        {account.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            </div>
            {operations.length === 0 ? (
              <p className="text-sm text-muted-foreground">Операций пока нет.</p>
            ) : (
              <div className="space-y-2">
                {operations.map((operation) => (
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
                        <div className="text-xs text-muted-foreground">{displayMoney(operation.amount_display)}</div>
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
            <div className="mt-4 grid gap-3 border-t border-border/60 pt-4 text-sm sm:grid-cols-3">
              <div className="rounded-2xl bg-background/70 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">Покупки</div>
                <div className="mt-1 font-semibold tabular-nums">{operationTotals.buyComplete ? formatCurrencyValue(operationTotals.buy, displayCurrency) : "нет курса"}</div>
              </div>
              <div className="rounded-2xl bg-background/70 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">Продажи</div>
                <div className="mt-1 font-semibold tabular-nums">{operationTotals.sellComplete ? formatCurrencyValue(operationTotals.sell, displayCurrency) : "нет курса"}</div>
              </div>
              <div className="rounded-2xl bg-background/70 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.12em] text-muted-foreground">Комиссии</div>
                <div className="mt-1 font-semibold tabular-nums">{operationTotals.feeComplete ? formatCurrencyValue(operationTotals.fee, displayCurrency) : "нет курса"}</div>
              </div>
            </div>
          </CollapsibleSection>
        </div>
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
        onSaveTargetAllocation={(id, payload) => saveTargetAllocationMutation.mutate({ id, payload })}
        onSaveOperation={(id, payload) => saveOperationMutation.mutate({ id, payload })}
        isSaving={
          savePortfolioMutation.isPending ||
          saveInstrumentMutation.isPending ||
          savePriceMutation.isPending ||
          saveAccountMutation.isPending ||
          saveTargetAllocationMutation.isPending ||
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
  onSaveTargetAllocation,
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
  onSaveTargetAllocation: (
    id: string | undefined,
    payload: InvestmentTargetAllocationPayload | Partial<InvestmentTargetAllocationPayload>,
  ) => void
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

            {dialog?.type === "target-allocation" ? (
              <TargetAllocationForm
                allocation={dialog.item}
                currentPortfolio={currentPortfolio}
                instruments={instruments}
                isSaving={isSaving}
                onSubmit={(payload) => onSaveTargetAllocation(dialog.item?.id, payload)}
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
            <SelectItem value="bond">Облигация</SelectItem>
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
        <Input value={providerSymbol} onChange={(event) => setProviderSymbol(event.target.value)} placeholder={type === "crypto" ? "bitcoin" : type === "bond" ? "RU000A..." : "AAPL.US"} />
      </FormField>
      <FormField label="Валюта котировки">
        <CurrencySelect value={quoteCurrency} onChange={setQuoteCurrency} />
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
  const [fxRateToUsd, setFxRateToUsd] = useState(priceCurrency.toUpperCase() === "USD" ? "1" : "")
  const [priceUsd, setPriceUsd] = useState("")
  const [source, setSource] = useState("manual")

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      instrument: instrumentId,
      captured_at: capturedAt,
      price: parseFormNumber(price),
      price_currency: priceCurrency.trim().toUpperCase() || selectedInstrument?.quote_currency || "USD",
      fx_rate_to_usd: parseFormNumber(fxRateToUsd, 1),
      price_usd: priceUsd.trim() ? parseFormNumber(priceUsd) : undefined,
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
              setFxRateToUsd(nextInstrument.quote_currency.toUpperCase() === "USD" ? "1" : fxRateToUsd)
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
        <CurrencySelect value={priceCurrency} onChange={setPriceCurrency} />
      </FormField>
      <FormField label="Курс к USD">
        <Input value={fxRateToUsd} onChange={(event) => setFxRateToUsd(event.target.value)} required inputMode="decimal" placeholder="Например: 1" />
      </FormField>
      <FormField label="Цена в USD">
        <Input value={priceUsd} onChange={(event) => setPriceUsd(event.target.value)} inputMode="decimal" placeholder="Можно оставить пустым" />
      </FormField>
      <FormField label="Источник">
        <Input value={source} onChange={(event) => setSource(event.target.value)} placeholder="manual" />
      </FormField>
      <div className="flex items-end">
        <Button type="submit" disabled={isSaving || !instrumentId || !price.trim() || !fxRateToUsd.trim()}>
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
  const [currency, setCurrency] = useState(account?.currency ?? "USD")
  const [hidden, setHidden] = useState(account?.hidden ?? false)

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      portfolio,
      name: name.trim(),
      type,
      currency: currency.trim().toUpperCase() || "USD",
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
        <CurrencySelect value={currency} onChange={setCurrency} />
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

function TargetAllocationForm({
  allocation,
  currentPortfolio,
  instruments,
  isSaving,
  onSubmit,
}: {
  allocation?: InvestmentTargetAllocation
  currentPortfolio: InvestmentPortfolio | null
  instruments: Instrument[]
  isSaving: boolean
  onSubmit: (payload: InvestmentTargetAllocationPayload | Partial<InvestmentTargetAllocationPayload>) => void
}) {
  const activeInstruments = instruments.filter((instrument) => instrument.is_active || instrument.id === allocation?.instrument)
  const [instrument, setInstrument] = useState(allocation?.instrument ?? activeInstruments[0]?.id ?? "")
  const [targetPercent, setTargetPercent] = useState(formatInputNumber(allocation?.target_percent))
  const [tolerancePercent, setTolerancePercent] = useState(formatInputNumber(allocation?.tolerance_percent ?? 5))

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onSubmit({
      portfolio: allocation?.portfolio ?? currentPortfolio?.id ?? "",
      instrument,
      target_percent: parseFormNumber(targetPercent),
      tolerance_percent: parseFormNumber(tolerancePercent, 5),
    })
  }

  return (
    <form className="grid gap-4 md:grid-cols-2" onSubmit={handleSubmit}>
      <FormField label="Портфель">
        <Input value={currentPortfolio?.name ?? allocation?.portfolio_name ?? ""} disabled />
      </FormField>
      <FormField label="Инструмент">
        <Select value={instrument} onValueChange={setInstrument} disabled={!!allocation}>
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
      <FormField label="Целевая доля, %">
        <Input value={targetPercent} onChange={(event) => setTargetPercent(event.target.value)} required inputMode="decimal" placeholder="Например: 40" />
      </FormField>
      <FormField label="Допуск, %">
        <Input value={tolerancePercent} onChange={(event) => setTolerancePercent(event.target.value)} required inputMode="decimal" placeholder="Например: 5" />
      </FormField>
      <div className="md:col-span-2">
        <Button
          type="submit"
          disabled={isSaving || !currentPortfolio || !instrument || !targetPercent.trim() || !tolerancePercent.trim()}
        >
          {isSaving ? "Сохраняем..." : "Сохранить цель"}
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
  const selectedInstrument = activeInstruments.find((item) => item.id === instrument)
  const quoteCurrency = (selectedInstrument?.quote_currency ?? "USD").toUpperCase()
  const [quantity, setQuantity] = useState(formatInputNumber(operation?.quantity))
  const [priceQuote, setPriceQuote] = useState("")
  const [amountQuote, setAmountQuote] = useState("")
  const [feeQuote, setFeeQuote] = useState("")
  const [fxRateToUsd, setFxRateToUsd] = useState(isUsdCurrency(selectedInstrument?.quote_currency) ? "1" : "")
  const [priceQuoteEditedManually, setPriceQuoteEditedManually] = useState(false)
  const [amountQuoteEditedManually, setAmountQuoteEditedManually] = useState(false)
  const [priceUsd, setPriceUsd] = useState(formatInputNumber(operation?.price_usd))
  const [priceEditedManually, setPriceEditedManually] = useState(Boolean(operation?.price_usd))
  const [amountUsd, setAmountUsd] = useState(formatInputNumber(operation?.amount_usd))
  const [amountEditedManually, setAmountEditedManually] = useState(isOperationAmountEditedManually(operation))
  const [feeUsd, setFeeUsd] = useState(formatInputNumber(operation?.fee_usd ?? 0))
  const [posted, setPosted] = useState(operation?.posted ?? true)
  const [deleted, setDeleted] = useState(operation?.deleted ?? false)
  const [comment, setComment] = useState(operation?.comment ?? "")
  const [priceLookupMessage, setPriceLookupMessage] = useState("")
  const needsAmount = operationType === "buy" || operationType === "sell"
  const usesQuoteCurrency = !isUsdCurrency(quoteCurrency)

  useEffect(() => {
    if (!selectedInstrument) {
      return
    }
    if (isUsdCurrency(selectedInstrument.quote_currency)) {
      setFxRateToUsd("1")
      return
    }
    setFxRateToUsd("")
  }, [selectedInstrument?.id, selectedInstrument?.quote_currency])

  useEffect(() => {
    if (!needsAmount || priceEditedManually || !instrument || !date) {
      return
    }
    let isCurrent = true
    setPriceLookupMessage("Ищем цену на дату сделки...")
    InvestmentService.lookupPrice({ instrument, date })
      .then((lookup) => {
        if (!isCurrent) {
          return
        }
        if (lookup.found && lookup.price_usd !== undefined) {
          setPriceUsd(formatInputNumber(lookup.price_usd))
          if (lookup.price !== undefined && lookup.price_currency === quoteCurrency) {
            setPriceQuote(formatInputNumber(lookup.price))
            setPriceQuoteEditedManually(false)
          }
          if (lookup.fx_rate_to_usd !== undefined && !isUsdCurrency(quoteCurrency)) {
            setFxRateToUsd(formatInputNumber(lookup.fx_rate_to_usd))
          }
          setPriceLookupMessage(
            lookup.is_exact_date
              ? `Цена на ${formatDate(lookup.snapshot_date ?? date)}`
              : `Цена от ${formatDate(lookup.snapshot_date ?? date)}, ${lookup.stale_days ?? 0} дн. до сделки`,
          )
          return
        }
        setPriceLookupMessage(lookup.detail ?? "Цена на эту дату не найдена.")
      })
      .catch(() => {
        if (isCurrent) {
          setPriceLookupMessage("Не удалось получить цену на дату.")
        }
      })
    return () => {
      isCurrent = false
    }
  }, [date, instrument, needsAmount, priceEditedManually, quoteCurrency])

  useEffect(() => {
    if (!needsAmount || amountEditedManually) {
      return
    }
    if (!quantity.trim() || !priceUsd.trim()) {
      setAmountUsd("")
      return
    }
    const calculatedAmount = parseFormNumber(quantity) * parseFormNumber(priceUsd)
    if (!Number.isFinite(calculatedAmount) || calculatedAmount <= 0) {
      setAmountUsd("")
      return
    }
    setAmountUsd(formatCalculatedAmount(calculatedAmount))
  }, [amountEditedManually, needsAmount, priceUsd, quantity])

  useEffect(() => {
    if (!needsAmount || !usesQuoteCurrency || !fxRateToUsd.trim()) {
      return
    }
    const rate = parseFormNumber(fxRateToUsd)
    if (!Number.isFinite(rate) || rate <= 0) {
      return
    }
    if (priceQuote.trim() && !priceEditedManually) {
      const nextPriceUsd = parseFormNumber(priceQuote) * rate
      if (Number.isFinite(nextPriceUsd) && nextPriceUsd > 0) {
        setPriceUsd(formatCalculatedPrice(nextPriceUsd))
      }
    }
    if (amountQuote.trim() && !amountEditedManually) {
      const nextAmountUsd = parseFormNumber(amountQuote) * rate
      if (Number.isFinite(nextAmountUsd) && nextAmountUsd > 0) {
        setAmountUsd(formatCalculatedAmount(nextAmountUsd))
      }
    }
    if (feeQuote.trim()) {
      const nextFeeUsd = parseFormNumber(feeQuote) * rate
      if (Number.isFinite(nextFeeUsd) && nextFeeUsd >= 0) {
        setFeeUsd(formatCalculatedAmount(nextFeeUsd))
      }
    }
  }, [amountEditedManually, amountQuote, feeQuote, fxRateToUsd, needsAmount, priceEditedManually, priceQuote, usesQuoteCurrency])

  useEffect(() => {
    if (!needsAmount || priceQuoteEditedManually || !usesQuoteCurrency) {
      return
    }
    if (!quantity.trim() || !amountQuote.trim()) {
      return
    }
    const nextPrice = parseFormNumber(amountQuote) / parseFormNumber(quantity)
    if (Number.isFinite(nextPrice) && nextPrice > 0) {
      setPriceQuote(formatCalculatedPrice(nextPrice))
    }
  }, [amountQuote, needsAmount, priceQuoteEditedManually, quantity, usesQuoteCurrency])

  useEffect(() => {
    if (!needsAmount || amountQuoteEditedManually || !usesQuoteCurrency) {
      return
    }
    if (!quantity.trim() || !priceQuote.trim()) {
      return
    }
    const nextAmount = parseFormNumber(quantity) * parseFormNumber(priceQuote)
    if (Number.isFinite(nextAmount) && nextAmount > 0) {
      setAmountQuote(formatCalculatedAmount(nextAmount))
    }
  }, [amountQuoteEditedManually, needsAmount, priceQuote, quantity, usesQuoteCurrency])

  useEffect(() => {
    if (!needsAmount || priceEditedManually) {
      return
    }
    if (!quantity.trim() || !amountUsd.trim()) {
      return
    }
    const nextPrice = parseFormNumber(amountUsd) / parseFormNumber(quantity)
    if (Number.isFinite(nextPrice) && nextPrice > 0) {
      setPriceUsd(formatCalculatedPrice(nextPrice))
    }
  }, [amountUsd, needsAmount, priceEditedManually, quantity])

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
      price_usd: priceUsd.trim() ? parseFormNumber(priceUsd) : undefined,
      amount_usd: parseFormNumber(amountUsd),
      fee_usd: parseFormNumber(feeUsd),
      comment: comment.trim(),
      posted,
      deleted,
    })
  }

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
        <Select
          value={instrument}
          onValueChange={(value) => {
            setInstrument(value)
            setPriceEditedManually(false)
            setPriceQuoteEditedManually(false)
            setPriceLookupMessage("")
          }}
        >
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
      {usesQuoteCurrency ? (
        <>
          <FormField label={`Цена ${quoteCurrency}`}>
            <Input
              value={priceQuote}
              onChange={(event) => {
                setPriceQuote(event.target.value)
                setPriceQuoteEditedManually(true)
                setPriceEditedManually(false)
              }}
              inputMode="decimal"
              placeholder={`Цена за единицу в ${quoteCurrency}`}
            />
          </FormField>
          <FormField label={`Сумма ${quoteCurrency}`}>
            <Input
              value={amountQuote}
              onChange={(event) => {
                setAmountQuote(event.target.value)
                setAmountQuoteEditedManually(true)
                setAmountEditedManually(false)
              }}
              inputMode="decimal"
              placeholder="Можно ввести итоговую сумму"
            />
          </FormField>
          <FormField label={`${quoteCurrency} к USD`}>
            <Input value={fxRateToUsd} onChange={(event) => setFxRateToUsd(event.target.value)} inputMode="decimal" placeholder="Например: 0.011" />
          </FormField>
          <FormField label={`Комиссия ${quoteCurrency}`}>
            <Input value={feeQuote} onChange={(event) => setFeeQuote(event.target.value)} inputMode="decimal" />
          </FormField>
        </>
      ) : null}
      <FormField label="Цена USD">
        <Input
          value={priceUsd}
          onChange={(event) => {
            setPriceUsd(event.target.value)
            setPriceEditedManually(true)
            setPriceLookupMessage("Цена изменена вручную.")
          }}
          required={needsAmount}
          inputMode="decimal"
          placeholder="Цена за единицу в USD"
        />
        {priceLookupMessage ? <p className="text-xs text-muted-foreground">{priceLookupMessage}</p> : null}
      </FormField>
      <FormField label="Сумма USD">
        <Input
          value={amountUsd}
          onChange={(event) => {
            setAmountUsd(event.target.value)
            setAmountEditedManually(true)
          }}
          required={needsAmount}
          inputMode="decimal"
          placeholder="Авто: количество × цена или сумма в валюте"
        />
      </FormField>
      <FormField label="Комиссия USD">
        <Input value={feeUsd} onChange={(event) => setFeeUsd(event.target.value)} inputMode="decimal" />
      </FormField>
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
            (needsAmount && (!priceUsd.trim() || !amountUsd.trim()))
          }
        >
          {isSaving ? "Сохраняем..." : "Сохранить операцию"}
        </Button>
      </div>
    </form>
  )
}
