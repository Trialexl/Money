"use client"

import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarRange, Loader2, Plus, Save, Sparkles, Trash2 } from "lucide-react"

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
  distributionSource?: {
    totalAmount?: number
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

export function PlanningGraphicsPanel({
  kind,
  documentId,
  graphicContract,
  draftRows,
  draftStorageKey,
  onDraftRowsChange,
  distributionSource,
}: PlanningGraphicsPanelProps) {
  const queryClient = useQueryClient()
  const [dateStart, setDateStart] = useState(formatDateForInput())
  const [amount, setAmount] = useState("")
  const [distributionStartDate, setDistributionStartDate] = useState(distributionSource?.startDate || formatDateForInput())
  const [distributionMonthCount, setDistributionMonthCount] = useState("1")
  const [rows, setRows] = useState<PlanningGraphicDraft[]>(draftRows ?? [])
  const [validationError, setValidationError] = useState<string | null>(null)
  const [saveFeedback, setSaveFeedback] = useState<string | null>(null)

  useEffect(() => {
    setDateStart(formatDateForInput())
    setAmount("")
    setDistributionStartDate(distributionSource?.startDate || formatDateForInput())
    setDistributionMonthCount("1")
    setValidationError(null)
    setSaveFeedback(null)
  }, [documentId, distributionSource?.startDate, kind])

  const graphicsQuery = useQuery({
    queryKey: ["planning-graphics", kind, documentId ?? "new"],
    enabled: Boolean(documentId),
    queryFn: () => PlanningService.getGraphics(kind, documentId!),
  })

  useEffect(() => {
    if (documentId) {
      if (graphicsQuery.data) {
        setRows(
          graphicsQuery.data.map((row) => ({
            id: `server-${row.id}`,
            date_start: row.date_start,
            amount: row.amount,
          }))
        )
      }
      return
    }

    if (Array.isArray(draftRows)) {
      setRows(draftRows)
      return
    }

    if (draftStorageKey) {
      setRows(PlanningService.getDraftRows(draftStorageKey))
    }
  }, [documentId, draftRows, draftStorageKey, graphicsQuery.data])

  useEffect(() => {
    if (documentId) {
      return
    }

    onDraftRowsChange?.(rows)
  }, [documentId, onDraftRowsChange, rows])

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (documentId) {
        await PlanningService.replaceGraphicsRows(kind, documentId, rows)
        return
      }

      if (!draftStorageKey) {
        throw new Error("Не удалось сохранить черновик графика.")
      }

      PlanningService.saveDraftRows(draftStorageKey, rows)
    },
    onSuccess: async () => {
      if (documentId) {
        await queryClient.invalidateQueries({ queryKey: ["planning-graphics", kind, documentId ?? "new"] })
        setSaveFeedback("Расписание сохранено отдельно от документа.")
        return
      }

      setSaveFeedback("Черновик расписания сохранен.")
    },
  })

  const graphics = graphicsQuery.data ?? []
  const totalAmount = useMemo(
    () => rows.reduce((sum, row) => sum + row.amount, 0),
    [rows]
  )

  const handleCreate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)
    setSaveFeedback(null)

    const parsedAmount = Number.parseFloat(amount)
    if (Number.isNaN(parsedAmount) || parsedAmount <= 0 || !dateStart) {
      setValidationError("Укажи дату строки графика и положительную сумму.")
      return
    }

    setRows((current) =>
      [...current, { id: `draft-${Date.now()}-${current.length}`, date_start: dateStart, amount: parsedAmount }].sort((left, right) =>
        left.date_start.localeCompare(right.date_start)
      )
    )
    setAmount("")
  }

  const handleDelete = (rowId: string) => {
    setRows((current) => current.filter((row) => row.id !== rowId))
    setSaveFeedback(null)
  }

  const handleAutoFill = () => {
    setValidationError(null)
    setSaveFeedback(null)

    const parsedMonths = Number.parseInt(distributionMonthCount, 10)
    const totalFromDocument = distributionSource?.totalAmount ?? 0
    const builtRows = PlanningService.buildDistributedRows({
      totalAmount: totalFromDocument,
      startDate: distributionStartDate,
      monthCount: parsedMonths,
    })

    if (builtRows.length === 0) {
      setValidationError("Для автозаполнения укажи дату начала, число месяцев и общую сумму документа больше нуля.")
      return
    }

    setRows(builtRows)
  }

  const hasContract = Object.keys(graphicContract ?? {}).length > 0
  const canAutoFill = Boolean(distributionSource?.totalAmount && distributionSource.totalAmount > 0)
  const canSaveDraft = documentId ? rows.length >= 0 : Boolean(draftStorageKey)

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle>Расписание исполнения</CardTitle>
        <CardDescription>{contractDescription(kind)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Периодов</div>
            <div className="mt-1 text-xl font-semibold tracking-[-0.04em]">{rows.length}</div>
          </div>
          <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Сумма по расписанию</div>
            <div className="mt-1 text-xl font-semibold tracking-[-0.04em]">{formatCurrency(totalAmount)}</div>
          </div>
        </div>

        {hasContract ? (
          <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
            Изменения в расписании учитываются отдельно от шапки документа.
          </div>
        ) : null}

        <div className="space-y-3 rounded-[20px] border border-border/70 bg-background/70 p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="h-4 w-4 text-primary" />
            Автозаполнение графика
          </div>
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_140px_auto] md:items-end">
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
              <Label htmlFor={`${kind}-distribution-months`}>Месяцев</Label>
              <Input
                id={`${kind}-distribution-months`}
                type="number"
                min="1"
                step="1"
                value={distributionMonthCount}
                onChange={(event) => setDistributionMonthCount(event.target.value)}
              />
            </div>
            <Button type="button" variant="outline" onClick={handleAutoFill} disabled={!canAutoFill}>
              <Sparkles className="h-4 w-4" />
              Заполнить
            </Button>
          </div>
        </div>

        <form onSubmit={handleCreate} className="space-y-3 rounded-[20px] border border-border/70 bg-background/70 p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <CalendarRange className="h-4 w-4 text-primary" />
            Добавить период
          </div>
          {validationError ? (
            <div className="rounded-[18px] border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
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
            <Button type="button" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !canSaveDraft}>
              {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Сохранить расписание
            </Button>
          </div>
          {saveFeedback ? <div className="text-xs leading-5 text-emerald-600 dark:text-emerald-300">{saveFeedback}</div> : null}
          {!documentId ? (
            <div className="text-xs text-muted-foreground">
              Можно сохранить черновик отдельно.
            </div>
          ) : null}
        </form>

        {graphicsQuery.isLoading ? (
          <div className="rounded-[24px] border border-border/70 bg-background/70 px-4 py-12 text-center text-sm text-muted-foreground">
            Загружаем расписание...
          </div>
        ) : graphicsQuery.isError ? (
          <div className="rounded-[24px] border border-destructive/20 bg-destructive/10 px-4 py-12 text-center text-sm text-destructive">
            Не удалось загрузить расписание. Проверь backend API и попробуй снова.
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-[20px] border border-dashed border-border/70 px-4 py-8 text-center text-sm text-muted-foreground">
            Для этого документа пока не задано ни одного периода.
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map((graphic, index) => (
              <div key={graphic.id} className="flex items-center justify-between gap-3 rounded-[18px] border border-border/70 bg-background/70 px-4 py-3">
                <div>
                  <div className="text-sm font-medium text-foreground">{formatDate(graphic.date_start)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">Период #{index + 1}</div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-sm font-semibold">{formatCurrency(graphic.amount)}</div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => handleDelete(graphic.id)}
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
