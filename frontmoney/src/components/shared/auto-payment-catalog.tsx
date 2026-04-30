"use client"

import Link from "next/link"
import { useDeferredValue, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, ArrowRightLeft, CalendarRange, Copy, PencilLine, Search, SlidersHorizontal, Trash2, Wallet2, X } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { useOperationReferenceDataQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { AutoPaymentService } from "@/services/financial-operations-service"

function getDaysUntil(dateString?: string) {
  if (!dateString) {
    return null
  }

  const target = new Date(dateString)
  if (Number.isNaN(target.getTime())) {
    return null
  }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  target.setHours(0, 0, 0, 0)

  return Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

function getAutoPaymentDuplicateHref(autoPayment: Awaited<ReturnType<typeof AutoPaymentService.getAutoPayments>>[number]) {
  const params = new URLSearchParams({ duplicate: autoPayment.id })

  if (autoPayment.wallet_from) {
    params.set("wallet_from", autoPayment.wallet_from)
  }

  if (autoPayment.wallet_to) {
    params.set("wallet_to", autoPayment.wallet_to)
  }

  if (autoPayment.cash_flow_item) {
    params.set("cash_flow_item", autoPayment.cash_flow_item)
  }

  return `/auto-payments/new?${params.toString()}`
}

export default function AutoPaymentCatalog() {
  const queryClient = useQueryClient()
  const [searchTerm, setSearchTerm] = useState("")
  const [typeFilter, setTypeFilter] = useState<"all" | "transfer" | "expense">("all")
  const [walletFromId, setWalletFromId] = useState("all-wallets-from")
  const [walletToId, setWalletToId] = useState("all-wallets-to")
  const [categoryId, setCategoryId] = useState("all-categories")
  const [amountMin, setAmountMin] = useState("")
  const [amountMax, setAmountMax] = useState("")
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const deferredSearch = useDeferredValue(searchTerm)
  const referencesQuery = useOperationReferenceDataQuery()

  const autoPaymentsQuery = useQuery({
    queryKey: ["auto-payments"],
    queryFn: async () => {
      const autoPayments = await AutoPaymentService.getAutoPayments()
      return autoPayments.filter((autoPayment) => !autoPayment.deleted)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (autoPaymentId: string) => AutoPaymentService.deleteAutoPayment(autoPaymentId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["auto-payments"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
      ])
    },
  })

  const handleResetFilters = () => {
    setSearchTerm("")
    setTypeFilter("all")
    setWalletFromId("all-wallets-from")
    setWalletToId("all-wallets-to")
    setCategoryId("all-categories")
    setAmountMin("")
    setAmountMax("")
    setShowAdvancedFilters(false)
  }

  if (autoPaymentsQuery.isLoading || referencesQuery.isLoading) {
    return <FullPageLoader label="Загружаем автоплатежи..." />
  }

  if (autoPaymentsQuery.isError || referencesQuery.isError || !autoPaymentsQuery.data) {
    return (
      <EmptyState
        icon={CalendarRange}
        title="Не удалось загрузить автоплатежи"
        description="Повторяющиеся операции сейчас недоступны. Проверь backend API и попробуй снова."
        action={<Button onClick={() => autoPaymentsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const autoPayments = autoPaymentsQuery.data
  const wallets = referencesQuery.wallets
  const cashFlowItems = referencesQuery.cashFlowItems
  const walletMap = Object.fromEntries(wallets.map((wallet) => [wallet.id, wallet.name]))
  const categoryMap = Object.fromEntries(cashFlowItems.map((item) => [item.id, item.name || "Без названия"]))
  const normalizedSearch = deferredSearch.trim().toLowerCase()
  const parsedAmountMin = amountMin ? Number.parseFloat(amountMin) : null
  const parsedAmountMax = amountMax ? Number.parseFloat(amountMax) : null

  const filteredAutoPayments = autoPayments
    .filter((autoPayment) => {
      const sourceWallet = walletMap[autoPayment.wallet_from] || ""
      const targetWallet = autoPayment.wallet_to ? walletMap[autoPayment.wallet_to] || "" : ""
      const categoryName = autoPayment.cash_flow_item ? categoryMap[autoPayment.cash_flow_item] || "" : ""
      const haystack = `${autoPayment.description || ""} ${autoPayment.number || ""} ${sourceWallet} ${targetWallet} ${categoryName}`.toLowerCase()

      if (normalizedSearch && !haystack.includes(normalizedSearch)) {
        return false
      }

      if (typeFilter === "transfer" && !autoPayment.is_transfer) {
        return false
      }

      if (typeFilter === "expense" && autoPayment.is_transfer) {
        return false
      }

      if (walletFromId !== "all-wallets-from" && autoPayment.wallet_from !== walletFromId) {
        return false
      }

      if (walletToId !== "all-wallets-to" && autoPayment.wallet_to !== walletToId) {
        return false
      }

      if (categoryId !== "all-categories" && autoPayment.cash_flow_item !== categoryId) {
        return false
      }

      if (parsedAmountMin !== null && autoPayment.amount < parsedAmountMin) {
        return false
      }

      if (parsedAmountMax !== null && autoPayment.amount > parsedAmountMax) {
        return false
      }

      return true
    })
    .sort((left, right) => {
      const leftDate = left.date_start || left.date
      const rightDate = right.date_start || right.date
      return leftDate.localeCompare(rightDate)
    })

  const totalAmount = filteredAutoPayments.reduce((sum, autoPayment) => sum + autoPayment.amount, 0)
  const dueSoonCount = filteredAutoPayments.filter((autoPayment) => {
    const daysUntil = getDaysUntil(autoPayment.date_start)
    return daysUntil !== null && daysUntil <= 7
  }).length
  const transferCount = filteredAutoPayments.filter((autoPayment) => autoPayment.is_transfer).length
  const expenseCount = filteredAutoPayments.length - transferCount
  const hasActiveFilters =
    Boolean(searchTerm.trim() || amountMin || amountMax) ||
    typeFilter !== "all" ||
    walletFromId !== "all-wallets-from" ||
    walletToId !== "all-wallets-to" ||
    categoryId !== "all-categories"
  const activeFilterLabels = [
    searchTerm.trim() ? `Поиск: ${searchTerm.trim()}` : null,
    typeFilter === "transfer" ? "Только автопереводы" : null,
    typeFilter === "expense" ? "Только автосписания" : null,
    walletFromId !== "all-wallets-from" ? `Источник: ${walletMap[walletFromId] || "кошелек"}` : null,
    walletToId !== "all-wallets-to" ? `Назначение: ${walletMap[walletToId] || "кошелек"}` : null,
    categoryId !== "all-categories" ? categoryMap[categoryId] || "Статья" : null,
    amountMin || amountMax ? `Сумма: ${amountMin || "0"} - ${amountMax || "..."}` : null,
  ].filter(Boolean) as string[]
  const advancedFilterCount = [
    Boolean(walletToId !== "all-wallets-to"),
    Boolean(categoryId !== "all-categories"),
    Boolean(amountMin),
    Boolean(amountMax),
  ].filter(Boolean).length

  const handleDelete = async (autoPaymentId: string) => {
    setActionError(null)

    if (!window.confirm("Удалить этот автоплатеж? На фронте действие необратимо.")) {
      return
    }

    try {
      await deleteMutation.mutateAsync(autoPaymentId)
    } catch (error) {
      setActionError((error as any)?.response?.data?.detail || "Не удалось удалить автоплатеж. Попробуй еще раз.")
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        compact
        title="Автоплатежи"
      />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Сумма на экране" value={formatCurrency(totalAmount)} hint="Текущая выборка" icon={CalendarRange} variant="compact" />
        <StatCard label="Скоро сработают" value={String(dueSoonCount)} hint="Ближайшие 7 дней" icon={AlertCircle} tone={dueSoonCount > 0 ? "danger" : "neutral"} variant="compact" />
        <StatCard label="Автопереводы" value={String(transferCount)} hint="Между кошельками" icon={ArrowRightLeft} variant="compact" />
        <StatCard label="Автосписания" value={String(expenseCount)} hint="Расходные правила" icon={Wallet2} variant="compact" />
      </div>

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <div className="uppercase tracking-[0.16em]">Найдено {filteredAutoPayments.length} из {autoPayments.length}</div>
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
                {showAdvancedFilters ? "Скрыть детали" : "Назначение и сумма"}
                {advancedFilterCount > 0 ? ` · ${advancedFilterCount}` : null}
              </Button>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="autopayment-search" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Поиск
              </Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="autopayment-search"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Описание, номер, кошелек или статья"
                  className="h-11 rounded-xl bg-background/70 pl-10"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Тип правила</Label>
              <div className="flex flex-wrap gap-2">
                <Button variant={typeFilter === "all" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("all")}>
                  Все
                </Button>
                <Button variant={typeFilter === "transfer" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("transfer")}>
                  Переводы
                </Button>
                <Button variant={typeFilter === "expense" ? "default" : "outline"} size="sm" onClick={() => setTypeFilter("expense")}>
                  Расходы
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="autopayment-wallet-from" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Откуда
              </Label>
              <Select value={walletFromId} onValueChange={setWalletFromId}>
                <SelectTrigger id="autopayment-wallet-from" className="h-11 rounded-xl bg-background/70 px-3.5">
                  <SelectValue placeholder="Все источники" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all-wallets-from">Все источники</SelectItem>
                  {wallets.map((wallet) => (
                    <SelectItem key={wallet.id} value={wallet.id}>
                      {wallet.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {showAdvancedFilters ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="space-y-2">
                <Label htmlFor="autopayment-wallet-to" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Куда
                </Label>
                <Select value={walletToId} onValueChange={setWalletToId}>
                  <SelectTrigger id="autopayment-wallet-to" className="h-11 rounded-xl bg-background/70 px-3.5">
                    <SelectValue placeholder="Все назначения" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all-wallets-to">Все назначения</SelectItem>
                    {wallets.map((wallet) => (
                      <SelectItem key={wallet.id} value={wallet.id}>
                        {wallet.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="autopayment-category" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Статья расхода
                </Label>
                <Select value={categoryId} onValueChange={setCategoryId}>
                  <SelectTrigger id="autopayment-category" className="h-11 rounded-xl bg-background/70 px-3.5">
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

              <div className="space-y-2">
                <Label htmlFor="autopayment-amount-min" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма от
                </Label>
                <Input
                  id="autopayment-amount-min"
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
                <Label htmlFor="autopayment-amount-max" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма до
                </Label>
                <Input
                  id="autopayment-amount-max"
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

      {filteredAutoPayments.length === 0 ? (
        <EmptyState
          icon={CalendarRange}
          title={autoPayments.length === 0 ? "Автоплатежей пока нет" : "Автоплатежи не найдены"}
          description={
            autoPayments.length === 0
              ? "Создай первое правило, чтобы вынести повторяющиеся движения денег в отдельный управляемый слой."
              : "По текущим фильтрам ничего не найдено. Ослабь ограничения или очисти поиск."
          }
          action={
            autoPayments.length === 0 ? (
              <Button asChild>
                <Link href="/auto-payments/new">Создать автоплатеж</Link>
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
            <div className="hidden grid-cols-[160px_120px_minmax(0,1.2fr)_130px_150px_124px] gap-4 border-b border-border/70 px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground lg:grid">
              <div>Сумма</div>
              <div>Тип</div>
              <div>Маршрут</div>
              <div>Интервал</div>
              <div>Следующее</div>
              <div className="text-right">Действия</div>
            </div>

            <div className="divide-y divide-border/60">
              {filteredAutoPayments.map((autoPayment) => {
                const daysUntil = getDaysUntil(autoPayment.date_start)
                const isOverdue = daysUntil !== null && daysUntil < 0
                const isSoon = daysUntil !== null && daysUntil >= 0 && daysUntil <= 7
                const targetLabel = autoPayment.is_transfer
                  ? autoPayment.wallet_to
                    ? walletMap[autoPayment.wallet_to] || "Неизвестный кошелек"
                    : "Не указано"
                  : autoPayment.cash_flow_item
                    ? categoryMap[autoPayment.cash_flow_item] || "Неизвестная статья"
                    : "Не указано"

                return (
                  <div key={autoPayment.id} className="px-4 py-4 lg:grid lg:grid-cols-[160px_120px_minmax(0,1.2fr)_130px_150px_124px] lg:items-center lg:gap-4 lg:px-5 lg:py-3">
                    <div className="text-lg font-semibold tracking-[-0.03em] text-foreground">{formatCurrency(autoPayment.amount)}</div>

                    <div className="mt-2 flex flex-wrap gap-2 lg:mt-0">
                      <Badge variant={autoPayment.is_transfer ? "outline" : "secondary"}>
                        {autoPayment.is_transfer ? "Перевод" : "Списание"}
                      </Badge>
                      {isOverdue ? <Badge variant="destructive">Просрочен</Badge> : null}
                      {!isOverdue && isSoon ? <Badge variant="outline">Скоро</Badge> : null}
                    </div>

                    <div className="mt-3 min-w-0 lg:mt-0">
                      <div className="truncate text-sm font-medium text-foreground">
                        {walletMap[autoPayment.wallet_from] || "Неизвестный кошелек"}
                        {" → "}
                        {targetLabel}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        {autoPayment.number ? <span>№ {autoPayment.number}</span> : null}
                        {autoPayment.description ? <span className="truncate">{autoPayment.description}</span> : null}
                      </div>
                    </div>

                    <div className="mt-3 text-sm text-muted-foreground lg:mt-0">
                      {autoPayment.amount_month != null ? `${autoPayment.amount_month} мес. в графике` : "Не задан"}
                    </div>

                    <div className="mt-3 space-y-1 text-sm text-muted-foreground lg:mt-0">
                      <div>{autoPayment.date_start ? formatDate(autoPayment.date_start) : "Без даты"}</div>
                      <div>
                        {daysUntil === null
                          ? "Не определено"
                          : isOverdue
                            ? `${Math.abs(daysUntil)} дн. назад`
                            : `Через ${daysUntil} дн.`}
                      </div>
                    </div>

                    <div className="mt-4 flex justify-end gap-1 lg:mt-0">
                      <Button asChild variant="ghost" size="icon">
                        <Link href={`/auto-payments/${autoPayment.id}/edit`} aria-label="Редактировать" title="Редактировать">
                          <PencilLine className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button asChild variant="ghost" size="icon">
                        <Link href={getAutoPaymentDuplicateHref(autoPayment)} aria-label="Дублировать" title="Дублировать">
                          <Copy className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(autoPayment.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
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
