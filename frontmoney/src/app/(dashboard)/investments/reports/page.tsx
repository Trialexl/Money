"use client"

import * as Dialog from "@radix-ui/react-dialog"
import { ResponsiveLine } from "@nivo/line"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, ChevronLeft, ChevronRight, Eye, EyeOff, LineChart, X } from "lucide-react"
import Link from "next/link"
import { useMemo, useState } from "react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { formatDate, formatDateForInput } from "@/lib/formatters"
import {
  InvestmentService,
  type FxRateSnapshot,
  type Instrument,
  type InvestmentInstrumentPerformanceSeries,
  type InvestmentOperation,
  type InvestmentPerformancePoint,
} from "@/services/investment-service"

type DisplayCurrency = "USD" | "EUR" | "RUB"
type RangePreset = "month" | "quarter" | "year" | "ytd" | null
type GroupBy = "day" | "month"

type ChartPoint = {
  x: string
  y: number
  date?: string
  realized?: number | null
  unrealized?: number | null
  total?: number | null
}

type InstrumentLineSeries = {
  id: string
  instrumentId: string
  data: ChartPoint[]
}

type OperationChartMarker = {
  key: string
  x: string
  y: number
  type: "buy" | "sell"
  count: number
  amountUsd: number
  quantity: number
  tickers: string[]
}

type InstrumentLegendItem = {
  id: string
  ticker: string
  name: string
  color: string
  price?: number | null
  totalPl?: number | null
}

const displayCurrencies: DisplayCurrency[] = ["USD", "EUR", "RUB"]
const instrumentChartColors = ["#0f8b8d", "#f97316", "#8b5cf6", "#10b981", "#ef4444", "#3b82f6", "#f59e0b", "#ec4899"]
const SHORT_MONTH_LABELS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
const MONTH_LABELS = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]

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

function getDateKey(value?: string) {
  return value ? value.slice(0, 10) : ""
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

function getPeriodKey(value: string, groupBy: GroupBy) {
  const dateKey = getDateKey(value)
  return groupBy === "month" ? dateKey.slice(0, 7) : dateKey
}

function formatShortPeriodLabel(value: string, groupBy: GroupBy) {
  if (!value) {
    return ""
  }
  if (value === "Старт") {
    return value
  }
  if (groupBy === "month") {
    const [year, month] = value.split("-").map(Number)
    if (!year || !month || month < 1 || month > 12) {
      return value
    }
    return `${SHORT_MONTH_LABELS[month - 1]} ${String(year).slice(-2)}`
  }
  const [year, month, day] = getDateKey(value).split("-")
  return year && month && day ? `${day}.${month}.${year.slice(-2)}` : value
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

function getChartTickValues(data: ChartPoint[]) {
  if (data.length <= 8) {
    return data.map((point) => point.x)
  }
  const step = Math.ceil(data.length / 7)
  return data
    .filter((_, index) => index === 0 || index === data.length - 1 || index % step === 0)
    .map((point) => point.x)
}

function getChartYDomain(data: ChartPoint[], includeZero = false) {
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

function getOperationMarkerLabel(operation: InvestmentOperation, groupBy: GroupBy) {
  return formatShortPeriodLabel(getPeriodKey(operation.date, groupBy), groupBy)
}

function buildOperationMarkers(
  points: ChartPoint[],
  operations: InvestmentOperation[],
  groupBy: GroupBy,
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
        quantity: 0,
        tickers: [],
      }
      marker.count += 1
      marker.amountUsd += operation.amount_usd
      marker.quantity += operation.quantity
      if (operation.instrument_ticker && !marker.tickers.includes(operation.instrument_ticker)) {
        marker.tickers.push(operation.instrument_ticker)
      }
      grouped.set(key, marker)
    })

  return Array.from(grouped.values())
}

function toPerformancePointData(point: InvestmentPerformancePoint, groupBy: GroupBy, key: "current_value" | "total_pl") {
  const label = point.label === "Старт" ? "Старт" : formatShortPeriodLabel(point.date, groupBy)
  const value =
    key === "current_value"
      ? point.current_value_display ?? point.current_value_usd
      : point.total_pl_display ?? point.total_pl_usd

  return {
    x: label,
    y: value,
    date: point.date,
    realized: point.realized_pl_display ?? point.realized_pl_usd,
    unrealized: point.unrealized_pl_display ?? point.unrealized_pl_usd,
    total: point.total_pl_display ?? point.total_pl_usd,
  }
}

function getSeriesLastPoint(series: InvestmentInstrumentPerformanceSeries) {
  return series.points[series.points.length - 1]
}

export default function InvestmentReportsPage() {
  const currentYear = new Date().getFullYear()
  const defaultPeriod = useMemo(() => yearDateRange(), [])
  const [dateFrom, setDateFrom] = useState(defaultPeriod.dateFrom)
  const [dateTo, setDateTo] = useState(defaultPeriod.dateTo)
  const [draftDateFrom, setDraftDateFrom] = useState(defaultPeriod.dateFrom)
  const [draftDateTo, setDraftDateTo] = useState(defaultPeriod.dateTo)
  const [monthPickerYear, setMonthPickerYear] = useState(currentYear)
  const [monthSelectionAnchor, setMonthSelectionAnchor] = useState<string | null>(null)
  const [selectedPreset, setSelectedPreset] = useState<RangePreset>("year")
  const [periodDialogOpen, setPeriodDialogOpen] = useState(false)
  const [groupBy, setGroupBy] = useState<GroupBy>("month")
  const [displayCurrency, setDisplayCurrency] = useState<DisplayCurrency>("USD")
  const [selectedInstrumentId, setSelectedInstrumentId] = useState<string | null>(null)
  const [hiddenInstrumentIds, setHiddenInstrumentIds] = useState<string[]>([])

  const periodFromMonth = getMonthInputValue(draftDateFrom)
  const periodToMonth = getMonthInputValue(draftDateTo)

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
  const fxRatesQuery = useQuery({
    queryKey: ["investment-fx-rates", displayCurrency],
    queryFn: () => InvestmentService.getFxRates({ base_currency: "USD", quote_currency: displayCurrency }),
    enabled: displayCurrency !== "USD",
  })

  const activePortfolioId =
    overviewQuery.data?.portfolio?.id ??
    portfoliosQuery.data?.find((portfolio) => portfolio.is_default)?.id ??
    portfoliosQuery.data?.[0]?.id

  const performanceQuery = useQuery({
    queryKey: ["investment-performance", activePortfolioId, groupBy, dateFrom, dateTo, displayCurrency],
    queryFn: () =>
      InvestmentService.getPortfolioPerformance(activePortfolioId!, {
        date_from: dateFrom,
        date_to: dateTo,
        group_by: groupBy,
        display_currency: displayCurrency,
        scope: "all",
      }),
    enabled: Boolean(activePortfolioId),
  })

  const operationsQuery = useQuery({
    queryKey: ["investment-report-operations", activePortfolioId, dateFrom, dateTo],
    queryFn: () =>
      InvestmentService.getOperations({
        portfolio: activePortfolioId!,
        date_from: dateFrom,
        date_to: dateTo,
      }),
    enabled: Boolean(activePortfolioId),
  })

  const pricesQuery = useQuery({
    queryKey: ["investment-prices", dateFrom, dateTo],
    queryFn: () => InvestmentService.getPrices({ date_from: dateFrom, date_to: dateTo }),
  })

  const isLoading = overviewQuery.isLoading || portfoliosQuery.isLoading || instrumentsQuery.isLoading
  const isError = overviewQuery.isError || portfoliosQuery.isError || instrumentsQuery.isError

  const instruments = instrumentsQuery.data ?? []
  const activeInstruments = instruments.filter((instrument) => instrument.is_active)
  const instrumentById = new Map(instruments.map((instrument) => [instrument.id, instrument]))
  const currentPortfolio = overviewQuery.data?.portfolio ?? portfoliosQuery.data?.find((portfolio) => portfolio.is_default) ?? portfoliosQuery.data?.[0] ?? null
  const fxRates = fxRatesQuery.data ?? []
  const operations = operationsQuery.data ?? []
  const performance = performanceQuery.data
  const performancePoints = performance?.points ?? []

  const instrumentColorById = new Map(
    activeInstruments.map((instrument, index) => [instrument.id, instrumentChartColors[index % instrumentChartColors.length]]),
  )
  const visibleInstrumentIds = new Set(
    activeInstruments
      .filter((instrument) => !hiddenInstrumentIds.includes(instrument.id))
      .filter((instrument) => !selectedInstrumentId || instrument.id === selectedInstrumentId)
      .map((instrument) => instrument.id),
  )

  const valueLineData = performancePoints.map((point) => toPerformancePointData(point, groupBy, "current_value"))
  const plLineData = performancePoints.map((point) => toPerformancePointData(point, groupBy, "total_pl"))
  const valueChartTicks = getChartTickValues(valueLineData)
  const plChartTicks = getChartTickValues(plLineData)
  const valueChartDomain = getChartYDomain(valueLineData)
  const plChartDomain = getChartYDomain(plLineData, true)
  const chartPointSize = performancePoints.length > 60 ? 0 : 7
  const valueOperationMarkers = buildOperationMarkers(valueLineData, operations, groupBy)
  const plOperationMarkers = buildOperationMarkers(plLineData, operations, groupBy)

  const instrumentPlSeries = performance?.instrument_series.filter((series) => series.points.length > 0) ?? []
  const visibleInstrumentPlSeries = instrumentPlSeries.filter((series) => visibleInstrumentIds.has(series.instrument_id))
  const instrumentPlLineData: InstrumentLineSeries[] = visibleInstrumentPlSeries.map((series) => ({
    id: series.instrument_ticker,
    instrumentId: series.instrument_id,
    data: series.points.map((point) => toPerformancePointData(point, groupBy, "total_pl")),
  }))
  const instrumentPlTicks = getChartTickValues(instrumentPlLineData[0]?.data ?? [])
  const instrumentPlDomain = getChartYDomain(instrumentPlLineData.flatMap((series) => series.data), true)
  const instrumentPlOperationMarkers = instrumentPlLineData.flatMap((series) =>
    buildOperationMarkers(series.data, operations, groupBy, { instrumentId: series.instrumentId }),
  )

  const priceSnapshots = (pricesQuery.data ?? [])
    .filter((snapshot) => activeInstruments.some((instrument) => instrument.id === snapshot.instrument))
    .sort((left, right) => left.captured_at.localeCompare(right.captured_at))

  const latestPriceByInstrument = new Map<string, number>()
  const priceSnapshotsByInstrument = new Map<string, Map<string, ChartPoint>>()
  priceSnapshots.forEach((snapshot) => {
    const instrument = instrumentById.get(snapshot.instrument)
    if (!instrument) {
      return
    }
    const periodKey = getPeriodKey(snapshot.captured_at, groupBy)
    const x = formatShortPeriodLabel(periodKey, groupBy)
    const convertedPrice = convertUsdAmount(snapshot.price_usd, displayCurrency, fxRates)
    const priceValue = convertedPrice ?? snapshot.price_usd
    latestPriceByInstrument.set(snapshot.instrument, priceValue)
    const map = priceSnapshotsByInstrument.get(snapshot.instrument) ?? new Map<string, ChartPoint>()
    map.set(periodKey, {
      x,
      y: priceValue,
      date: snapshot.captured_at,
    })
    priceSnapshotsByInstrument.set(snapshot.instrument, map)
  })

  const priceLineData: InstrumentLineSeries[] = activeInstruments
    .filter((instrument) => visibleInstrumentIds.has(instrument.id))
    .map((instrument) => {
      const points = Array.from(priceSnapshotsByInstrument.get(instrument.id)?.entries() ?? [])
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([, point]) => point)
      return {
        id: instrument.ticker,
        instrumentId: instrument.id,
        data: points,
      }
    })
    .filter((series) => series.data.length > 0)
  const priceChartTicks = getChartTickValues(priceLineData[0]?.data ?? [])
  const priceChartDomain = getChartYDomain(priceLineData.flatMap((series) => series.data))
  const priceOperationMarkers = priceLineData.flatMap((series) =>
    buildOperationMarkers(series.data, operations, groupBy, { instrumentId: series.instrumentId }),
  )

  const lastPlByInstrument = new Map(
    instrumentPlSeries.map((series) => {
      const lastPoint = getSeriesLastPoint(series)
      return [series.instrument_id, lastPoint ? lastPoint.total_pl_display ?? lastPoint.total_pl_usd : null]
    }),
  )

  const legendItems: InstrumentLegendItem[] = activeInstruments.map((instrument) => ({
    id: instrument.id,
    ticker: instrument.ticker,
    name: instrument.name,
    color: instrumentColorById.get(instrument.id) ?? instrumentChartColors[0],
    price: latestPriceByInstrument.get(instrument.id) ?? null,
    totalPl: lastPlByInstrument.get(instrument.id) ?? null,
  }))

  const filteredLegendItems = legendItems.filter((item) => visibleInstrumentIds.has(item.id))

  const setPresetRange = (preset: Exclude<RangePreset, null>) => {
    const now = new Date()
    let nextDateFrom = draftDateFrom
    let nextDateTo = draftDateTo

    if (preset === "month") {
      const month = formatDateForInput(now).slice(0, 7)
      nextDateFrom = getMonthStartDate(month)
      nextDateTo = getMonthEndDate(month)
    }
    if (preset === "quarter") {
      const quarterStartMonth = Math.floor(now.getMonth() / 3) * 3
      const start = new Date(now.getFullYear(), quarterStartMonth, 1)
      const end = new Date(now.getFullYear(), quarterStartMonth + 3, 0)
      nextDateFrom = formatDateForInput(start)
      nextDateTo = formatDateForInput(end)
    }
    if (preset === "year") {
      nextDateFrom = `${now.getFullYear()}-01-01`
      nextDateTo = `${now.getFullYear()}-12-31`
    }
    if (preset === "ytd") {
      nextDateFrom = `${now.getFullYear()}-01-01`
      nextDateTo = todayInputDate()
    }

    setSelectedPreset(preset)
    setDraftDateFrom(nextDateFrom)
    setDraftDateTo(nextDateTo)
    setMonthPickerYear(Number(nextDateFrom.slice(0, 4)) || currentYear)
    setMonthSelectionAnchor(null)
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

  const setExactDateFrom = (value: string) => {
    setDraftDateFrom(value)
    setMonthSelectionAnchor(null)
    setSelectedPreset(null)
  }

  const setExactDateTo = (value: string) => {
    setDraftDateTo(value)
    setMonthSelectionAnchor(null)
    setSelectedPreset(null)
  }

  const applyPeriod = () => {
    const normalized = normalizeDateRange(draftDateFrom, draftDateTo)
    setDateFrom(normalized.from)
    setDateTo(normalized.to)
    setPeriodDialogOpen(false)
  }

  const toggleHiddenInstrument = (instrumentId: string) => {
    setHiddenInstrumentIds((current) =>
      current.includes(instrumentId)
        ? current.filter((id) => id !== instrumentId)
        : [...current, instrumentId],
    )
    setSelectedInstrumentId((current) => (current === instrumentId ? null : current))
  }

  const resetInstrumentFilters = () => {
    setSelectedInstrumentId(null)
    setHiddenInstrumentIds([])
  }

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
        const markerAmount = convertUsdAmount(marker.amountUsd, displayCurrency, fxRates)
        const title = [
          isBuy ? "Покупка" : "Продажа",
          marker.x,
          marker.tickers.join(", "),
          `${marker.count} сделк.`,
          markerAmount === null ? "нет курса" : formatCurrencyValue(markerAmount, displayCurrency),
        ].filter(Boolean).join(" · ")
        return (
          <g key={`${marker.key}-${index}`} transform={`translate(${x}, ${y})`}>
            <title>{title}</title>
            <line y1={isBuy ? 8 : -8} y2={isBuy ? 18 : -18} stroke={color} strokeWidth={1.5} strokeDasharray="3 3" />
            <circle r={8} fill={color} stroke="hsl(var(--background))" strokeWidth={2} />
            <text dy="0.36em" textAnchor="middle" fill="#fff" fontSize={11} fontWeight={800}>
              {isBuy ? "+" : "−"}
            </text>
          </g>
        )
      })}
    </g>
  )

  if (isLoading) {
    return <FullPageLoader label="Загружаем инвестиционные отчеты..." />
  }

  if (isError || !overviewQuery.data) {
    return (
      <EmptyState
        icon={LineChart}
        title="Отчеты портфеля пока недоступны"
        description="Backend инвестиционного модуля не ответил. Проверь миграции и доступность API."
        action={<Button onClick={() => void Promise.all([overviewQuery.refetch(), portfoliosQuery.refetch(), instrumentsQuery.refetch()])}>Повторить</Button>}
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Финансовые инструменты"
        title="Отчеты портфеля"
        description="Динамика стоимости, P/L, курсы инструментов и сделки за выбранный период."
        actions={
          <>
            <Button variant="outline" asChild>
              <Link href="/investments">
                <ArrowLeft className="mr-2 h-4 w-4" />
                Портфель
              </Link>
            </Button>
            <Button variant="outline" onClick={() => setPeriodDialogOpen(true)}>
              Период: {formatDate(dateFrom)} — {formatDate(dateTo)}
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2 rounded-[22px] border border-border/70 bg-card/70 px-4 py-3">
        <span className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Валюта</span>
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
        <div className="flex rounded-full border border-border/70 bg-muted/40 p-1">
          <Button type="button" size="sm" variant={groupBy === "day" ? "default" : "ghost"} className="rounded-full" onClick={() => setGroupBy("day")}>
            По дням
          </Button>
          <Button type="button" size="sm" variant={groupBy === "month" ? "default" : "ghost"} className="rounded-full" onClick={() => setGroupBy("month")}>
            По месяцам
          </Button>
        </div>
        <Badge variant="outline">{currentPortfolio?.name ?? "портфель не выбран"}</Badge>
        {displayCurrency !== "USD" ? (
          <span className="text-sm text-muted-foreground">
            {fxRatesQuery.isLoading
              ? "Загружаем курс..."
              : getDisplayRate(displayCurrency, fxRates)
                ? `1 USD = ${formatCurrencyValue(getDisplayRate(displayCurrency, fxRates) ?? 0, displayCurrency)}`
                : "Курс не найден"}
          </span>
        ) : null}
      </div>

      <Dialog.Root open={periodDialogOpen} onOpenChange={setPeriodDialogOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-sm" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(calc(100vw-18px),1040px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[28px] border border-border/70 bg-background shadow-[0_35px_120px_-45px_rgba(15,23,42,0.85)]">
            <div className="flex items-start justify-between gap-4 border-b border-border/60 px-5 py-4 sm:px-6">
              <div className="min-w-0">
                <Dialog.Title className="text-xl font-semibold tracking-[-0.03em] text-foreground">
                  Период инвестиционного отчета
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
                      <Label htmlFor="investment-report-date-from">Дата с</Label>
                      <Input
                        id="investment-report-date-from"
                        type="date"
                        value={draftDateFrom}
                        onChange={(event) => setExactDateFrom(event.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="investment-report-date-to">Дата по</Label>
                      <Input
                        id="investment-report-date-to"
                        type="date"
                        value={draftDateTo}
                        onChange={(event) => setExactDateTo(event.target.value)}
                      />
                    </div>
                    <div className="md:col-span-2">
                      <Button
                        type="button"
                        onClick={applyPeriod}
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

      <Card>
        <CardHeader className="gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle>Динамика портфеля</CardTitle>
            <CardDescription>
              Начальная точка учитывает операции до начала периода. Покупки и продажи отмечены на графиках.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {performanceQuery.isLoading ? (
            <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">Загружаем графики...</div>
          ) : performanceQuery.isError || !performance ? (
            <EmptyState
              icon={LineChart}
              title="График пока недоступен"
              description="Не удалось получить performance API."
              action={<Button variant="outline" onClick={() => void performanceQuery.refetch()}>Повторить</Button>}
            />
          ) : performance.points.length === 0 ? (
            <EmptyState icon={LineChart} title="Нет точек графика" description="За выбранный период нет данных для динамики." />
          ) : (
            <div className="grid gap-6 xl:grid-cols-2">
              <LineChartPanel
                title="Стоимость"
                data={[{ id: "Стоимость", data: valueLineData }]}
                ticks={valueChartTicks}
                domain={valueChartDomain}
                pointSize={chartPointSize}
                colors={["hsl(var(--primary))"]}
                displayCurrency={displayCurrency}
                operationLayer={renderOperationMarkers(valueOperationMarkers)}
              />
              <LineChartPanel
                title="Total P/L"
                data={[{ id: "Total P/L", data: plLineData }]}
                ticks={plChartTicks}
                domain={plChartDomain}
                pointSize={chartPointSize}
                colors={[overviewQuery.data.total_pl_usd < 0 ? "#ef4444" : "#10b981"]}
                displayCurrency={displayCurrency}
                operationLayer={renderOperationMarkers(plOperationMarkers)}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Инструменты: P/L и курсы</CardTitle>
          <CardDescription>
            Клик по инструменту в легенде оставляет только его. Глаз исключает инструмент из графиков и таблицы.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="space-y-5">
              {performanceQuery.isLoading ? (
                <div className="flex h-[320px] items-center justify-center rounded-[22px] border border-border/70 text-sm text-muted-foreground">
                  Загружаем P/L...
                </div>
              ) : instrumentPlLineData.length === 0 ? (
                <EmptyState
                  icon={LineChart}
                  title="Нет данных P/L"
                  description="Для выбранного периода и текущих фильтров нет точек P/L по инструментам."
                  action={hiddenInstrumentIds.length > 0 || selectedInstrumentId ? <Button variant="outline" onClick={resetInstrumentFilters}>Показать все</Button> : undefined}
                />
              ) : (
                <LineChartPanel
                  title="P/L по инструментам"
                  data={instrumentPlLineData}
                  ticks={instrumentPlTicks}
                  domain={instrumentPlDomain}
                  pointSize={performancePoints.length > 60 ? 0 : 6}
                  colorById={(id) => {
                    const series = instrumentPlLineData.find((item) => item.id === id)
                    return (series && instrumentColorById.get(series.instrumentId)) || instrumentChartColors[0]
                  }}
                  displayCurrency={displayCurrency}
                  operationLayer={renderOperationMarkers(instrumentPlOperationMarkers)}
                />
              )}

              {pricesQuery.isLoading ? (
                <div className="flex h-[320px] items-center justify-center rounded-[22px] border border-border/70 text-sm text-muted-foreground">
                  Загружаем курсы...
                </div>
              ) : priceLineData.length === 0 ? (
                <EmptyState
                  icon={LineChart}
                  title="Нет данных по курсам"
                  description="За выбранный период нет снимков цен для видимых инструментов."
                  action={hiddenInstrumentIds.length > 0 || selectedInstrumentId ? <Button variant="outline" onClick={resetInstrumentFilters}>Показать все</Button> : undefined}
                />
              ) : (
                <LineChartPanel
                  title="Курсы инструментов"
                  data={priceLineData}
                  ticks={priceChartTicks}
                  domain={priceChartDomain}
                  pointSize={priceLineData.flatMap((series) => series.data).length > 80 ? 0 : 5}
                  colorById={(id) => {
                    const series = priceLineData.find((item) => item.id === id)
                    return (series && instrumentColorById.get(series.instrumentId)) || instrumentChartColors[0]
                  }}
                  displayCurrency={displayCurrency}
                  operationLayer={renderOperationMarkers(priceOperationMarkers)}
                />
              )}
            </div>

            <InstrumentLegend
              items={legendItems}
              selectedInstrumentId={selectedInstrumentId}
              hiddenInstrumentIds={hiddenInstrumentIds}
              displayCurrency={displayCurrency}
              onSelect={(instrumentId) => setSelectedInstrumentId((current) => (current === instrumentId ? null : instrumentId))}
              onToggleHidden={toggleHiddenInstrument}
              onReset={resetInstrumentFilters}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{selectedInstrumentId ? "Данные по выбранному инструменту" : "Данные по инструментам"}</CardTitle>
          <CardDescription>Таблица следует тем же фильтрам, что и графики.</CardDescription>
        </CardHeader>
        <CardContent>
          {filteredLegendItems.length === 0 ? (
            <div className="rounded-2xl border border-border/70 bg-background/70 px-4 py-6 text-sm text-muted-foreground">
              Все инструменты исключены фильтром.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  <tr className="border-b border-border/70">
                    <th className="py-3 pr-4">Инструмент</th>
                    <th className="py-3 pr-4 text-right">Последняя цена</th>
                    <th className="py-3 pr-4 text-right">Total P/L</th>
                    <th className="py-3 text-right">Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLegendItems.map((item) => (
                    <tr key={item.id} className="border-b border-border/50">
                      <td className="py-3 pr-4">
                        <div className="flex items-center gap-2">
                          <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: item.color }} />
                          <div>
                            <div className="font-medium text-foreground">{item.ticker}</div>
                            <div className="text-xs text-muted-foreground">{item.name}</div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-right tabular-nums">
                        {item.price === null || item.price === undefined ? "нет цены" : formatCurrencyValue(item.price, displayCurrency)}
                      </td>
                      <td className={item.totalPl !== null && item.totalPl !== undefined && item.totalPl < 0 ? "py-3 pr-4 text-right text-destructive tabular-nums" : "py-3 pr-4 text-right text-emerald-600 tabular-nums"}>
                        {item.totalPl === null || item.totalPl === undefined ? "нет P/L" : formatCurrencyValue(item.totalPl, displayCurrency)}
                      </td>
                      <td className="py-3 text-right">
                        {selectedInstrumentId === item.id ? <Badge variant="secondary">выбран</Badge> : <Badge variant="outline">в отчете</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function LineChartPanel({
  title,
  data,
  ticks,
  domain,
  pointSize,
  colors,
  colorById,
  displayCurrency,
  operationLayer,
}: {
  title: string
  data: Array<{ id: string; data: ChartPoint[] }>
  ticks: string[]
  domain: { min: number; max: number }
  pointSize: number
  colors?: string[]
  colorById?: (id: string) => string
  displayCurrency: DisplayCurrency
  operationLayer: any
}) {
  return (
    <div className="min-w-0 rounded-[22px] border border-border/70 bg-background/70 p-4">
      <div className="mb-3 text-sm font-semibold text-foreground">{title}</div>
      <div className="h-[340px]">
        <ResponsiveLine
          data={data}
          margin={{ top: 22, right: 18, bottom: 50, left: 64 }}
          xScale={{ type: "point" }}
          yScale={{ type: "linear", stacked: false, min: domain.min, max: domain.max }}
          axisBottom={{ tickSize: 0, tickPadding: 10, tickRotation: -25, tickValues: ticks }}
          axisLeft={{ tickSize: 0, tickPadding: 8, format: (value) => formatCompactChartValue(Number(value)) }}
          enableGridX={false}
          curve="monotoneX"
          pointSize={pointSize}
          pointBorderWidth={2}
          pointBorderColor={{ from: "serieColor" }}
          colors={colorById ? (series) => colorById(String(series.id)) : colors}
          useMesh
          layers={["grid", "markers", "axes", "crosshair", "lines", "points", operationLayer, "mesh", "legends"]}
          tooltip={({ point }) => {
            const dataPoint = point.data as typeof point.data & {
              realized?: number | null
              unrealized?: number | null
              total?: number | null
            }
            return (
              <div className="rounded border bg-background px-2 py-1 text-xs shadow-sm">
                <div className="font-semibold">
                  {String(point.seriesId)} · {String(point.data.x)}
                </div>
                <div>{formatCurrencyValue(Number(dataPoint.total ?? point.data.y), displayCurrency)}</div>
                {dataPoint.realized !== undefined ? <div>Realized: {formatCurrencyValue(Number(dataPoint.realized ?? 0), displayCurrency)}</div> : null}
                {dataPoint.unrealized !== undefined ? <div>Unrealized: {formatCurrencyValue(Number(dataPoint.unrealized ?? 0), displayCurrency)}</div> : null}
              </div>
            )
          }}
        />
      </div>
    </div>
  )
}

function InstrumentLegend({
  items,
  selectedInstrumentId,
  hiddenInstrumentIds,
  displayCurrency,
  onSelect,
  onToggleHidden,
  onReset,
}: {
  items: InstrumentLegendItem[]
  selectedInstrumentId: string | null
  hiddenInstrumentIds: string[]
  displayCurrency: DisplayCurrency
  onSelect: (instrumentId: string) => void
  onToggleHidden: (instrumentId: string) => void
  onReset: () => void
}) {
  const hiddenSet = new Set(hiddenInstrumentIds)
  const hasFilters = Boolean(selectedInstrumentId) || hiddenInstrumentIds.length > 0

  return (
    <div className="rounded-[22px] border border-border/70 bg-background/70 p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold tracking-[-0.02em]">Легенда инструментов</div>
          <div className="mt-1 text-xs text-muted-foreground">Название — оставить только инструмент. Глаз — исключить.</div>
        </div>
        {hasFilters ? (
          <Button type="button" size="sm" variant="ghost" onClick={onReset}>
            Сброс
          </Button>
        ) : null}
      </div>
      <div className="max-h-[520px] space-y-2 overflow-y-auto pr-1">
        {items.length === 0 ? (
          <div className="rounded-2xl border border-border/60 bg-card/50 px-3 py-3 text-sm text-muted-foreground">
            Инструментов нет.
          </div>
        ) : (
          items.map((item) => {
            const isSelected = selectedInstrumentId === item.id
            const isHidden = hiddenSet.has(item.id)
            return (
              <div
                key={item.id}
                className={`flex items-stretch gap-2 rounded-2xl border px-3 py-2 transition ${
                  isSelected
                    ? "border-primary bg-primary/10"
                    : isHidden
                      ? "border-border/40 bg-muted/30 opacity-60"
                      : "border-border/60 bg-card/50 hover:border-primary/50 hover:bg-muted/50"
                }`}
              >
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onSelect(item.id)}>
                  <div className="flex items-center gap-2">
                    <span className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className={`min-w-0 flex-1 truncate text-sm font-medium ${isHidden ? "line-through" : ""}`}>
                      {item.ticker}
                    </span>
                    <span className="text-sm font-semibold tabular-nums">
                      {item.price === null || item.price === undefined ? "нет цены" : formatCurrencyValue(item.price, displayCurrency)}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {isHidden ? "Исключен" : item.name}
                  </div>
                </button>
                <button
                  type="button"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border/70 bg-background/80 text-muted-foreground transition hover:border-primary/60 hover:text-primary"
                  aria-label={isHidden ? "Вернуть инструмент в отчет" : "Исключить инструмент из отчета"}
                  title={isHidden ? "Вернуть инструмент" : "Исключить инструмент"}
                  onClick={() => onToggleHidden(item.id)}
                >
                  {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
