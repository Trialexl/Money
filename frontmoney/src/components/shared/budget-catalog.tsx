"use client"

import Link from "next/link"
import { useDeferredValue, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Copy, Landmark, PencilLine, PiggyBank, Search, SlidersHorizontal, Trash2, TrendingDown, TrendingUp, X } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { useActiveCashFlowItemsQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { BudgetService } from "@/services/financial-operations-service"

function getMonthStart(date = new Date()) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function getBudgetDuplicateHref(budget: Awaited<ReturnType<typeof BudgetService.getBudgets>>[number]) {
  const params = new URLSearchParams({ duplicate: budget.id })

  if (budget.cash_flow_item) {
    params.set("cash_flow_item", budget.cash_flow_item)
  }

  return `/budgets/new?${params.toString()}`
}

export default function BudgetCatalog() {
  const queryClient = useQueryClient()
  const [searchTerm, setSearchTerm] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [typeFilter, setTypeFilter] = useState<"all" | "income" | "expense">("all")
  const [categoryId, setCategoryId] = useState("all-categories")
  const [amountMin, setAmountMin] = useState("")
  const [amountMax, setAmountMax] = useState("")
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const deferredSearch = useDeferredValue(searchTerm)
  const itemsQuery = useActiveCashFlowItemsQuery()

  const budgetsQuery = useQuery({
    queryKey: ["budgets"],
    queryFn: async () => {
      const budgets = await BudgetService.getBudgets()
      return budgets.filter((budget) => !budget.deleted)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (budgetId: string) => BudgetService.deleteBudget(budgetId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["budgets"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
      ])
    },
  })

  const handleResetFilters = () => {
    setSearchTerm("")
    setDateFrom("")
    setDateTo("")
    setTypeFilter("all")
    setCategoryId("all-categories")
    setAmountMin("")
    setAmountMax("")
    setShowAdvancedFilters(false)
  }

  if (budgetsQuery.isLoading || itemsQuery.isLoading) {
    return <FullPageLoader label="Загружаем бюджеты..." />
  }

  if (budgetsQuery.isError || itemsQuery.isError || !budgetsQuery.data) {
    return (
      <EmptyState
        icon={PiggyBank}
        title="Не удалось загрузить бюджеты"
        description="Бюджетный слой сейчас недоступен. Проверь backend API и попробуй снова."
        action={<Button onClick={() => budgetsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const budgets = budgetsQuery.data
  const cashFlowItems = itemsQuery.data || []
  const categoryMap = Object.fromEntries(cashFlowItems.map((item) => [item.id, item.name || "Без названия"]))
  const normalizedSearch = deferredSearch.trim().toLowerCase()
  const parsedAmountMin = amountMin ? Number.parseFloat(amountMin) : null
  const parsedAmountMax = amountMax ? Number.parseFloat(amountMax) : null

  const filteredBudgets = budgets
    .filter((budget) => {
      const categoryName = categoryMap[budget.cash_flow_item] || ""
      const haystack = `${budget.description || ""} ${budget.number || ""} ${categoryName}`.toLowerCase()

      if (normalizedSearch && !haystack.includes(normalizedSearch)) {
        return false
      }

      if (typeFilter !== "all" && budget.type !== typeFilter) {
        return false
      }

      if (categoryId !== "all-categories" && budget.cash_flow_item !== categoryId) {
        return false
      }

      if (dateFrom && budget.date < dateFrom) {
        return false
      }

      if (dateTo && budget.date > dateTo) {
        return false
      }

      if (parsedAmountMin !== null && budget.amount < parsedAmountMin) {
        return false
      }

      if (parsedAmountMax !== null && budget.amount > parsedAmountMax) {
        return false
      }

      return true
    })
    .sort((left, right) => {
      if (left.date === right.date) {
        return right.amount - left.amount
      }

      return right.date.localeCompare(left.date)
    })

  const incomeTotal = filteredBudgets.filter((budget) => budget.type === "income").reduce((sum, budget) => sum + budget.amount, 0)
  const expenseTotal = filteredBudgets.filter((budget) => budget.type === "expense").reduce((sum, budget) => sum + budget.amount, 0)
  const periodCountTotal = filteredBudgets.reduce((sum, budget) => sum + (budget.amount_month || 0), 0)
  const monthStart = getMonthStart()
  const recentCount = filteredBudgets.filter((budget) => new Date(budget.date) >= monthStart).length
  const hasActiveFilters =
    Boolean(searchTerm.trim() || dateFrom || dateTo || amountMin || amountMax) || typeFilter !== "all" || categoryId !== "all-categories"
  const activeFilterLabels = [
    searchTerm.trim() ? `Поиск: ${searchTerm.trim()}` : null,
    typeFilter === "income" ? "Доходные" : null,
    typeFilter === "expense" ? "Расходные" : null,
    categoryId !== "all-categories" ? categoryMap[categoryId] || "Статья" : null,
    dateFrom || dateTo ? `Период: ${dateFrom || "..."} - ${dateTo || "..."}` : null,
    amountMin || amountMax ? `Сумма: ${amountMin || "0"} - ${amountMax || "..."}` : null,
  ].filter(Boolean) as string[]
  const advancedFilterCount = [Boolean(dateFrom), Boolean(dateTo), Boolean(amountMin), Boolean(amountMax)].filter(Boolean).length

  const handleDelete = async (budgetId: string) => {
    setActionError(null)

    if (!window.confirm("Удалить этот бюджет? На фронте действие необратимо.")) {
      return
    }

    try {
      await deleteMutation.mutateAsync(budgetId)
    } catch (error) {
      setActionError((error as any)?.response?.data?.detail || "Не удалось удалить бюджет. Попробуй еще раз.")
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        compact
        title="Бюджеты"
      />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="План по доходам" value={formatCurrency(incomeTotal)} hint="Доходные бюджеты" icon={TrendingUp} tone={incomeTotal > 0 ? "positive" : "neutral"} variant="compact" />
        <StatCard label="План по расходам" value={formatCurrency(expenseTotal)} hint="Расходные бюджеты" icon={TrendingDown} tone={expenseTotal > 0 ? "danger" : "neutral"} variant="compact" />
        <StatCard label="Периодов в графике" value={String(periodCountTotal)} hint="Текущая выборка" icon={Landmark} variant="compact" />
        <StatCard label="Новых в этом месяце" value={String(recentCount)} hint="Текущий месяц" icon={PiggyBank} variant="compact" />
      </div>

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <div className="uppercase tracking-[0.16em]">Найдено {filteredBudgets.length} из {budgets.length}</div>
            <div className="flex flex-wrap gap-2">
              {hasActiveFilters ? (
                <Button variant="outline" size="sm" onClick={handleResetFilters}>
                  <X className="h-3.5 w-3.5" />
                  Очистить
                </Button>
              ) : null}
              <Button
                variant={showAdvancedFilters ? "default" : "outline"}
                size="sm"
                onClick={() => setShowAdvancedFilters((current) => !current)}
              >
                <SlidersHorizontal className="h-3.5 w-3.5" />
                {showAdvancedFilters ? "Скрыть детали" : "Период и суммы"}
                {advancedFilterCount > 0 ? ` · ${advancedFilterCount}` : null}
              </Button>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="budget-search" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Поиск
              </Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="budget-search"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Описание, номер или статья"
                  className="h-11 rounded-xl bg-background/70 pl-10"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Тип бюджета</Label>
              <div className="flex flex-wrap gap-2">
                <Button variant={typeFilter === "all" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("all")}>
                  Все
                </Button>
                <Button variant={typeFilter === "income" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("income")}>
                  Доходы
                </Button>
                <Button variant={typeFilter === "expense" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("expense")}>
                  Расходы
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="budget-category-filter" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Статья бюджета
              </Label>
              <Select value={categoryId} onValueChange={setCategoryId}>
                <SelectTrigger id="budget-category-filter" className="h-11 rounded-xl bg-background/70 px-3.5">
                  <SelectValue placeholder="Все статьи" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all-categories">Все статьи</SelectItem>
                  {cashFlowItems.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name || "Без названия"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {showAdvancedFilters ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="space-y-2">
                <Label htmlFor="budget-date-from" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Дата с
                </Label>
                <Input id="budget-date-from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="h-11 rounded-xl bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-date-to" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Дата по
                </Label>
                <Input id="budget-date-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="h-11 rounded-xl bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-amount-min" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма от
                </Label>
                <Input
                  id="budget-amount-min"
                  type="number"
                  min="0"
                  step="0.01"
                  value={amountMin}
                  onChange={(event) => setAmountMin(event.target.value)}
                  placeholder="0.00"
                  className="h-11 rounded-xl bg-background/70"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-amount-max" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма до
                </Label>
                <Input
                  id="budget-amount-max"
                  type="number"
                  min="0"
                  step="0.01"
                  value={amountMax}
                  onChange={(event) => setAmountMax(event.target.value)}
                  placeholder="0.00"
                  className="h-11 rounded-xl bg-background/70"
                />
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-3 text-xs text-muted-foreground">
            <div className="uppercase tracking-[0.16em]">Фильтры</div>
            <div className="flex flex-wrap justify-end gap-2">
              {activeFilterLabels.length > 0 ? (
                activeFilterLabels.map((label) => (
                  <Badge key={label} variant="outline">
                    {label}
                  </Badge>
                ))
              ) : (
                <span>Без фильтров</span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {actionError ? (
        <div className="rounded-[24px] border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm leading-6 text-destructive">
          {actionError}
        </div>
      ) : null}

      {filteredBudgets.length === 0 ? (
        <EmptyState
          icon={PiggyBank}
          title={budgets.length === 0 ? "Бюджетов пока нет" : "Бюджеты не найдены"}
          description={
            budgets.length === 0
              ? "Создай первый бюджет, чтобы отделить планирование от фактических операций."
              : "По текущим фильтрам ничего не найдено. Ослабь ограничения или очисти поиск."
          }
          action={
            budgets.length === 0 ? (
              <Button asChild>
                <Link href="/budgets/new">Создать бюджет</Link>
              </Button>
            ) : (
              <Button variant="outline" onClick={handleResetFilters}>
                Очистить фильтры
              </Button>
            )
          }
        />
      ) : (
        <Card className="overflow-hidden">
          <CardContent className="p-0">
            <div className="hidden grid-cols-[180px_minmax(0,1.3fr)_160px_160px_120px_124px] gap-4 border-b border-border/70 px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground lg:grid">
              <div>Сумма</div>
              <div>Статья</div>
              <div>Тип</div>
              <div>Период</div>
              <div>Дата</div>
              <div className="text-right">Действия</div>
            </div>

            <div className="divide-y divide-border/60">
              {filteredBudgets.map((budget) => {
                const isIncome = budget.type === "income"
                return (
                  <div key={budget.id} className="px-4 py-4 lg:grid lg:grid-cols-[180px_minmax(0,1.3fr)_160px_160px_120px_124px] lg:items-center lg:gap-4 lg:px-5 lg:py-3">
                    <div className="flex items-center gap-2">
                      <div
                        className={`text-lg font-semibold tracking-[-0.03em] ${
                          isIncome ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"
                        }`}
                      >
                        {formatCurrency(budget.amount)}
                      </div>
                      <Badge variant={isIncome ? "success" : "secondary"}>{isIncome ? "Доход" : "Расход"}</Badge>
                    </div>

                    <div className="mt-3 min-w-0 lg:mt-0">
                      <div className="truncate text-sm font-medium text-foreground">
                        {categoryMap[budget.cash_flow_item] || "Неизвестная статья"}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        {budget.number ? <span>№ {budget.number}</span> : null}
                        {budget.description ? <span className="truncate">{budget.description}</span> : null}
                      </div>
                    </div>

                    <div className="mt-3 text-sm text-muted-foreground lg:mt-0">
                      {isIncome ? "Доходный бюджет" : "Расходный бюджет"}
                    </div>

                    <div className="mt-3 space-y-1 text-sm text-muted-foreground lg:mt-0">
                      <div>{budget.date_start ? formatDate(budget.date_start) : "Без периода"}</div>
                      {budget.amount_month ? <div>{budget.amount_month} мес. в графике</div> : null}
                    </div>

                    <div className="mt-3 text-sm text-muted-foreground lg:mt-0">{formatDate(budget.date)}</div>

                    <div className="mt-4 flex justify-end gap-1 lg:mt-0">
                      <Button asChild variant="ghost" size="icon">
                        <Link href={`/budgets/${budget.id}/edit`} aria-label="Редактировать" title="Редактировать">
                          <PencilLine className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button asChild variant="ghost" size="icon">
                        <Link href={getBudgetDuplicateHref(budget)} aria-label="Дублировать" title="Дублировать">
                          <Copy className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(budget.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
