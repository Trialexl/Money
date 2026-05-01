"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Save, X } from "lucide-react"

import { useActiveCashFlowItemsQuery } from "@/hooks/use-reference-data"
import { PageHeader } from "@/components/shared/page-header"
import { PlanningGraphicsPanel } from "@/components/shared/planning-graphics-panel"
import { SearchableSelect, type SearchableSelectOption } from "@/components/shared/searchable-select"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Textarea } from "@/components/ui/textarea"
import { formatDateForInput } from "@/lib/formatters"
import { Budget, BudgetService } from "@/services/financial-operations-service"
import { PlanningGraphicDraft, PlanningService } from "@/services/planning-service"

interface BudgetFormProps {
  budget?: Budget
  isEdit?: boolean
}

function toCashFlowItemOption(item: { id: string; name?: string | null; code?: string | null }): SearchableSelectOption {
  return {
    value: item.id,
    label: item.name || "Без названия",
    description: item.code ? `Код ${item.code}` : undefined,
    keywords: [item.code ?? ""],
  }
}

export default function BudgetForm({ budget, isEdit = false }: BudgetFormProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const duplicateId = searchParams.get("duplicate")
  const defaultCashFlowItemId = searchParams.get("cash_flow_item") || ""
  const isDuplicateMode = Boolean(duplicateId) && !isEdit
  const planningDraftStorageKey = !isEdit ? "planning-draft:budget:new" : undefined
  const [type, setType] = useState<"income" | "expense">("expense")
  const [amount, setAmount] = useState("")
  const [date, setDate] = useState(formatDateForInput())
  const [dateStart, setDateStart] = useState("")
  const [amountMonth, setAmountMonth] = useState("")
  const [cashFlowItemId, setCashFlowItemId] = useState<string | undefined>(undefined)
  const [description, setDescription] = useState("")
  const [planningDraftRows, setPlanningDraftRows] = useState<PlanningGraphicDraft[] | null>(isEdit ? null : [])
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setType(budget?.type || "expense")
    setAmount(budget?.amount?.toString() || "")
    setDate(isDuplicateMode ? formatDateForInput() : budget?.date ? formatDateForInput(new Date(budget.date)) : formatDateForInput())
    setDateStart(
      isDuplicateMode
        ? formatDateForInput()
        : budget?.date_start
          ? formatDateForInput(new Date(budget.date_start))
          : ""
    )
    setAmountMonth(budget?.amount_month != null ? String(budget.amount_month) : "")
    setCashFlowItemId(undefined)
    setDescription(budget?.description || "")
    setValidationError(null)
  }, [budget, defaultCashFlowItemId, isDuplicateMode])

  useEffect(() => {
    if (!planningDraftStorageKey) {
      setPlanningDraftRows(isEdit ? null : [])
      return
    }

    setPlanningDraftRows(PlanningService.getDraftRows(planningDraftStorageKey))
  }, [isEdit, planningDraftStorageKey])

  const itemsQuery = useActiveCashFlowItemsQuery()
  const baseCashFlowItemId = budget?.cash_flow_item || defaultCashFlowItemId || ""
  const effectiveCashFlowItemId = cashFlowItemId ?? baseCashFlowItemId

  const budgetMutation = useMutation({
    mutationFn: async () => {
      const parsedAmount = Number.parseFloat(amount)
      const parsedAmountMonth = amountMonth ? Number.parseInt(amountMonth, 10) : undefined
      const payload: Partial<Budget> = {
        type,
        amount: parsedAmount,
        date,
        date_start: dateStart || undefined,
        amount_month: parsedAmountMonth,
        cash_flow_item: effectiveCashFlowItemId,
        description: description.trim() || undefined,
      }

      if (isEdit && budget) {
        return BudgetService.updateBudget(budget.id, payload)
      }

      return BudgetService.createBudget(payload)
    },
    onSuccess: async (savedBudget) => {
      const shouldReplacePlanningRows = isEdit ? planningDraftRows !== null : Boolean(planningDraftRows?.length)

      if (shouldReplacePlanningRows) {
        await PlanningService.replaceGraphicsRows("budget", savedBudget.id, planningDraftRows ?? [])
        if (planningDraftStorageKey) {
          PlanningService.clearDraftRows(planningDraftStorageKey)
        }
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["budgets"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
      ])
      router.push("/budgets")
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)

    const parsedAmount = Number.parseFloat(amount)
    const parsedAmountMonth = amountMonth ? Number.parseInt(amountMonth, 10) : null

    if (!effectiveCashFlowItemId || !date || Number.isNaN(parsedAmount) || parsedAmount <= 0) {
      setValidationError("Укажи тип, дату, статью и сумму бюджета. Сумма должна быть больше нуля.")
      return
    }

    if (parsedAmountMonth !== null && (Number.isNaN(parsedAmountMonth) || parsedAmountMonth <= 0)) {
      setValidationError("Количество месяцев должно быть положительным числом.")
      return
    }

    try {
      await budgetMutation.mutateAsync()
    } catch {}
  }

  const items = itemsQuery.data || []
  const itemOptions = useMemo(() => {
    if (!effectiveCashFlowItemId || items.some((item) => item.id === effectiveCashFlowItemId)) {
      return items
    }

    return [
      ...items,
      {
        id: effectiveCashFlowItemId,
        name: "Загружаем статью",
        code: null,
        created_at: "",
        updated_at: "",
        deleted: false,
      },
    ]
  }, [effectiveCashFlowItemId, items])
  const cashFlowItemOptions: SearchableSelectOption[] = [
    { value: "unselected", label: "Не выбрано" },
    ...itemOptions.map(toCashFlowItemOption),
  ]
  const parsedAmount = Number.parseFloat(amount)
  const hasAmount = !Number.isNaN(parsedAmount) && parsedAmount > 0
  const errorMessage =
    validationError ||
    (budgetMutation.error as any)?.response?.data?.detail ||
    (budgetMutation.error ? "Не удалось сохранить бюджет. Проверь поля и попробуй снова." : null) ||
    null

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Планирование"
        title={isEdit ? "Редактирование бюджета" : "Новый бюджет"}
        description={
          isEdit
            ? "Обнови тип, статью и параметры периода. Бюджеты должны оставаться компактными и понятными для последующего план-факт анализа."
            : "Создай бюджет как плановую запись для дохода или расхода. Это отдельный слой управления, а не фактическая операция."
        }
        actions={
          <Button asChild variant="outline" size="icon">
            <Link href="/budgets" aria-label="К списку" title="К списку">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
        }
      />

      <div>
        <Card>
          <CardHeader>
            <CardTitle>Параметры бюджета</CardTitle>
            <CardDescription>Главное здесь не форма ради формы, а быстрый ввод плановой суммы, типа и периода действия.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-5 rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm leading-5 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            {itemsQuery.isError ? (
              <div className="rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-3 text-sm leading-5 text-destructive">
                Не удалось загрузить статьи для бюджета. Проверь backend API и попробуй обновить страницу.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
                <div className="space-y-3">
                  <Label>Тип бюджета</Label>
                  <RadioGroup value={type} onValueChange={(value) => setType(value as "income" | "expense")} className="grid gap-3 sm:grid-cols-2">
                    <label className="flex cursor-pointer items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                      <RadioGroupItem value="income" id="budget-income" className="mt-1" />
                      <div className="space-y-1">
                        <div className="font-medium text-foreground">Доходный бюджет</div>
                        <div className="text-sm leading-5 text-muted-foreground">План по поступлениям: зарплата, продажи, возвраты, прочие входящие потоки.</div>
                      </div>
                    </label>
                    <label className="flex cursor-pointer items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                      <RadioGroupItem value="expense" id="budget-expense" className="mt-1" />
                      <div className="space-y-1">
                        <div className="font-medium text-foreground">Расходный бюджет</div>
                        <div className="text-sm leading-5 text-muted-foreground">План по затратам: обязательные траты, переменные расходы, лимиты по категориям.</div>
                      </div>
                    </label>
                  </RadioGroup>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="budget-amount">Сумма</Label>
                    <Input
                      id="budget-amount"
                      type="number"
                      min="0"
                      step="0.01"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      placeholder="0.00"
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="budget-date">Дата бюджета</Label>
                    <Input
                      id="budget-date"
                      type="date"
                      value={date}
                      onChange={(event) => setDate(event.target.value)}
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="budget-date-start">Дата начала периода</Label>
                    <Input
                      id="budget-date-start"
                      type="date"
                      value={dateStart}
                      onChange={(event) => setDateStart(event.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="budget-amount-month">Месяцев в графике</Label>
                    <Input
                      id="budget-amount-month"
                      type="number"
                      min="1"
                      step="1"
                      value={amountMonth}
                      onChange={(event) => setAmountMonth(event.target.value)}
                      placeholder="12"
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="budget-item">Статья бюджета</Label>
                  {itemsQuery.isLoading ? (
                    <div className="rounded-[16px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
                      Загружаем статьи...
                    </div>
                  ) : (
                    <SearchableSelect
                      id="budget-item"
                      value={effectiveCashFlowItemId || "unselected"}
                      onValueChange={(value) => setCashFlowItemId(value === "unselected" ? "" : value)}
                      options={cashFlowItemOptions}
                      placeholder="Выбери статью бюджета"
                      searchPlaceholder="Найти статью по названию или коду"
                      emptyLabel="Статья не найдена"
                    />
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="budget-description">Комментарий</Label>
                  <Textarea
                    id="budget-description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Короткое пояснение к логике бюджета"
                    rows={4}
                  />
                </div>

                <div className="flex flex-wrap gap-3">
                  <Button type="submit" disabled={budgetMutation.isPending || itemsQuery.isLoading || itemsQuery.isError}>
                    <Save className="h-4 w-4" />
                    {budgetMutation.isPending ? "Сохраняем..." : isEdit ? "Сохранить и выйти" : "Создать бюджет и выйти"}
                  </Button>
                  <Button asChild variant="outline" size="icon">
                    <Link href="/budgets" aria-label="Отмена" title="Отмена">
                      <X className="h-4 w-4" />
                    </Link>
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </div>

      <PlanningGraphicsPanel
        kind="budget"
        documentId={isEdit ? budget?.id : undefined}
        graphicContract={budget?.graphic_contract}
        draftRows={planningDraftRows ?? undefined}
        draftStorageKey={planningDraftStorageKey}
        onDraftRowsChange={setPlanningDraftRows}
        onTotalAmountChange={(nextAmount) => setAmount(String(nextAmount))}
        distributionSource={{
          totalAmount: hasAmount ? parsedAmount : 0,
          startDate: dateStart || date,
        }}
      />
    </div>
  )
}
