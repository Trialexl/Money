"use client"

import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { useDeferredValue, useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowRightLeft, Copy, PencilLine, Search, SlidersHorizontal, Trash2, Wallet2, X } from "lucide-react"

import { CatalogPaginationControls } from "@/components/shared/catalog-pagination-controls"
import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { useActiveWalletsQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { buildReturnToHref, withReturnToHref } from "@/lib/return-navigation"
import { cn } from "@/lib/utils"
import { PageSizeOption, TransferService } from "@/services/financial-operations-service"

function getMonthStart(date = new Date()) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function getTransferDuplicateHref(transfer: Awaited<ReturnType<typeof TransferService.getTransfers>>[number]) {
  const params = new URLSearchParams({ duplicate: transfer.id })

  if (transfer.wallet_from) {
    params.set("wallet_from", transfer.wallet_from)
  }

  if (transfer.wallet_to) {
    params.set("wallet_to", transfer.wallet_to)
  }

  return `/transfers/new?${params.toString()}`
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

export default function TransferCatalog() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const didMountFilterReset = useRef(false)
  const [searchTerm, setSearchTerm] = useState(() => searchParams.get("search") || "")
  const [dateFrom, setDateFrom] = useState(() => searchParams.get("date_from") || "")
  const [dateTo, setDateTo] = useState(() => searchParams.get("date_to") || "")
  const [walletFromId, setWalletFromId] = useState(() => searchParams.get("wallet_from") || "all-wallets-from")
  const [walletToId, setWalletToId] = useState(() => searchParams.get("wallet_to") || "all-wallets-to")
  const [amountMin, setAmountMin] = useState(() => searchParams.get("amount_min") || "")
  const [amountMax, setAmountMax] = useState(() => searchParams.get("amount_max") || "")
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [page, setPage] = useState(() => parsePage(searchParams.get("page")))
  const [pageSize, setPageSize] = useState<PageSizeOption>(() => parsePageSize(searchParams.get("page_size")))
  const deferredSearch = useDeferredValue(searchTerm)
  const normalizedSearch = deferredSearch.trim()
  const walletsQuery = useActiveWalletsQuery()
  const highlightedTransferId = searchParams.get("highlight") || ""
  const returnToHref = buildReturnToHref(pathname, searchParams)
  const createHref = withReturnToHref("/transfers/new", returnToHref)

  useEffect(() => {
    if (!didMountFilterReset.current) {
      didMountFilterReset.current = true
      return
    }

    setPage(1)
  }, [normalizedSearch, dateFrom, dateTo, walletFromId, walletToId, amountMin, amountMax])

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

    if (walletFromId !== "all-wallets-from") {
      params.set("wallet_from", walletFromId)
    }

    if (walletToId !== "all-wallets-to") {
      params.set("wallet_to", walletToId)
    }

    if (amountMin) {
      params.set("amount_min", amountMin)
    }

    if (amountMax) {
      params.set("amount_max", amountMax)
    }

    if (page > 1) {
      params.set("page", String(page))
    }

    if (pageSize !== 20) {
      params.set("page_size", String(pageSize))
    }

    if (highlightedTransferId) {
      params.set("highlight", highlightedTransferId)
    }

    const nextSearch = params.toString()
    if (searchParams.toString() !== nextSearch) {
      router.replace(nextSearch ? `/transfers?${nextSearch}` : "/transfers", { scroll: false })
    }
  }, [
    amountMax,
    amountMin,
    dateFrom,
    dateTo,
    highlightedTransferId,
    normalizedSearch,
    page,
    pageSize,
    router,
    searchParams,
    walletFromId,
    walletToId,
  ])

  const transfersQuery = useQuery({
    queryKey: [
      "transfers",
      {
        search: normalizedSearch,
        dateFrom,
        dateTo,
        walletFromId,
        walletToId,
        amountMin,
        amountMax,
        page,
        pageSize,
      },
    ],
    queryFn: () =>
      TransferService.getTransfersPage({
        search: normalizedSearch || undefined,
        dateFrom: dateFrom || undefined,
        dateTo: dateTo || undefined,
        walletFrom: walletFromId !== "all-wallets-from" ? walletFromId : undefined,
        walletTo: walletToId !== "all-wallets-to" ? walletToId : undefined,
        amountMin: amountMin || undefined,
        amountMax: amountMax || undefined,
        page,
        pageSize,
      }),
    placeholderData: (previousData) => previousData,
  })
  const pageCount = Math.max(transfersQuery.data?.totalPages ?? 1, 1)

  const deleteMutation = useMutation({
    mutationFn: (transferId: string) => TransferService.deleteTransfer(transferId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["transfers"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
        queryClient.invalidateQueries({ queryKey: ["wallets"] }),
      ])
    },
  })

  const handleResetFilters = () => {
    setSearchTerm("")
    setDateFrom("")
    setDateTo("")
    setWalletFromId("all-wallets-from")
    setWalletToId("all-wallets-to")
    setAmountMin("")
    setAmountMax("")
    setShowAdvancedFilters(false)
    setPage(1)
  }

  useEffect(() => {
    if (page > pageCount) {
      setPage(pageCount)
    }
  }, [page, pageCount])

  if ((transfersQuery.isLoading && !transfersQuery.data) || walletsQuery.isLoading) {
    return <FullPageLoader label="Загружаем переводы..." />
  }

  if (transfersQuery.isError || walletsQuery.isError || !transfersQuery.data) {
    return (
      <EmptyState
        icon={ArrowRightLeft}
        title="Не удалось загрузить переводы"
        description="Лента внутренних переводов сейчас недоступна. Проверь backend API и попробуй снова."
        action={<Button onClick={() => transfersQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const transfersPage = transfersQuery.data
  const transfers = transfersPage.results
  const totalTransfers = transfersPage.count
  const wallets = walletsQuery.data || []
  const walletMap = Object.fromEntries(wallets.map((wallet) => [wallet.id, wallet.name]))
  const totalAmount = transfers.reduce((sum, transfer) => sum + transfer.amount, 0)
  const monthStart = getMonthStart()
  const thisMonthCount = transfers.filter((transfer) => new Date(transfer.date) >= monthStart).length
  const uniqueRoutes = new Set(transfers.map((transfer) => `${transfer.wallet_from}:${transfer.wallet_to}`)).size
  const uniqueWallets = new Set(
    transfers.reduce<string[]>((accumulator, transfer) => {
      accumulator.push(transfer.wallet_from, transfer.wallet_to)
      return accumulator
    }, [])
  ).size
  const hasActiveFilters =
    Boolean(searchTerm.trim() || dateFrom || dateTo || amountMin || amountMax) ||
    walletFromId !== "all-wallets-from" ||
    walletToId !== "all-wallets-to"
  const activeFilterLabels = [
    searchTerm.trim() ? `Поиск: ${searchTerm.trim()}` : null,
    walletFromId !== "all-wallets-from" ? `Из: ${walletMap[walletFromId] || "кошелька"}` : null,
    walletToId !== "all-wallets-to" ? `В: ${walletMap[walletToId] || "кошелька"}` : null,
    dateFrom || dateTo ? `Период: ${dateFrom || "..."} - ${dateTo || "..."}` : null,
    amountMin || amountMax ? `Сумма: ${amountMin || "0"} - ${amountMax || "..."}` : null,
  ].filter(Boolean) as string[]
  const advancedFilterCount = [Boolean(dateFrom), Boolean(dateTo), Boolean(amountMin), Boolean(amountMax)].filter(Boolean).length

  const handleDelete = async (transferId: string) => {
    setActionError(null)

    if (!window.confirm("Удалить этот перевод? На фронте действие необратимо.")) {
      return
    }

    try {
      await deleteMutation.mutateAsync(transferId)
    } catch (error) {
      setActionError((error as any)?.response?.data?.detail || "Не удалось удалить перевод. Попробуй еще раз.")
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader compact title="Переводы" />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Сумма на экране" value={formatCurrency(totalAmount)} hint="Текущая страница" icon={ArrowRightLeft} variant="compact" />
        <StatCard
          label="Переводов на странице"
          value={String(transfers.length)}
          hint={`Страница ${page}${thisMonthCount > 0 ? ` · ${thisMonthCount} в текущем месяце` : ""}`}
          icon={Wallet2}
          variant="compact"
        />
        <StatCard label="Маршрутов" value={String(uniqueRoutes)} hint="На текущей странице" icon={ArrowRightLeft} tone={uniqueRoutes > 0 ? "positive" : "neutral"} variant="compact" />
        <StatCard label="Кошельков в движении" value={String(uniqueWallets)} hint="На текущей странице" icon={Wallet2} variant="compact" />
      </div>

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <div className="uppercase tracking-[0.16em]">Найдено {totalTransfers}, показано {transfers.length}</div>
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
              <Label htmlFor="transfer-search" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Поиск
              </Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="transfer-search"
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Описание, номер или название кошелька"
                  className="h-11 rounded-xl bg-background/70 pl-10"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="transfer-wallet-from" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Откуда
              </Label>
              <Select value={walletFromId} onValueChange={setWalletFromId}>
                <SelectTrigger id="transfer-wallet-from" className="h-11 rounded-xl bg-background/70 px-3.5">
                  <SelectValue placeholder="Все кошельки" />
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
            <div className="space-y-2">
              <Label htmlFor="transfer-wallet-to" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                Куда
              </Label>
              <Select value={walletToId} onValueChange={setWalletToId}>
                <SelectTrigger id="transfer-wallet-to" className="h-11 rounded-xl bg-background/70 px-3.5">
                  <SelectValue placeholder="Все кошельки" />
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
          </div>

          {showAdvancedFilters ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div className="space-y-2">
                <Label htmlFor="transfer-date-from" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Дата с
                </Label>
                <Input id="transfer-date-from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="h-11 rounded-xl bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="transfer-date-to" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Дата по
                </Label>
                <Input id="transfer-date-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="h-11 rounded-xl bg-background/70" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="transfer-amount-min" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма от
                </Label>
                <Input
                  id="transfer-amount-min"
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
                <Label htmlFor="transfer-amount-max" className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                  Сумма до
                </Label>
                <Input
                  id="transfer-amount-max"
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

      {transfers.length === 0 ? (
        <EmptyState
          icon={ArrowRightLeft}
          title={hasActiveFilters ? "Переводы не найдены" : "Переводов пока нет"}
          description={
            hasActiveFilters
              ? "По текущим фильтрам ничего не найдено. Ослабь ограничения или очисти форму поиска."
              : "Добавь первый перевод, чтобы контролировать внутренние перемещения между кошельками."
          }
          action={
            !hasActiveFilters ? (
              <Button asChild>
                <Link href={createHref}>Создать перевод</Link>
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
              <div>
                <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">Журнал переводов</div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  Плотный реестр для быстрой сверки маршрутов между кошельками, дат и сумм.
                </div>
              </div>
              <Badge variant="outline">{transfers.length} строк</Badge>
            </div>

            <div className="divide-y divide-border/60 md:hidden">
              {transfers.map((transfer) => {
                const isHighlighted = highlightedTransferId === transfer.id

                return (
                  <div
                    key={transfer.id}
                    className={cn(
                      "space-y-4 px-5 py-4 transition-colors",
                      isHighlighted && "bg-primary/10 ring-1 ring-inset ring-primary/35"
                    )}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline">Перевод</Badge>
                        </div>
                        {transfer.description ? <div className="text-sm font-medium text-foreground">{transfer.description}</div> : null}
                        <div className="text-xs text-muted-foreground">
                          {transfer.number || "Без номера"} · {formatDate(transfer.date)}
                        </div>
                      </div>
                      <div className="text-right text-lg font-semibold tracking-[-0.03em] text-foreground">{formatCurrency(transfer.amount)}</div>
                    </div>

                    <div className="grid gap-3 rounded-[20px] border border-border/60 bg-background/70 p-4 text-sm">
                      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Откуда</div>
                          <div className="mt-1 text-foreground">{walletMap[transfer.wallet_from] || "Неизвестный кошелек"}</div>
                        </div>
                        <ArrowRightLeft className="h-4 w-4 text-primary" />
                        <div>
                          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Куда</div>
                          <div className="mt-1 text-foreground">{walletMap[transfer.wallet_to] || "Неизвестный кошелек"}</div>
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-1">
                      <Button asChild variant="ghost" size="icon">
                        <Link
                          href={withReturnToHref(`/transfers/${transfer.id}/edit`, returnToHref)}
                          aria-label="Редактировать"
                          title="Редактировать"
                        >
                          <PencilLine className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button asChild variant="ghost" size="icon">
                        <Link
                          href={withReturnToHref(getTransferDuplicateHref(transfer), returnToHref)}
                          aria-label="Дублировать"
                          title="Дублировать"
                        >
                          <Copy className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(transfer.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
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
                    <th className="px-6 py-4 font-medium">Перевод</th>
                    <th className="px-4 py-4 font-medium">Дата</th>
                    <th className="px-4 py-4 font-medium">Маршрут</th>
                    <th className="px-4 py-4 text-right font-medium">Сумма</th>
                    <th className="px-4 py-4 font-medium">Статус</th>
                    <th className="px-6 py-4 text-right font-medium">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {transfers.map((transfer) => {
                    const isHighlighted = highlightedTransferId === transfer.id

                    return (
                      <tr
                        key={transfer.id}
                        className={cn(
                          "border-b border-border/60 align-top transition-colors last:border-b-0",
                          isHighlighted && "bg-primary/10 ring-1 ring-inset ring-primary/35"
                        )}
                      >
                        <td className="px-6 py-4">
                          <div className="max-w-[280px]">
                            {transfer.description ? <div className="text-sm font-medium text-foreground">{transfer.description}</div> : null}
                            <div className="mt-1 text-xs text-muted-foreground">{transfer.number || "Без номера"}</div>
                          </div>
                        </td>
                        <td className="px-4 py-4 text-sm text-foreground">{formatDate(transfer.date)}</td>
                        <td className="px-4 py-4">
                          <div className="flex items-center gap-3 text-sm">
                            <span className="text-foreground">{walletMap[transfer.wallet_from] || "Неизвестный кошелек"}</span>
                            <ArrowRightLeft className="h-4 w-4 text-primary" />
                            <span className="text-foreground">{walletMap[transfer.wallet_to] || "Неизвестный кошелек"}</span>
                          </div>
                        </td>
                        <td className="px-4 py-4 text-right text-sm font-semibold text-foreground">{formatCurrency(transfer.amount)}</td>
                        <td className="px-4 py-4">
                          <Badge variant="outline">Перевод</Badge>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex justify-end gap-1">
                            <Button asChild variant="ghost" size="icon">
                              <Link
                                href={withReturnToHref(`/transfers/${transfer.id}/edit`, returnToHref)}
                                aria-label="Редактировать"
                                title="Редактировать"
                              >
                                <PencilLine className="h-4 w-4" />
                              </Link>
                            </Button>
                            <Button asChild variant="ghost" size="icon">
                              <Link
                                href={withReturnToHref(getTransferDuplicateHref(transfer), returnToHref)}
                                aria-label="Дублировать"
                                title="Дублировать"
                              >
                                <Copy className="h-4 w-4" />
                              </Link>
                            </Button>
                            <Button variant="ghost" size="icon" onClick={() => handleDelete(transfer.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
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
              totalCount={totalTransfers}
              currentCount={transfers.length}
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
