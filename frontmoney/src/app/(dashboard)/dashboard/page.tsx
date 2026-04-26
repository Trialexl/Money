"use client"

import Link from "next/link"
import { useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import * as Popover from "@radix-ui/react-popover"
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format as formatDateFns,
  isAfter,
  isSameDay,
  isSameMonth,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns"
import { ru } from "date-fns/locale"
import {
  ArrowDownRight,
  ArrowRightLeft,
  ArrowUpRight,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Copy,
  Eye,
  EyeOff,
  PencilLine,
  ReceiptText,
  Wallet2,
} from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { formatCurrency, formatDate, formatDateForInput } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import {
  DashboardService,
  type DashboardBudgetExpenseBreakdown,
  type DashboardBudgetExpenseItem,
  type DashboardRecentActivity,
} from "@/services/dashboard-service"

type ActivityFilter = "all" | "receipt" | "expenditure" | "transfer"

export default function DashboardPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [showHiddenWallets, setShowHiddenWallets] = useState(false)
  const [isDatePickerOpen, setIsDatePickerOpen] = useState(false)
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("all")
  const [expandedBudgetItemId, setExpandedBudgetItemId] = useState<string | null>(null)
  const today = formatDateForInput()
  const selectedDate = searchParams.get("date") || today
  const selectedDashboardDate = new Date(`${selectedDate}T12:00:00`)
  const [visibleMonth, setVisibleMonth] = useState(startOfMonth(selectedDashboardDate))
  const todayDate = new Date(`${today}T12:00:00`)
  const calendarDays = eachDayOfInterval({
    start: startOfWeek(startOfMonth(visibleMonth), { weekStartsOn: 1 }),
    end: endOfWeek(endOfMonth(visibleMonth), { weekStartsOn: 1 }),
  })
  const weekdayLabels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
  const dashboardWeekdayLabel = formatDateFns(selectedDashboardDate, "ccc", { locale: ru }).replace(".", "")
  const dashboardDayLabel = formatDateFns(selectedDashboardDate, "d MMMM", { locale: ru })
  const dashboardCompactDateLabel = formatDateFns(selectedDashboardDate, "d MMM", { locale: ru })

  const dashboardQuery = useQuery({
    queryKey: ["dashboard-overview", { selectedDate, showHiddenWallets }],
    queryFn: async () => {
      const [overview, recentActivity] = await Promise.all([
        DashboardService.getOverview({ date: selectedDate, hideHiddenWallets: !showHiddenWallets }),
        DashboardService.getRecentActivity({
          date: selectedDate,
          hideHiddenWallets: !showHiddenWallets,
          limit: 20,
        }),
      ])

      return {
        overview,
        recentActivity,
      }
    },
    staleTime: 60_000,
  })

  const budgetBreakdownQuery = useQuery({
    queryKey: ["dashboard-budget-expense-breakdown", { selectedDate, cashFlowItemId: expandedBudgetItemId }],
    queryFn: async () =>
      DashboardService.getBudgetExpenseBreakdown({
        date: selectedDate,
        cashFlowItemId: expandedBudgetItemId!,
      }),
    enabled: Boolean(expandedBudgetItemId),
    staleTime: 60_000,
  })

  if (dashboardQuery.isLoading) {
    return <FullPageLoader label="Собираем обзор денег..." />
  }

  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <EmptyState
        icon={ReceiptText}
        title="Обзор денег пока не загрузился"
        description="Не удалось собрать данные по кошелькам и операциям. Проверь API и повтори попытку."
        action={<Button onClick={() => dashboardQuery.refetch()}>Повторить загрузку</Button>}
      />
    )
  }

  const overview = dashboardQuery.data.overview
  const allRecentActivity: DashboardRecentActivity[] = dashboardQuery.data.recentActivity

  const currentMonthIncome = overview.month_comparison.current_month.income
  const currentMonthExpense = overview.month_comparison.current_month.expense
  const currentMonthNet = currentMonthIncome - currentMonthExpense
  const previousMonthNet =
    overview.month_comparison.previous_month.income - overview.month_comparison.previous_month.expense
  const freeCash = overview.cash_with_budget
  const sortedWallets = [...overview.wallets].sort((left, right) => right.balance - left.balance)
  const negativeWallets = sortedWallets.filter((wallet) => wallet.balance < 0)
  const budgetAlerts = [...overview.budget_expense.items]
    .filter((item) => item.overrun > 0)
    .sort((left, right) => right.overrun - left.overrun)
    .slice(0, 5)
  const expandedBudgetBreakdown: DashboardBudgetExpenseBreakdown | null =
    expandedBudgetItemId && budgetBreakdownQuery.data?.cash_flow_item_id === expandedBudgetItemId
      ? budgetBreakdownQuery.data
      : null

  const recentActivity = allRecentActivity.filter((item) => activityFilter === "all" || item.kind === activityFilter)

  const handleSelectDashboardDate = (value: Date) => {
    const nextDate = formatDateForInput(value)
    const params = new URLSearchParams(searchParams.toString())
    if (nextDate === today) {
      params.delete("date")
    } else {
      params.set("date", nextDate)
    }
    const query = params.toString()
    router.replace(query ? `/dashboard?${query}` : "/dashboard", { scroll: false })
    setVisibleMonth(startOfMonth(value))
    setIsDatePickerOpen(false)
  }

  const handleToggleBudgetBreakdown = (cashFlowItemId: string) => {
    setExpandedBudgetItemId((current) => (current === cashFlowItemId ? null : cashFlowItemId))
  }

  const formatBudgetDetailType = (documentType?: string | null) => {
    if (!documentType) {
      return null
    }

    return (
      {
        Budget: "План",
        Expenditure: "Расход",
        Receipt: "Приход",
        Transfer: "Перевод",
      }[documentType] ?? documentType
    )
  }

  const getActivityDuplicateHref = (operation: DashboardRecentActivity) => {
    const params = new URLSearchParams({ duplicate: operation.id })

    if (operation.kind === "receipt" || operation.kind === "expenditure") {
      if (operation.wallet) {
        params.set("wallet", operation.wallet)
      }

      if (operation.cash_flow_item) {
        params.set("cash_flow_item", operation.cash_flow_item)
      }
    }

    if (operation.kind === "transfer") {
      if (operation.wallet_from) {
        params.set("wallet_from", operation.wallet_from)
      }

      if (operation.wallet_to) {
        params.set("wallet_to", operation.wallet_to)
      }
    }

    const path =
      operation.kind === "receipt"
        ? "/receipts/new"
        : operation.kind === "expenditure"
          ? "/expenditures/new"
          : "/transfers/new"

    return `${path}?${params.toString()}`
  }

  return (
    <div className="space-y-5">
      <section>
        <div className="rounded-[20px] border border-border/60 bg-card/85 p-3 shadow-soft sm:rounded-[24px] sm:p-4">
          <div className="grid grid-cols-[minmax(0,1fr)_116px] items-start gap-3 md:grid-cols-[minmax(0,1fr)_148px]">
            <div className="min-w-0 flex-1 space-y-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Общий остаток</div>
                  <div className="mt-1.5 text-xl font-semibold tracking-[-0.04em] text-foreground sm:mt-2 sm:text-2xl">
                    {formatCurrency(overview.wallet_total)}
                  </div>
                </div>

                <div className="border-t border-border/60 pt-3">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Свободный остаток</div>
                  <div
                    className={
                      freeCash >= 0
                        ? "mt-1 text-lg font-semibold tracking-[-0.04em] text-emerald-600 dark:text-emerald-300 sm:mt-1.5 sm:text-xl"
                        : "mt-1 text-lg font-semibold tracking-[-0.04em] text-rose-600 dark:text-rose-300 sm:mt-1.5 sm:text-xl"
                    }
                  >
                    {formatCurrency(freeCash)}
                  </div>
                  <div className="mt-1 text-xs leading-4 text-muted-foreground">С учетом бюджета</div>
                </div>

                <div className="border-t border-border/60 pt-3">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Результат месяца</div>
                  <div
                    className={
                      currentMonthNet >= 0
                        ? "mt-1 text-lg font-semibold tracking-[-0.04em] text-emerald-600 dark:text-emerald-300 sm:mt-1.5 sm:text-xl"
                        : "mt-1 text-lg font-semibold tracking-[-0.04em] text-rose-600 dark:text-rose-300 sm:mt-1.5 sm:text-xl"
                    }
                  >
                    {formatCurrency(currentMonthNet)}
                  </div>
                  <div className="mt-1 text-xs leading-4 text-muted-foreground">Прошлый: {formatCurrency(previousMonthNet)}</div>
                </div>
            </div>

            <div className="flex shrink-0 flex-col gap-2.5 md:gap-3">
              <Popover.Root
                open={isDatePickerOpen}
                onOpenChange={(open) => {
                  setIsDatePickerOpen(open)
                  if (open) {
                    setVisibleMonth(startOfMonth(selectedDashboardDate))
                  }
                }}
              >
                <Popover.Trigger asChild>
                  <button
                    type="button"
                    className="flex min-h-[84px] w-full flex-col items-center justify-between rounded-[16px] border border-border/70 bg-background/75 px-2.5 py-2.5 text-center transition-colors hover:border-primary/25 hover:bg-card md:h-[120px] md:items-start md:rounded-[24px] md:p-4 md:text-left"
                    aria-label="Выбрать дату обзора"
                  >
                    <CalendarDays className="h-4 w-4 shrink-0 text-primary md:h-5 md:w-5" />
                    <div className="min-w-0 w-full">
                      <div className="truncate text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground capitalize md:text-[11px] md:tracking-[0.14em]">
                        {dashboardWeekdayLabel}
                      </div>
                      <div className="mt-1 text-sm font-semibold leading-5 tracking-[-0.03em] text-foreground capitalize md:mt-2 md:text-lg">
                        <span className="md:hidden">{dashboardCompactDateLabel}</span>
                        <span className="hidden md:inline">{dashboardDayLabel}</span>
                      </div>
                    </div>
                  </button>
                </Popover.Trigger>
                <Popover.Portal>
                  <Popover.Content
                    align="end"
                    sideOffset={10}
                    className="z-50 w-[320px] rounded-[28px] border border-border/70 bg-background/97 p-4 shadow-[0_30px_80px_-40px_rgba(15,23,42,0.6)] backdrop-blur-xl"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <button
                        type="button"
                        className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/70 bg-card/80 transition-colors hover:bg-card"
                        onClick={() => setVisibleMonth((current) => subMonths(current, 1))}
                        aria-label="Предыдущий месяц"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </button>

                      <div className="text-sm font-semibold tracking-[-0.02em] text-foreground capitalize">
                        {formatDateFns(visibleMonth, "LLLL yyyy", { locale: ru })}
                      </div>

                      <button
                        type="button"
                        className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/70 bg-card/80 transition-colors hover:bg-card disabled:cursor-not-allowed disabled:opacity-40"
                        onClick={() => setVisibleMonth((current) => addMonths(current, 1))}
                        disabled={isAfter(startOfMonth(addMonths(visibleMonth, 1)), startOfMonth(todayDate))}
                        aria-label="Следующий месяц"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>

                    <div className="mt-4 grid grid-cols-7 gap-1 text-center text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {weekdayLabels.map((label) => (
                        <div key={label} className="py-2">
                          {label}
                        </div>
                      ))}
                    </div>

                    <div className="grid grid-cols-7 gap-1">
                      {calendarDays.map((day) => {
                        const isSelected = isSameDay(day, selectedDashboardDate)
                        const isCurrentMonth = isSameMonth(day, visibleMonth)
                        const isFutureDay = isAfter(day, todayDate)

                        return (
                          <button
                            key={day.toISOString()}
                            type="button"
                            disabled={isFutureDay}
                            onClick={() => handleSelectDashboardDate(day)}
                            className={cn(
                              "flex h-10 items-center justify-center rounded-2xl text-sm font-medium transition-colors",
                              isSelected
                                ? "bg-primary text-primary-foreground shadow-[0_18px_35px_-18px_hsl(var(--primary)/0.8)]"
                                : isCurrentMonth
                                  ? "text-foreground hover:bg-card"
                                  : "text-muted-foreground/45 hover:bg-card/70",
                              isFutureDay && "cursor-not-allowed text-muted-foreground/35 hover:bg-transparent"
                            )}
                          >
                            {formatDateFns(day, "d")}
                          </button>
                        )
                      })}
                    </div>

                    <div className="mt-4 flex items-center justify-end gap-3 border-t border-border/60 pt-4">
                      {selectedDate !== today ? (
                        <Button size="sm" variant="outline" onClick={() => handleSelectDashboardDate(todayDate)}>
                          Сегодня
                        </Button>
                      ) : null}
                    </div>
                  </Popover.Content>
                </Popover.Portal>
              </Popover.Root>

              <div className="flex min-h-0 flex-1 flex-col justify-center rounded-[16px] border border-border/70 bg-background/75 px-3 py-2.5 text-center md:rounded-[24px] md:p-4 md:text-left">
                <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground md:text-[11px] md:tracking-[0.16em]">
                  Перерасход
                </div>
                <div
                  className={
                    overview.budget_expense.overrun_total > 0
                      ? "mt-1 text-lg font-semibold tracking-[-0.04em] text-rose-600 dark:text-rose-300 md:mt-2 md:text-2xl"
                      : "mt-1 text-lg font-semibold tracking-[-0.04em] text-foreground md:mt-2 md:text-2xl"
                  }
                >
                  {formatCurrency(overview.budget_expense.overrun_total)}
                </div>
                <div className="mt-1 text-[11px] leading-4 text-muted-foreground md:text-xs md:leading-5">
                  {budgetAlerts.length > 0 ? `${budgetAlerts.length} стат.` : "Без перерасхода"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {overview.wallets.length === 0 ? (
        <EmptyState
          icon={Wallet2}
          title="Пока нет ни одного кошелька"
          description="Начни со структуры учета. Создай первый кошелек, чтобы видеть остатки, операции и динамику."
          action={
            <Button asChild>
              <Link href="/wallets/new">Создать первый кошелек</Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_380px]">
            <div className="space-y-5">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between gap-3 border-b border-border/60 pb-4">
                  <CardTitle>Кошельки</CardTitle>
                  <div className="flex shrink-0 items-center">
                    <Button
                      variant="outline"
                      size="icon"
                      onClick={() => setShowHiddenWallets((value) => !value)}
                      aria-label={showHiddenWallets ? "Скрыть скрытые кошельки" : "Показать скрытые кошельки"}
                      title={showHiddenWallets ? "Скрыть скрытые кошельки" : "Показать скрытые кошельки"}
                    >
                      {showHiddenWallets ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="max-h-[440px] overflow-y-auto">
                    <div className="grid grid-cols-[minmax(0,1.3fr)_160px] gap-3 border-b border-border/60 px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                      <div>Кошелек</div>
                      <div>Остаток</div>
                    </div>
                    {sortedWallets.map((wallet) => (
                      <Link
                        key={wallet.wallet_id}
                        href={`/wallets/${wallet.wallet_id}`}
                        className="grid grid-cols-[minmax(0,1.3fr)_160px] gap-3 border-b border-border/60 px-5 py-3 text-sm transition-colors hover:bg-background/60"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-medium text-foreground">{wallet.wallet_name}</div>
                        </div>
                        <div
                          className={
                            wallet.balance >= 0
                              ? "font-semibold text-emerald-600 dark:text-emerald-300"
                              : "font-semibold text-rose-600 dark:text-rose-300"
                          }
                        >
                          {formatCurrency(wallet.balance)}
                        </div>
                      </Link>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>

            <div>
              <Card>
                <CardHeader className="pb-4">
                  <CardTitle>Бюджет под контролем</CardTitle>
                  <CardDescription>Только то, что требует реакции.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-[20px] border border-border/60 bg-background/75 p-4">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-muted-foreground">План по доходам</span>
                      <span className="font-semibold text-foreground">
                        {formatCurrency(overview.budget_income.planned_total)}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-3 text-sm">
                      <span className="text-muted-foreground">Факт по доходам</span>
                      <span className="font-semibold text-foreground">
                        {formatCurrency(overview.budget_income.actual_total)}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-3 text-sm">
                      <span className="text-muted-foreground">Осталось по плану</span>
                      <span className="font-semibold text-foreground">
                        {formatCurrency(overview.budget_income.remaining_total)}
                      </span>
                    </div>
                  </div>

                  {budgetAlerts.length > 0 ? (
                    <div className="space-y-2">
                      {budgetAlerts.map((item: DashboardBudgetExpenseItem) => (
                        <div key={item.cash_flow_item_id} className="space-y-2">
                          <button
                            type="button"
                            onClick={() => handleToggleBudgetBreakdown(item.cash_flow_item_id)}
                            className={cn(
                              "flex w-full items-center justify-between gap-3 rounded-[20px] border border-border/60 bg-background/75 px-4 py-3 text-left transition-colors hover:bg-background",
                              expandedBudgetItemId === item.cash_flow_item_id && "border-primary/30 bg-background"
                            )}
                          >
                            <div className="min-w-0">
                              <div className="truncate text-sm font-medium text-foreground">{item.cash_flow_item_name}</div>
                              <div className="mt-1 text-xs text-muted-foreground">Нажми, чтобы увидеть расчет суммы</div>
                            </div>
                            <div className="text-right">
                              <div className="text-sm font-semibold text-rose-600 dark:text-rose-300">
                                {formatCurrency(item.overrun)}
                              </div>
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                {expandedBudgetItemId === item.cash_flow_item_id ? "Скрыть" : "Раскрыть"}
                              </div>
                            </div>
                          </button>

                          {expandedBudgetItemId === item.cash_flow_item_id ? (
                            <div className="rounded-[20px] border border-border/60 bg-card/70 p-4">
                              {budgetBreakdownQuery.isLoading ? (
                                <div className="text-sm text-muted-foreground">Собираем расшифровку статьи...</div>
                              ) : budgetBreakdownQuery.isError || !expandedBudgetBreakdown ? (
                                <div className="space-y-3">
                                  <div className="text-sm text-muted-foreground">
                                    Не удалось загрузить расшифровку суммы.
                                  </div>
                                  <Button size="sm" variant="outline" onClick={() => budgetBreakdownQuery.refetch()}>
                                    Повторить
                                  </Button>
                                </div>
                              ) : (
                                <div className="space-y-4">
                                  <div className="grid gap-2 sm:grid-cols-3">
                                    <div className="rounded-2xl border border-border/60 bg-background/75 p-3">
                                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                        План
                                      </div>
                                      <div className="mt-1 text-lg font-semibold text-foreground">
                                        {formatCurrency(expandedBudgetBreakdown.planned_total)}
                                      </div>
                                    </div>
                                    <div className="rounded-2xl border border-border/60 bg-background/75 p-3">
                                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                        Факт
                                      </div>
                                      <div className="mt-1 text-lg font-semibold text-foreground">
                                        {formatCurrency(expandedBudgetBreakdown.actual_total)}
                                      </div>
                                    </div>
                                    <div className="rounded-2xl border border-border/60 bg-background/75 p-3">
                                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                                        {expandedBudgetBreakdown.overrun > 0 ? "Перерасход" : "Остаток"}
                                      </div>
                                      <div
                                        className={cn(
                                          "mt-1 text-lg font-semibold",
                                          expandedBudgetBreakdown.overrun > 0
                                            ? "text-rose-600 dark:text-rose-300"
                                            : "text-emerald-600 dark:text-emerald-300"
                                        )}
                                      >
                                        {formatCurrency(
                                          expandedBudgetBreakdown.overrun > 0
                                            ? expandedBudgetBreakdown.overrun
                                            : expandedBudgetBreakdown.remaining
                                        )}
                                      </div>
                                    </div>
                                  </div>

                                  <div className="rounded-2xl border border-border/60 bg-background/60 p-3 text-sm text-muted-foreground">
                                    {expandedBudgetBreakdown.overrun > 0
                                      ? "Перерасход считается как факт минус план по выбранной статье на текущую дату."
                                      : "Остаток считается как план минус факт по выбранной статье на текущую дату."}
                                  </div>

                                  <div className="space-y-2">
                                    {expandedBudgetBreakdown.details.map((detail) => (
                                      <div
                                        key={`${detail.entry_type}-${detail.document_id ?? detail.period}-${detail.amount}`}
                                        className="flex items-start justify-between gap-3 rounded-2xl border border-border/60 bg-background/75 px-3 py-3"
                                      >
                                        <div className="min-w-0 space-y-1">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <Badge variant={detail.entry_type === "budget" ? "outline" : "destructive"}>
                                              {detail.entry_type === "budget" ? "План" : "Факт"}
                                            </Badge>
                                            {formatBudgetDetailType(detail.document_type) ? (
                                              <span className="text-xs text-muted-foreground">
                                                {formatBudgetDetailType(detail.document_type)}
                                              </span>
                                            ) : null}
                                          </div>
                                          <div className="text-sm text-foreground">{formatDate(detail.period)}</div>
                                        </div>
                                        <div className="text-sm font-semibold text-foreground">
                                          {formatCurrency(detail.amount)}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-[20px] border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
                      Сейчас явных перерасходов по бюджету нет.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          <Card>
            <CardHeader className="pb-4">
              <CardTitle>Последние документы</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Button variant={activityFilter === "all" ? "default" : "outline"} size="sm" onClick={() => setActivityFilter("all")}>
                  Все
                </Button>
                <Button variant={activityFilter === "receipt" ? "default" : "outline"} size="sm" onClick={() => setActivityFilter("receipt")}>
                  Приходы
                </Button>
                <Button variant={activityFilter === "expenditure" ? "default" : "outline"} size="sm" onClick={() => setActivityFilter("expenditure")}>
                  Расходы
                </Button>
                <Button variant={activityFilter === "transfer" ? "default" : "outline"} size="sm" onClick={() => setActivityFilter("transfer")}>
                  Переводы
                </Button>
              </div>
              {recentActivity.length > 0 ? (
                recentActivity.map((operation) => (
                  <div
                    key={`${operation.kind}-${operation.id}`}
                    className="flex items-start gap-3 rounded-[18px] border border-border/60 bg-background/75 px-3 py-3"
                  >
                    <Badge
                      className="shrink-0"
                      variant={operation.kind === "receipt" ? "success" : operation.kind === "transfer" ? "secondary" : "outline"}
                    >
                      {operation.kind === "receipt" ? "Приход" : operation.kind === "expenditure" ? "Расход" : "Перевод"}
                    </Badge>

                    <Link
                      href={
                        operation.kind === "receipt"
                          ? `/receipts/${operation.id}/edit`
                          : operation.kind === "expenditure"
                            ? `/expenditures/${operation.id}/edit`
                            : `/transfers/${operation.id}/edit`
                      }
                      className="min-w-0 flex-1 transition-colors hover:text-foreground/80"
                    >
                      <div className="truncate text-sm font-medium text-foreground">
                        {operation.kind === "transfer"
                          ? `${operation.wallet_from_name || "Без кошелька"} → ${operation.wallet_to_name || "Без кошелька"}`
                          : `${operation.wallet_name || "Без кошелька"} · ${operation.cash_flow_item_name || "Без статьи"}`}
                      </div>
                      <div className="mt-1 text-xs leading-4 text-muted-foreground">
                        {operation.description ? <div className="truncate">{operation.description}</div> : null}
                        <div>{formatDate(operation.date)}</div>
                      </div>
                    </Link>

                    <div className="flex shrink-0 items-start gap-1.5">
                      <div
                        className={
                          operation.kind === "receipt"
                            ? "pt-1 text-sm font-semibold text-emerald-600 dark:text-emerald-300"
                            : operation.kind === "expenditure"
                              ? "pt-1 text-sm font-semibold text-rose-600 dark:text-rose-300"
                              : "pt-1 text-sm font-semibold text-foreground"
                        }
                      >
                        {operation.kind === "receipt" ? "+" : operation.kind === "expenditure" ? "-" : ""}
                        {formatCurrency(operation.amount)}
                      </div>
                      <Button asChild variant="ghost" size="icon" className="h-8 w-8">
                        <Link
                          href={getActivityDuplicateHref(operation)}
                          aria-label="Копировать документ"
                          title="Копировать"
                        >
                          <Copy className="h-4 w-4" />
                        </Link>
                      </Button>
                      <Button asChild variant="ghost" size="icon" className="h-8 w-8">
                        <Link
                          href={
                            operation.kind === "receipt"
                              ? `/receipts/${operation.id}/edit`
                              : operation.kind === "expenditure"
                                ? `/expenditures/${operation.id}/edit`
                                : `/transfers/${operation.id}/edit`
                          }
                          aria-label="Редактировать документ"
                          title="Редактировать"
                        >
                          <PencilLine className="h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-[20px] border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
                  Операций пока нет. Создай первый приход или расход, чтобы увидеть движение денег.
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
