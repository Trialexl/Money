"use client"

import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useDeferredValue, useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDownRight, ArrowUpRight, Copy, PencilLine, Search, SlidersHorizontal, Trash2, Wallet2, X } from "lucide-react"

import { CatalogPaginationControls } from "@/components/shared/catalog-pagination-controls"
import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { SearchableSelect, type SearchableSelectOption } from "@/components/shared/searchable-select"
import { StatCard } from "@/components/shared/stat-card"
import { useOperationReferenceDataQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { formatCurrency, formatDate } from "@/lib/formatters"
import {
  Expenditure,
  ExpenditureService,
  PageSizeOption,
  Receipt,
  ReceiptService,
} from "@/services/financial-operations-service"

type OperationMode = "receipt" | "expenditure"
type OperationEntity = Receipt | Expenditure
type BudgetFilter = "all" | "included" | "excluded"

interface FinancialOperationsCatalogProps {
  mode: OperationMode
}

const CATALOG_CONFIG = {
  receipt: {
    accentIcon: ArrowDownRight,
    accentTone: "positive" as const,
    categoryLabel: "Статья прихода",
    createHref: "/receipts/new",
    createLabel: "Новый приход",
    deleteConfirm: "Удалить этот приход? На фронте действие необратимо.",
    deleteErrorFallback: "Не удалось удалить приход. Попробуй еще раз.",
    emptyDescription: "Добавь первый приход, чтобы видеть поступления денег по кошелькам и статьям.",
    emptyTitle: "Приходов пока нет",
    errorDescription: "Список приходов сейчас недоступен. Проверь backend API и попробуй снова.",
    errorTitle: "Не удалось загрузить приходы",
    listQueryKey: "receipts",
    loadingLabel: "Загружаем приходы...",
    pageDescription: "",
    pageTitle: "Приходы",
    resetEmptyDescription: "По текущему фильтру приходов не найдено. Сбрось ограничения или создай новую операцию.",
    resetEmptyTitle: "Приходы не найдены",
    routeHref: "/receipts",
  },
  expenditure: {
    accentIcon: ArrowUpRight,
    accentTone: "danger" as const,
    categoryLabel: "Статья расхода",
    createHref: "/expenditures/new",
    createLabel: "Новый расход",
    deleteConfirm: "Удалить этот расход? На фронте действие необратимо.",
    deleteErrorFallback: "Не удалось удалить расход. Попробуй еще раз.",
    emptyDescription: "Добавь первый расход, чтобы начать анализировать денежный отток и бюджетный слой.",
    emptyTitle: "Расходов пока нет",
    errorDescription: "Список расходов сейчас недоступен. Проверь backend API и попробуй снова.",
    errorTitle: "Не удалось загрузить расходы",
    listQueryKey: "expenditures",
    loadingLabel: "Загружаем расходы...",
    pageDescription: "",
    pageTitle: "Расходы",
    resetEmptyDescription: "По текущему фильтру расходов не найдено. Ослабь фильтры или добавь новую операцию.",
    resetEmptyTitle: "Расходы не найдены",
    routeHref: "/expenditures",
  },
} as const

function isExpenditureOperation(operation: OperationEntity): operation is Expenditure {
  return "include_in_budget" in operation
}

function getDuplicateHref(createHref: string, operation: OperationEntity) {
  const params = new URLSearchParams({ duplicate: operation.id })

  if (operation.wallet) {
    params.set("wallet", operation.wallet)
  }

  if (operation.cash_flow_item) {
    params.set("cash_flow_item", operation.cash_flow_item)
  }

  return `${createHref}?${params.toString()}`
}

function getMonthStart(date = new Date()) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function parsePage(value: string | null) {
  const parsed = Number.parseInt(value ?? "", 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1
}

function parsePageSize(value: string | null): PageSizeOption {
  if (value === "50") {
    return 50
  }

  if (value === "100") {
    return 100
  }

  return 20
}

function parseBudgetFilter(value: string | null): BudgetFilter {
  return value === "included" || value === "excluded" ? value : "all"
}

function toCashFlowItemOption(item: { id: string; name?: string | null; code?: string | null }): SearchableSelectOption {
  return {
    value: item.id,
    label: item.name || "Без названия",
    description: item.code ? `Код ${item.code}` : undefined,
    keywords: [item.code ?? ""],
  }
}

export default function FinancialOperationsCatalog({ mode }: FinancialOperationsCatalogProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const config = CATALOG_CONFIG[mode]
  const AccentIcon = config.accentIcon
  const didMountFilterReset = useRef(false)
  const [searchTerm, setSearchTerm] = useState(() => searchParams.get("search") || "")
  const [dateFrom, setDateFrom] = useState(() => searchParams.get("date_from") || "")
  const [dateTo, setDateTo] = useState(() => searchParams.get("date_to") || "")
  const [selectedWalletId, setSelectedWalletId] = useState(() => searchParams.get("wallet") || "all-wallets")
  const [selectedCategoryId, setSelectedCategoryId] = useState(() => searchParams.get("cash_flow_item") || "all-categories")
  const [amountMin, setAmountMin] = useState(() => searchParams.get("amount_min") || "")
  const [amountMax, setAmountMax] = useState(() => searchParams.get("amount_max") || "")
  const [budgetFilter, setBudgetFilter] = useState<BudgetFilter>(() => parseBudgetFilter(searchParams.get("budget")))
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [page, setPage] = useState(() => parsePage(searchParams.get("page")))
  const [pageSize, setPageSize] = useState<PageSizeOption>(() => parsePageSize(searchParams.get("page_size")))
  const deferredSearch = useDeferredValue(searchTerm)
  const referencesQuery = useOperationReferenceDataQuery()
  const normalizedSearch = deferredSearch.trim()

  useEffect(() => {
    if (!didMountFilterReset.current) {
      didMountFilterReset.current = true
      return
    }

    setPage(1)
  }, [normalizedSearch, dateFrom, dateTo, selectedWalletId, selectedCategoryId, amountMin, amountMax, budgetFilter])

  useEffect(() => {
    const params = new URLSearchParams()

    if (normalizedSearch) {
      params.set("search", normalizedSearch)
    }

    if (dateFrom) {
      params.set("date_from", dateFrom)
    }

    if (dateTo) {
      params.set("date_to", dateTo)
    }

    if (selectedWalletId !== "all-wallets") {
      params.set("wallet", selectedWalletId)
    }

    if (selectedCategoryId !== "all-categories") {
      params.set("cash_flow_item", selectedCategoryId)
    }

    if (amountMin) {
      params.set("amount_min", amountMin)
    }

    if (amountMax) {
      params.set("amount_max", amountMax)
    }

    if (mode === "expenditure" && budgetFilter !== "all") {
      params.set("budget", budgetFilter)
    }

    if (page > 1) {
      params.set("page", String(page))
    }

    if (pageSize !== 20) {
      params.set("page_size", String(pageSize))
    }

    const nextSearch = params.toString()
    if (searchParams.toString() !== nextSearch) {
      router.replace(nextSearch ? `${config.routeHref}?${nextSearch}` : config.routeHref, { scroll: false })
    }
  }, [
    amountMax,
    amountMin,
    budgetFilter,
    config.routeHref,
    dateFrom,
    dateTo,
    mode,
    normalizedSearch,
    page,
    pageSize,
    router,
    searchParams,
    selectedCategoryId,
    selectedWalletId,
  ])

  const operationsQuery = useQuery({
    queryKey: [
      config.listQueryKey,
      {
        search: normalizedSearch,
        dateFrom,
        dateTo,
        wallet: selectedWalletId,
        cashFlowItem: selectedCategoryId,
        amountMin,
        amountMax,
        budgetFilter,
        page,
        pageSize,
      },
    ],
    queryFn: async () => {
      if (mode === "receipt") {
        return ReceiptService.getReceiptsPage({
          search: normalizedSearch || undefined,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          wallet: selectedWalletId !== "all-wallets" ? selectedWalletId : undefined,
          cashFlowItem: selectedCategoryId !== "all-categories" ? selectedCategoryId : undefined,
          amountMin: amountMin || undefined,
          amountMax: amountMax || undefined,
          page,
          pageSize,
        })
      }

      return ExpenditureService.getExpendituresPage({
        search: normalizedSearch || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        wallet: selectedWalletId !== "all-wallets" ? selectedWalletId : undefined,
        cashFlowItem: selectedCategoryId !== "all-categories" ? selectedCategoryId : undefined,
        amountMin: amountMin || undefined,
        amountMax: amountMax || undefined,
        includedInBudget: budgetFilter === "all" ? undefined : budgetFilter === "included",
        page,
        pageSize,
      })
    },
    placeholderData: (previousData) => previousData,
  })
  const pageCount = Math.max(operationsQuery.data?.totalPages ?? 1, 1)

  const deleteMutation = useMutation({
    mutationFn: async (operationId: string) => {
      if (mode === "receipt") {
        await ReceiptService.deleteReceipt(operationId)
        return
      }

      await ExpenditureService.deleteExpenditure(operationId)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: [config.listQueryKey] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
        queryClient.invalidateQueries({ queryKey: ["wallets"] }),
      ])
    },
  })

  const handleResetFilters = () => {
    setSearchTerm("")
    setDateFrom("")
    setDateTo("")
    setSelectedWalletId("all-wallets")
    setSelectedCategoryId("all-categories")
    setAmountMin("")
    setAmountMax("")
    setBudgetFilter("all")
    setShowAdvancedFilters(false)
    setPage(1)
  }

  useEffect(() => {
    if (page > pageCount) {
      setPage(pageCount)
    }
  }, [page, pageCount])

  if ((operationsQuery.isLoading && !operationsQuery.data) || referencesQuery.isLoading) {
    return <FullPageLoader label={config.loadingLabel} />
  }

  if (operationsQuery.isError || referencesQuery.isError || !operationsQuery.data) {
    return (
      <EmptyState
        icon={AccentIcon}
        title={config.errorTitle}
        description={config.errorDescription}
        action={<Button onClick={() => operationsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const operationsPage = operationsQuery.data
  const operations = operationsPage.results
  const totalOperations = operationsPage.count
  const wallets = referencesQuery.wallets
  const cashFlowItems = referencesQuery.cashFlowItems
  const walletMap = Object.fromEntries(wallets.map((wallet) => [wallet.id, wallet.name]))
  const categoryMap = Object.fromEntries(cashFlowItems.map((item) => [item.id, item.name || "Без названия"]))
  const categoryOptions: SearchableSelectOption[] = [
    { value: "all-categories", label: "Все статьи" },
    ...cashFlowItems.map(toCashFlowItemOption),
  ]

  const totalAmount = operations.reduce((sum, operation) => sum + operation.amount, 0)
  const uniqueWalletsCount = new Set(operations.map((operation) => operation.wallet)).size
  const uniqueCategoriesCount = new Set(operations.map((operation) => operation.cash_flow_item)).size
  const monthStart = getMonthStart()
  const monthOperationsCount = operations.filter((operation) => new Date(operation.date) >= monthStart).length
  const budgetIncludedAmount =
    mode === "expenditure"
      ? operations.reduce(
          (sum, operation) => sum + (isExpenditureOperation(operation) && operation.include_in_budget ? operation.amount : 0),
          0
        )
      : 0
  const budgetIncludedCount =
    mode === "expenditure"
      ? operations.filter((operation) => isExpenditureOperation(operation) && operation.include_in_budget).length
      : 0
  const hasActiveFilters =
    Boolean(searchTerm.trim() || dateFrom || dateTo || amountMin || amountMax) ||
    selectedWalletId !== "all-wallets" ||
    selectedCategoryId !== "all-categories" ||
    budgetFilter !== "all"
  const activeFilterLabels = [
    searchTerm.trim() ? `Поиск: ${searchTerm.trim()}` : null,
    selectedWalletId !== "all-wallets" ? walletMap[selectedWalletId] || "Кошелек" : null,
    selectedCategoryId !== "all-categories" ? categoryMap[selectedCategoryId] || "Статья" : null,
    dateFrom || dateTo ? `Период: ${dateFrom || "..."} - ${dateTo || "..."}` : null,
    amountMin || amountMax ? `Сумма: ${amountMin || "0"} - ${amountMax || "..."}` : null,
    mode === "expenditure" && budgetFilter === "included" ? "В бюджете" : null,
    mode === "expenditure" && budgetFilter === "excluded" ? "Вне бюджета" : null,
  ].filter(Boolean) as string[]
  const advancedFilterCount = [Boolean(dateFrom), Boolean(dateTo), Boolean(amountMin), Boolean(amountMax)].filter(Boolean).length

  const handleDelete = async (operationId: string) => {
    setActionError(null)

    if (!window.confirm(config.deleteConfirm)) {
      return
    }

    try {
      await deleteMutation.mutateAsync(operationId)
    } catch (error) {
      setActionError((error as any)?.response?.data?.detail || config.deleteErrorFallback)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader className="mb-2" compact title={config.pageTitle} description={config.pageDescription} />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        <StatCard
          label="Сумма на экране"
          value={formatCurrency(totalAmount)}
          hint="Текущая страница"
          icon={AccentIcon}
          tone={config.accentTone}
          variant="compact"
        />
        <StatCard
          label="Операций на странице"
          value={String(operations.length)}
          hint={`Страница ${page}${monthOperationsCount > 0 ? ` · ${monthOperationsCount} в текущем месяце` : ""}`}
          icon={Wallet2}
          variant="compact"
        />
        <StatCard
          label={mode === "receipt" ? "Кошельков в потоке" : "Категорий в потоке"}
          value={String(mode === "receipt" ? uniqueWalletsCount : uniqueCategoriesCount)}
          hint="На текущей странице"
          icon={mode === "receipt" ? Wallet2 : AccentIcon}
          className="col-span-2 xl:col-span-1"
          variant="compact"
        />
      </div>

      {mode === "expenditure" ? (
        <div className="grid grid-cols-2 gap-3">
          <StatCard
            label="В бюджете"
            value={formatCurrency(budgetIncludedAmount)}
            hint={`${budgetIncludedCount} операций на текущей странице`}
            icon={AccentIcon}
            tone={budgetIncludedCount > 0 ? "positive" : "neutral"}
            variant="compact"
          />
          <StatCard label="Все расходы на экране" value={String(operations.length)} hint="На текущей странице" icon={Wallet2} variant="compact" />
        </div>
      ) : null}

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <div className="uppercase tracking-[0.16em]">Найдено {totalOperations}, показано {operations.length}</div>
            <div className="flex flex-wrap gap-2">
              {hasActiveFilters ? (
                <Button variant="outline" size="sm" onClick={handleResetFilters}>
                  <X className="h-3.5 w-3.5" />
                  Очистить
                </Button>
              ) : null}
              <Button variant={showAdvancedFilters ? "default" : "outline"} size="sm" onClick={() => setShowAdvancedFilters((current) => !current)}>
                <SlidersHorizontal className="h-3.5 w-3.5" />
                {showAdvancedFilters ? "Скрыть детали" : "Даты и суммы"}
                {advancedFilterCount > 0 ? ` · ${advancedFilterCount}` : null}
              </Button>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor={`${mode}-search`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Поиск
              </Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id={`${mode}-search`}
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Описание, номер, кошелек или статья"
                  className="h-11 rounded-xl bg-background/70 pl-10"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${mode}-wallet-filter`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Кошелек
              </Label>
              <Select value={selectedWalletId} onValueChange={setSelectedWalletId}>
                <SelectTrigger id={`${mode}-wallet-filter`} className="h-11 rounded-xl bg-background/70 px-3.5">
                  <SelectValue placeholder="Все кошельки" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all-wallets">Все кошельки</SelectItem>
                  {wallets.map((wallet) => (
                    <SelectItem key={wallet.id} value={wallet.id}>
                      {wallet.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`${mode}-category-filter`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                {config.categoryLabel}
              </Label>
              <SearchableSelect
                id={`${mode}-category-filter`}
                value={selectedCategoryId}
                onValueChange={setSelectedCategoryId}
                options={categoryOptions}
                placeholder="Все статьи"
                searchPlaceholder="Найти статью по названию или коду"
                emptyLabel="Статья не найдена"
                triggerClassName="bg-background/70 px-3.5"
              />
            </div>
          </div>

          {mode === "expenditure" ? (
            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Бюджет</Label>
              <div className="flex flex-wrap gap-2">
                <Button variant={budgetFilter === "all" ? "default" : "outline"} size="sm" onClick={() => setBudgetFilter("all")}>
                  Все расходы
                </Button>
                <Button variant={budgetFilter === "included" ? "default" : "outline"} size="sm" onClick={() => setBudgetFilter("included")}>
                  В бюджете
                </Button>
                <Button variant={budgetFilter === "excluded" ? "default" : "outline"} size="sm" onClick={() => setBudgetFilter("excluded")}>
                  Вне бюджета
                </Button>
              </div>
            </div>
          ) : null}

          {showAdvancedFilters ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="space-y-2">
                <Label htmlFor={`${mode}-date-from`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Дата с
                </Label>
                <Input id={`${mode}-date-from`} type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="h-11 rounded-xl bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${mode}-date-to`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Дата по
                </Label>
                <Input id={`${mode}-date-to`} type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="h-11 rounded-xl bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor={`${mode}-amount-min`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма от
                </Label>
                <Input
                  id={`${mode}-amount-min`}
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
                <Label htmlFor={`${mode}-amount-max`} className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма до
                </Label>
                <Input
                  id={`${mode}-amount-max`}
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

      {operations.length === 0 ? (
        <EmptyState
          icon={AccentIcon}
          title={hasActiveFilters ? config.resetEmptyTitle : config.emptyTitle}
          description={hasActiveFilters ? config.resetEmptyDescription : config.emptyDescription}
          action={
            !hasActiveFilters ? (
              <Button asChild>
                <Link href={config.createHref}>{config.createLabel}</Link>
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
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 px-6 py-4">
              <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">Журнал операций</div>
              <Badge variant="outline">{operations.length} строк</Badge>
            </div>

            <div className="divide-y divide-border/60 md:hidden">
              {operations.map((operation) => {
                const budgetIncluded = mode === "expenditure" && isExpenditureOperation(operation) ? operation.include_in_budget : null

                return (
                  <div key={operation.id} className="space-y-4 px-5 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={mode === "receipt" ? "success" : "secondary"}>
                            {mode === "receipt" ? "Приход" : "Расход"}
                          </Badge>
                          {budgetIncluded === true ? <Badge variant="success">В бюджете</Badge> : null}
                          {budgetIncluded === false ? <Badge variant="outline">Вне бюджета</Badge> : null}
                        </div>
                        {operation.description ? <div className="text-sm font-medium text-foreground">{operation.description}</div> : null}
                        <div className="text-xs text-muted-foreground">
                          {operation.number || "Без номера"} · {formatDate(operation.date)}
                        </div>
                      </div>
                      <div
                        className={`text-right text-lg font-semibold tracking-[-0.03em] ${
                          mode === "receipt" ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"
                        }`}
                      >
                        {`${mode === "receipt" ? "+" : "-"}${formatCurrency(operation.amount)}`}
                      </div>
                    </div>

                    <div className="grid gap-3 rounded-[20px] border border-border/60 bg-background/70 p-4 text-sm sm:grid-cols-2">
                      <div>
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Кошелек</div>
                        <div className="mt-1 text-foreground">{walletMap[operation.wallet] || "Неизвестный кошелек"}</div>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Статья</div>
                        <div className="mt-1 text-foreground">{categoryMap[operation.cash_flow_item] || "Неизвестная статья"}</div>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-1">
                      <Button asChild variant="ghost" size="icon">
                        <Link href={`${config.routeHref}/${operation.id}/edit`} aria-label="Редактировать" title="Редактировать">
                          <PencilLine className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button asChild variant="ghost" size="icon">
                        <Link href={getDuplicateHref(config.createHref, operation)} aria-label="Дублировать" title="Дублировать">
                          <Copy className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(operation.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[980px]">
                <thead className="bg-background/60">
                  <tr className="border-b border-border/70 text-left text-xs uppercase tracking-[0.16em] text-muted-foreground">
                    <th className="px-6 py-4 font-medium">Операция</th>
                    <th className="px-4 py-4 font-medium">Дата</th>
                    <th className="px-4 py-4 font-medium">Кошелек</th>
                    <th className="px-4 py-4 font-medium">Статья</th>
                    <th className="px-4 py-4 text-right font-medium">Сумма</th>
                    <th className="px-4 py-4 font-medium">Статус</th>
                    <th className="px-6 py-4 text-right font-medium">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {operations.map((operation) => {
                    const budgetIncluded = mode === "expenditure" && isExpenditureOperation(operation) ? operation.include_in_budget : null

                    return (
                      <tr key={operation.id} className="border-b border-border/60 align-top last:border-b-0">
                        <td className="px-6 py-4">
                          <div className="max-w-[280px]">
                            {operation.description ? <div className="text-sm font-medium text-foreground">{operation.description}</div> : null}
                            <div className="mt-1 text-xs text-muted-foreground">{operation.number || "Без номера"}</div>
                          </div>
                        </td>
                        <td className="px-4 py-4 text-sm text-foreground">{formatDate(operation.date)}</td>
                        <td className="px-4 py-4 text-sm text-foreground">{walletMap[operation.wallet] || "Неизвестный кошелек"}</td>
                        <td className="px-4 py-4 text-sm text-foreground">{categoryMap[operation.cash_flow_item] || "Неизвестная статья"}</td>
                        <td
                          className={`px-4 py-4 text-right text-sm font-semibold ${
                            mode === "receipt" ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300"
                          }`}
                        >
                          {`${mode === "receipt" ? "+" : "-"}${formatCurrency(operation.amount)}`}
                        </td>
                        <td className="px-4 py-4">
                          <div className="flex flex-wrap gap-2">
                            <Badge variant={mode === "receipt" ? "success" : "secondary"}>
                              {mode === "receipt" ? "Приход" : "Расход"}
                            </Badge>
                            {budgetIncluded === true ? <Badge variant="success">В бюджете</Badge> : null}
                            {budgetIncluded === false ? <Badge variant="outline">Вне бюджета</Badge> : null}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex justify-end gap-1">
                            <Button asChild variant="ghost" size="icon">
                              <Link href={`${config.routeHref}/${operation.id}/edit`} aria-label="Редактировать" title="Редактировать">
                                <PencilLine className="h-4 w-4" />
                              </Link>
                            </Button>
                            <Button asChild variant="ghost" size="icon">
                              <Link href={getDuplicateHref(config.createHref, operation)} aria-label="Дублировать" title="Дублировать">
                                <Copy className="h-4 w-4" />
                              </Link>
                            </Button>
                            <Button variant="ghost" size="icon" onClick={() => handleDelete(operation.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <CatalogPaginationControls
              page={page}
              pageCount={pageCount}
              pageSize={pageSize}
              totalCount={totalOperations}
              currentCount={operations.length}
              onPageChange={setPage}
              onPageSizeChange={(value) => {
                setPageSize(value as PageSizeOption)
                setPage(1)
              }}
            />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
