"use client"

import Link from "next/link"
import { useDeferredValue, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Copy, Eye, PencilLine, Plus, Trash2, Wallet2 } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { useWalletsWithBalancesQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { WalletService } from "@/services/wallet-service"

export default function WalletsPage() {
  const queryClient = useQueryClient()
  const [searchTerm, setSearchTerm] = useState("")
  const [showHidden, setShowHidden] = useState(false)
  const deferredSearchTerm = useDeferredValue(searchTerm)

  const walletsQuery = useWalletsWithBalancesQuery()

  const deleteMutation = useMutation({
    mutationFn: (walletId: string) => WalletService.deleteWallet(walletId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["wallets"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
      ])
    },
  })

  if (walletsQuery.isLoading) {
    return <FullPageLoader label="Загружаем кошельки..." />
  }

  if (walletsQuery.isError || !walletsQuery.data) {
    return (
      <EmptyState
        icon={Wallet2}
        title="Раздел кошельков пока недоступен"
        description="Не удалось получить список кошельков и их балансы. Проверь доступность backend API и попробуй снова."
        action={<Button onClick={() => walletsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const { wallets, balances } = walletsQuery.data
  const filteredWallets = wallets
    .filter((wallet) => (showHidden ? true : !wallet.hidden))
    .filter((wallet) => {
      if (!deferredSearchTerm.trim()) {
        return true
      }

      const haystack = `${wallet.name} ${wallet.code ?? ""}`.toLowerCase()
      return haystack.includes(deferredSearchTerm.toLowerCase())
    })
    .sort((left, right) => left.name.localeCompare(right.name, "ru"))

  const displayedBalance = filteredWallets.reduce((sum, wallet) => sum + (balances[wallet.id] ?? 0), 0)
  const hiddenCount = wallets.filter((wallet) => wallet.hidden).length

  const handleDelete = async (walletId: string) => {
    if (!window.confirm("Удалить этот кошелек? Операция необратима на уровне UI.")) {
      return
    }

    await deleteMutation.mutateAsync(walletId)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Справочники"
        title="Кошельки"
        description="Счета, карты и видимые остатки."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <StatCard label="Всего кошельков" value={String(wallets.length)} hint="С учетом скрытых" icon={Wallet2} variant="compact" />
        <StatCard label="Баланс на экране" value={formatCurrency(displayedBalance)} hint="По текущему фильтру" icon={Eye} variant="compact" />
        <StatCard label="Скрытые кошельки" value={String(hiddenCount)} hint="Не в ежедневном учете" icon={Trash2} tone={hiddenCount > 0 ? "danger" : "neutral"} variant="compact" />
      </div>

      <Card>
        <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div className="space-y-2">
            <Label htmlFor="wallet-search">Поиск</Label>
            <Input
              id="wallet-search"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Найти кошелек"
            />
          </div>
          <div className="flex items-center gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-2.5">
            <Switch id="hidden-wallets" checked={showHidden} onCheckedChange={setShowHidden} />
            <Label htmlFor="hidden-wallets" className="cursor-pointer">
              Показывать скрытые кошельки
            </Label>
          </div>
        </CardContent>
      </Card>

      {filteredWallets.length === 0 ? (
        <EmptyState
          icon={Wallet2}
          title="Ничего не найдено"
          description="По текущему поиску и фильтру кошельков нет. Попробуй очистить поиск или создать новую запись."
          action={
            <Button asChild variant="outline">
              <Link href="/wallets/new">Создать кошелек</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {filteredWallets.map((wallet) => (
            <Card key={wallet.id} className="overflow-hidden">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-2">
                      <h2 className="text-xl font-semibold tracking-[-0.04em]">{wallet.name}</h2>
                      {wallet.hidden ? <Badge variant="outline">Скрыт</Badge> : <Badge variant="default">Активный</Badge>}
                    </div>
                    {wallet.code ? <p className="text-xs text-muted-foreground">Код: {wallet.code}</p> : null}
                  </div>
                  <div className="text-right">
                    <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Баланс</div>
                    <div className="mt-1.5 text-xl font-semibold tracking-[-0.04em]">{formatCurrency(balances[wallet.id] ?? 0)}</div>
                  </div>
                </div>

                <div className="mt-4 grid gap-3 rounded-[18px] border border-border/60 bg-background/70 p-3 text-sm text-muted-foreground sm:grid-cols-2">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.16em]">Создан</div>
                    <div className="mt-1.5 text-foreground">{formatDate(wallet.created_at)}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.16em]">Видимость</div>
                    <div className="mt-1.5 text-foreground">{wallet.hidden ? "Скрыт в ежедневном учете" : "Показывается в основном списке"}</div>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-1">
                  <Button asChild size="icon" aria-label="Открыть" title="Открыть">
                    <Link href={`/wallets/${wallet.id}`}>
                      <Eye className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="ghost" size="icon" aria-label="Редактировать" title="Редактировать">
                    <Link href={`/wallets/${wallet.id}/edit`}>
                      <PencilLine className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button asChild variant="ghost" size="icon" aria-label="Дублировать" title="Дублировать">
                    <Link href={`/wallets/new?duplicate=${wallet.id}`}>
                      <Copy className="h-4 w-4" />
                    </Link>
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => handleDelete(wallet.id)} disabled={deleteMutation.isPending} aria-label="Удалить" title="Удалить">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
