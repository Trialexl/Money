"use client"

import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CalendarRange, Plus, Sparkles, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { formatCurrency, formatDate, formatDateForInput } from "@/lib/formatters"
import { PlanningDocumentKind, PlanningGraphicDraft, PlanningService } from "@/services/planning-service"

interface PlanningGraphicsPanelProps {
  kind: PlanningDocumentKind
  documentId?: string
  graphicContract?: Record<string, unknown> | null
  draftRows?: PlanningGraphicDraft[]
  draftStorageKey?: string
  onDraftRowsChange?: (rows: PlanningGraphicDraft[]) => void
  onTotalAmountChange?: (amount: number) => void
  onMonthlyAmountChange?: (amount: number) => void
  onMonthCountChange?: (monthCount: number) => void
  distributionSource?: {
    totalAmount?: number
    monthlyAmount?: number
    monthCount?: number
    startDate?: string
  }
}

function contractDescription(kind: PlanningDocumentKind) {
  if (kind === "expenditure") {
    return "Разложение расхода по периодам."
  }

  if (kind === "budget") {
    return "Периоды исполнения бюджета."
  }

  if (kind === "auto-payment") {
    return "Плановые срабатывания правила."
  }

  return "Периоды перевода между кошельками."
}

function formatAmountInput(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return ""
  }

  return String(Math.round(value * 100) / 100)
}

function formatMonthCountInput(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "1"
  }

  return String(Math.trunc(value))
}

export function PlanningGraphicsPanel({
  kind,
  documentId,
  graphicContract,
  draftRows,
  draftStorageKey,
  onDraftRowsChange,
  onTotalAmountChange,
  onMonthlyAmountChange,
  onMonthCountChange,
  distributionSource,
}: PlanningGraphicsPanelProps) {
  const [dateStart, setDateStart] = useState(formatDateForInput())
  const [amount, setAmount] = useState("")
  const [distributionStartDate, setDistributionStartDate] = useState(distributionSource?.startDate || formatDateForInput())
  const [distributionTotalAmount, setDistributionTotalAmount] = useState(formatAmountInput(distributionSource?.totalAmount))
  const [distributionMonthCount, setDistributionMonthCount] = useState(formatMonthCountInput(distributionSource?.monthCount))
  const [distributionMonthlyAmount, setDistributionMonthlyAmount] = useState(formatAmountInput(distributionSource?.monthlyAmount))
  const [rows, setRows] = useState<PlanningGraphicDraft[]>(draftRows ?? [])
  const [rowsReady, setRowsReady] = useState(!documentId)
  const [rowsTouched, setRowsTouched] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setDateStart(formatDateForInput())
    setAmount("")
    setRowsTouched(false)
    setRowsReady(!documentId)
    setValidationError(null)
  }, [documentId, kind])

  useEffect(() => {
    setDistributionStartDate(distributionSource?.startDate || formatDateForInput())
  }, [distributionSource?.startDate])

  useEffect(() => {
    setDistributionTotalAmount(formatAmountInput(distributionSource?.totalAmount))
  }, [distributionSource?.totalAmount])

  useEffect(() => {
    setDistributionMonthCount(formatMonthCountInput(distributionSource?.monthCount))
  }, [distributionSource?.monthCount])

  useEffect(() => {
    setDistributionMonthlyAmount(formatAmountInput(distributionSource?.monthlyAmount))
  }, [distributionSource?.monthlyAmount])

  const graphicsQuery = useQuery({
    queryKey: ["planning-graphics", kind, documentId ?? "new"],
    enabled: Boolean(documentId),
    refetchOnWindowFocus: false,
    queryFn: () => PlanningService.getGraphics(kind, documentId!),
  })

  useEffect(() => {
    if (!documentId || !graphicsQuery.data || rowsTouched) {
      return
    }

    setRows(
      graphicsQuery.data.map((row) => ({
        id: `server-${row.id}`,
        date_start: row.date_start,
        amount: row.amount,
      }))
    )
    setRowsReady(true)
  }, [documentId, graphicsQuery.data, rowsTouched])

  useEffect(() => {
    if (documentId) {
      return
    }

    if (Array.isArray(draftRows)) {
      setRows(draftRows)
      setRowsReady(true)
      return
    }

    if (draftStorageKey) {
      setRows(PlanningService.getDraftRows(draftStorageKey))
      setRowsReady(true)
    }
  }, [documentId, draftRows, draftStorageKey])

  useEffect(() => {
    if (!rowsReady || documentId || !draftStorageKey) {
      return
    }

    PlanningService.saveDraftRows(draftStorageKey, rows)
  }, [documentId, draftStorageKey, rows, rowsReady])

  const totalAmount = useMemo(
    () => rows.reduce((sum, row) => sum + row.amount, 0),
    [rows]
  )

  const commitRows = (nextRows: PlanningGraphicDraft[]) => {
    setRows(nextRows)
    setRowsTouched(true)
    onDraftRowsChange?.(nextRows)
  }

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)

    const parsedAmount = Number.parseFloat(amount)
    if (Number.isNaN(parsedAmount) || parsedAmount <= 0 || !dateStart) {
      setValidationError("Укажи дату строки графика и положительную сумму.")
      return
    }

    commitRows(
      [...rows, { id: `draft-${Date.now()}-${rows.length}`, date_start: dateStart, amount: parsedAmount }].sort((left, right) =>
        left.date_start.localeCompare(right.date_start)
      )
    )
    setAmount("")
  }

  const handleDelete = (rowId: string) => {
    commitRows(rows.filter((row) => row.id !== rowId))
  }

  const handleRowChange = (rowId: string, patch: Partial<Pick<PlanningGraphicDraft, "date_start" | "amount">>) => {
    commitRows(
      rows
        .map((row) => (row.id === rowId ? { ...row, ...patch } : row))
        .sort((left, right) => left.date_start.localeCompare(right.date_start))
    )
  }

  const handleDistributionMonthCountChange = (value: string) => {
    setDistributionMonthCount(value)

    const parsedMonths = Number.parseInt(value, 10)
    if (Number.isFinite(parsedMonths) && parsedMonths > 0) {
      onMonthCountChange?.(parsedMonths)

      const parsedMonthlyAmount = Number.parseFloat(distributionMonthlyAmount)
      if (!Number.isNaN(parsedMonthlyAmount) && parsedMonthlyAmount > 0) {
        setDistributionTotalAmount(formatAmountInput(parsedMonthlyAmount * parsedMonths))
      }
    }
  }

  const handleDistributionMonthlyAmountChange = (value: string) => {
    setDistributionMonthlyAmount(value)

    const parsedMonthlyAmount = Number.parseFloat(value)
    const parsedMonths = Number.parseInt(distributionMonthCount, 10)
    if (!Number.isNaN(parsedMonthlyAmount) && parsedMonthlyAmount > 0 && Number.isFinite(parsedMonths) && parsedMonths > 0) {
      setDistributionTotalAmount(formatAmountInput(parsedMonthlyAmount * parsedMonths))
    }
  }

  const handleDistributionTotalBlur = () => {
    const parsedTotalAmount = Number.parseFloat(distributionTotalAmount)
    if (!Number.isNaN(parsedTotalAmount) && parsedTotalAmount > 0 && !onMonthlyAmountChange) {
      onTotalAmountChange?.(Math.round(parsedTotalAmount * 100) / 100)
    }
  }

  const handleAutoFill = () => {
    setValidationError(null)

    const parsedMonths = Number.parseInt(distributionMonthCount, 10)
    const parsedTotalAmount = Number.parseFloat(distributionTotalAmount)
    const parsedMonthlyAmount = Number.parseFloat(distributionMonthlyAmount)

    if (!Number.isFinite(parsedMonths) || parsedMonths <= 0) {
      setValidationError("Укажи положительное количество месяцев.")
      return
    }

    const builtRows =
      !Number.isNaN(parsedMonthlyAmount) && parsedMonthlyAmount > 0
        ? PlanningService.buildMonthlyRows({
            monthlyAmount: parsedMonthlyAmount,
            startDate: distributionStartDate,
            monthCount: parsedMonths,
          })
        : PlanningService.buildDistributedRows({
            totalAmount: parsedTotalAmount,
            startDate: distributionStartDate,
            monthCount: parsedMonths,
          })

    if (builtRows.length === 0) {
      setValidationError("Укажи дату начала, число месяцев и сумму: ежемесячную или итоговую в документе.")
      return
    }

    commitRows(builtRows)
    if (!Number.isNaN(parsedMonthlyAmount) && parsedMonthlyAmount > 0) {
      const nextTotalAmount = Math.round(parsedMonthlyAmount * parsedMonths * 100) / 100
      setDistributionTotalAmount(formatAmountInput(nextTotalAmount))
      onMonthlyAmountChange?.(parsedMonthlyAmount)
      if (!onMonthlyAmountChange) {
        onTotalAmountChange?.(nextTotalAmount)
      }
    } else if (!Number.isNaN(parsedTotalAmount) && parsedTotalAmount > 0) {
      const nextTotalAmount = Math.round(parsedTotalAmount * 100) / 100
      const averageMonthlyAmount = Math.round((nextTotalAmount / parsedMonths) * 100) / 100
      onTotalAmountChange?.(nextTotalAmount)
      onMonthlyAmountChange?.(averageMonthlyAmount)
    }
    onMonthCountChange?.(parsedMonths)
  }

  const hasContract = Object.keys(graphicContract ?? {}).length > 0
  const canAutoFill = Number.parseFloat(distributionTotalAmount) > 0 || Number.parseFloat(distributionMonthlyAmount) > 0

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle>Расписание исполнения</CardTitle>
        <CardDescription>{contractDescription(kind)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 md:grid-cols-2">
          <div className="rounded-xl border border-border/70 bg-background/70 px-3 py-2.5">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Периодов</div>
            <div className="mt-1 text-xl font-semibold tracking-[-0.04em]">{rows.length}</div>
          </div>
          <div className="rounded-xl border border-border/70 bg-background/70 px-3 py-2.5">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Сумма по расписанию</div>
            <div className="mt-1 text-xl font-semibold tracking-[-0.04em]">{formatCurrency(totalAmount)}</div>
          </div>
        </div>

        {hasContract ? (
          <div className="rounded-xl border border-border/70 bg-background/70 px-3 py-2 text-sm text-muted-foreground">
            Расписание сохраняется вместе с документом.
          </div>
        ) : null}

        <div className="space-y-3 rounded-xl border border-border/70 bg-background/70 p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="h-4 w-4 text-primary" />
            Автозаполнение графика
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_150px_150px_120px_auto] xl:items-end">
            <div className="space-y-2">
              <Label htmlFor={`${kind}-distribution-date`}>Дата начала</Label>
              <Input
                id={`${kind}-distribution-date`}
                type="date"
                value={distributionStartDate}
                onChange={(event) => setDistributionStartDate(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${kind}-distribution-total`}>Общая сумма</Label>
              <Input
                id={`${kind}-distribution-total`}
                type="number"
                min="0"
                step="0.01"
                value={distributionTotalAmount}
                onBlur={handleDistributionTotalBlur}
                onChange={(event) => setDistributionTotalAmount(event.target.value)}
                placeholder="0.00"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${kind}-distribution-monthly`}>Сумма в месяц</Label>
              <Input
                id={`${kind}-distribution-monthly`}
                type="number"
                min="0"
                step="0.01"
                value={distributionMonthlyAmount}
                onChange={(event) => handleDistributionMonthlyAmountChange(event.target.value)}
                placeholder="0.00"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${kind}-distribution-months`}>Месяцев</Label>
              <Input
                id={`${kind}-distribution-months`}
                type="number"
                min="1"
                step="1"
                value={distributionMonthCount}
                onChange={(event) => handleDistributionMonthCountChange(event.target.value)}
              />
            </div>
            <Button type="button" variant="outline" onClick={handleAutoFill} disabled={!canAutoFill} className="md:col-span-2 xl:col-span-1">
              <Sparkles className="h-4 w-4" />
              Заполнить
            </Button>
          </div>
          <div className="text-xs leading-5 text-muted-foreground">
            Если сумма в месяц заполнена, график строится по ней. Если пустая — общая сумма распределяется по месяцам.
          </div>
        </div>

        <form onSubmit={handleCreate} className="space-y-3 rounded-xl border border-border/70 bg-background/70 p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <CalendarRange className="h-4 w-4 text-primary" />
            Добавить период
          </div>
          {validationError ? (
            <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {validationError}
            </div>
          ) : null}
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={`${kind}-graphic-date`}>Дата периода</Label>
              <Input
                id={`${kind}-graphic-date`}
                type="date"
                value={dateStart}
                onChange={(event) => setDateStart(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${kind}-graphic-amount`}>Сумма периода</Label>
              <Input
                id={`${kind}-graphic-amount`}
                type="number"
                min="0"
                step="0.01"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="0.00"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button type="submit" variant="outline">
              <Plus className="h-4 w-4" />
              Добавить период
            </Button>
          </div>
        </form>

        {graphicsQuery.isLoading ? (
          <div className="rounded-xl border border-border/70 bg-background/70 px-4 py-8 text-center text-sm text-muted-foreground">
            Загружаем расписание...
          </div>
        ) : graphicsQuery.isError ? (
          <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-8 text-center text-sm text-destructive">
            Не удалось загрузить расписание. Проверь backend API и попробуй снова.
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/70 px-4 py-6 text-center text-sm text-muted-foreground">
            Для этого документа пока не задано ни одного периода.
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map((graphic, index) => (
              <div key={graphic.id} className="grid gap-2 rounded-xl border border-border/70 bg-background/70 px-3 py-2 md:grid-cols-[90px_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center">
                <div className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">#{index + 1}</div>
                <div className="space-y-1">
                  <Label htmlFor={`${kind}-row-${graphic.id}-date`} className="text-xs">Дата</Label>
                  <Input
                    id={`${kind}-row-${graphic.id}-date`}
                    type="date"
                    value={graphic.date_start}
                    onChange={(event) => handleRowChange(graphic.id, { date_start: event.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`${kind}-row-${graphic.id}-amount`} className="text-xs">Сумма</Label>
                  <Input
                    id={`${kind}-row-${graphic.id}-amount`}
                    type="number"
                    min="0"
                    step="0.01"
                    value={Number.isFinite(graphic.amount) ? graphic.amount : ""}
                    onChange={(event) => handleRowChange(graphic.id, { amount: Number.parseFloat(event.target.value) })}
                  />
                </div>
                <div className="flex items-end gap-2 md:justify-end">
                  <div className="hidden min-w-28 text-right text-sm font-semibold md:block">{formatCurrency(graphic.amount)}</div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handleDelete(graphic.id)}
                    aria-label={`Удалить период ${formatDate(graphic.date_start)}`}
                    title="Удалить период"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
