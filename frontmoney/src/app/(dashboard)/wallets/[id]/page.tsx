"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { ArrowDownRight, ArrowUpRight, PencilLine, Wallet2 } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { WalletService, type WalletRecentOperation } from "@/services/wallet-service"

export default function WalletDetailPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const walletQuery = useQuery({
    queryKey: ["wallet", idParam],
    enabled: Boolean(idParam),
    queryFn: async () => {
      const [wallet, summary] = await Promise.all([
        WalletService.getWallet(idParam as string),
        WalletService.getWalletSummary(idParam as string),
      ])

      return { wallet, summary }
    },
  })

  if (walletQuery.isLoading) {
    return <FullPageLoader label="Загружаем карточку кошелька..." />
  }

  if (walletQuery.isError || !walletQuery.data) {
    return (
      <EmptyState
        icon={Wallet2}
        title="Не удалось открыть кошелек"
        description="Данные по кошельку или его операциям не загрузились. Попробуй обновить страницу или вернуться к списку."
        action={
          <Button asChild>
            <Link href="/wallets">Вернуться к кошелькам</Link>
          </Button>
        }
      />
    )
  }

  const wallet = walletQuery.data.wallet
  const summary = walletQuery.data.summary

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Wallet detail"
        title={wallet.name}
        description="Кошелек как рабочая единица: баланс, общий поток денег, статус видимости и последняя активность."
        actions={
          <>
            <Button asChild variant="outline">
              <Link href="/wallets">К списку</Link>
            </Button>
            <Button asChild>
              <Link href={`/wallets/${wallet.id}/edit`}>
                <PencilLine className="h-4 w-4" />
                Редактировать
              </Link>
            </Button>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Текущий баланс" value={formatCurrency(summary.balance)} hint="По данным backend summary endpoint" icon={Wallet2} />
        <StatCard label="Всего приходов" value={formatCurrency(summary.income_total)} hint="Сумма всех приходов по этому кошельку" icon={ArrowUpRight} tone="positive" />
        <StatCard label="Всего расходов" value={formatCurrency(summary.expense_total)} hint="Сумма всех расходов по этому кошельку" icon={ArrowDownRight} tone="danger" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <Card>
          <CardHeader>
            <CardTitle>Контекст кошелька</CardTitle>
            <CardDescription>Основные атрибуты и место кошелька в системе.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex items-center gap-2">
              {wallet.hidden ? <Badge variant="outline">Hidden</Badge> : <Badge variant="default">Active</Badge>}
              {wallet.code ? <Badge variant="secondary">{wallet.code}</Badge> : null}
            </div>

            <div className="grid gap-4 rounded-[24px] border border-border/60 bg-background/70 p-5">
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Название</div>
                <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{wallet.name}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Создан</div>
                <div className="mt-2 text-sm text-foreground">{formatDate(wallet.created_at)}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Последнее обновление</div>
                <div className="mt-2 text-sm text-foreground">{formatDate(wallet.updated_at)}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Режим отображения</div>
                <div className="mt-2 text-sm text-foreground">
                  {wallet.hidden ? "Скрыт из основного списка, но остается рабочим." : "Виден в основном наборе кошельков."}
                </div>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Button asChild variant="outline">
                <Link href="/receipts/new">Добавить приход</Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/expenditures/new">Добавить расход</Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Последние операции</CardTitle>
            <CardDescription>Последние 10 движений по этому кошельку.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {summary.recent_operations.length > 0 ? (
              summary.recent_operations.map((operation: WalletRecentOperation) => (
                <div key={`${operation.kind}-${operation.id}`} className="flex items-start justify-between gap-4 rounded-[22px] border border-border/60 bg-background/70 px-4 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge variant={operation.kind === "receipt" ? "success" : "outline"}>
                        {operation.kind === "receipt" ? "Income" : "Expense"}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{formatDate(operation.date)}</span>
                    </div>
                    <div className="mt-2 text-sm font-medium text-foreground">
                      {operation.description || "Без описания"}
                    </div>
                  </div>
                  <div className={operation.kind === "receipt" ? "text-right text-emerald-600 dark:text-emerald-300" : "text-right text-rose-600 dark:text-rose-300"}>
                    <div className="text-sm font-semibold">
                      {operation.kind === "receipt" ? "+" : "-"}
                      {formatCurrency(operation.amount)}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-[22px] border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
                По этому кошельку пока нет операций. Используй кнопки выше, чтобы создать первый приход или расход.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
