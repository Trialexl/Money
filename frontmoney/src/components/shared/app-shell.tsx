"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useMemo, useState } from "react"
import {
  ArrowDownRight,
  ArrowRightLeft,
  ArrowUpRight,
  BarChart4,
  Bot,
  CalendarRange,
  Home,
  Layers3,
  LogOut,
  Menu,
  Plus,
  PieChart,
  Settings,
  Wallet,
  X,
  type LucideIcon
} from "lucide-react"

import { BrandMark } from "@/components/shared/brand-mark"
import { Button } from "@/components/ui/button"
import { ModeToggle } from "@/components/ui/mode-toggle"
import { getUserDisplayName, getUserSecondaryText } from "@/lib/user-profile"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth-store"

interface AppShellProps {
  children: React.ReactNode
}

interface NavigationItem {
  href: string
  label: string
  description: string
  icon: LucideIcon
}

interface NavigationSection {
  title: string
  items: NavigationItem[]
}

const frequentActions = [
  { href: "/expenditures/new", label: "Новый расход", icon: ArrowDownRight },
  { href: "/receipts/new", label: "Новый приход", icon: ArrowUpRight },
  { href: "/transfers/new", label: "Новый перевод", icon: ArrowRightLeft },
]

const navigationSections: NavigationSection[] = [
  {
    title: "Контроль",
    items: [
      { href: "/dashboard", label: "Оперативная страница", description: "Главный рабочий экран по остаткам, бюджету и свежим движениям", icon: Home },
      { href: "/reports", label: "Отчеты", description: "Аналитика структуры денег и детализация периода", icon: BarChart4 },
      { href: "/assistant", label: "Ассистент", description: "AI-ввод операций и Telegram-сценарии", icon: Bot },
    ],
  },
  {
    title: "Справочники",
    items: [
      { href: "/wallets", label: "Кошельки", description: "Счета, карты, наличные и остатки", icon: Wallet },
      { href: "/cash-flow-items", label: "Статьи", description: "Категории доходов, расходов и бюджетов", icon: PieChart },
      { href: "/projects", label: "Проекты", description: "Контекст для операций и планов", icon: Layers3 },
    ],
  },
  {
    title: "План и операции",
    items: [
      { href: "/receipts", label: "Приходы", description: "Журнал входящих операций", icon: ArrowUpRight },
      { href: "/expenditures", label: "Расходы", description: "Журнал трат и бюджетного контура", icon: ArrowDownRight },
      { href: "/transfers", label: "Переводы", description: "Перемещения между своими кошельками", icon: ArrowRightLeft },
      { href: "/budgets", label: "Бюджеты", description: "План, лимиты и исполнение", icon: CalendarRange },
      { href: "/auto-payments", label: "Автоплатежи", description: "Регулярные списания и автопереводы", icon: CalendarRange },
    ],
  },
]

const accountItems: NavigationItem[] = [
  { href: "/settings", label: "Настройки", description: "Профиль и параметры аккаунта", icon: Settings },
]

const topCreateActions: Record<string, { href: string; label: string }> = {
  "/receipts": { href: "/receipts/new", label: "Новый приход" },
  "/expenditures": { href: "/expenditures/new", label: "Новый расход" },
  "/transfers": { href: "/transfers/new", label: "Новый перевод" },
  "/budgets": { href: "/budgets/new", label: "Новый бюджет" },
  "/auto-payments": { href: "/auto-payments/new", label: "Новый автоплатеж" },
  "/wallets": { href: "/wallets/new", label: "Новый кошелек" },
  "/projects": { href: "/projects/new", label: "Новый проект" },
  "/cash-flow-items": { href: "/cash-flow-items/new", label: "Новая статья" },
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname()
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const { logout, user } = useAuthStore()

  const allItems = useMemo(() => [...navigationSections.flatMap((section) => section.items), ...accountItems], [])
  const currentItem =
    allItems.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`)) ?? allItems[0]
  const isDashboard = pathname === "/dashboard"
  const topCreateAction = topCreateActions[pathname]

  const handleLogout = async () => {
    await logout()
    window.location.href = "/auth/login"
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border/50 bg-background/76 backdrop-blur-xl">
        <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center justify-between gap-2 px-3 sm:px-5 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Link href="/dashboard" className="shrink-0">
              <>
                <BrandMark compact className="sm:hidden" />
                <BrandMark compact={false} className="hidden sm:flex [&_div:last-child>div:first-child]:text-xs [&_div:last-child>div:last-child]:hidden" />
              </>
            </Link>

            {!isDashboard ? (
              <div className="hidden min-w-0 rounded-full border border-border/70 bg-card/80 px-3 py-1 text-sm text-muted-foreground md:block">
                <span className="font-medium text-foreground">{currentItem.label}</span>
              </div>
            ) : null}
          </div>

          <div className="flex items-center gap-2">
            {!isDashboard ? (
              <Button asChild variant="outline" size="sm" className="hidden sm:inline-flex">
                <Link href="/dashboard">На главную</Link>
              </Button>
            ) : null}

            {topCreateAction ? (
              <Button asChild size="icon" aria-label={topCreateAction.label} title={topCreateAction.label}>
                <Link href={topCreateAction.href}>
                  <Plus className="h-4 w-4" />
                </Link>
              </Button>
            ) : null}

            <ModeToggle />

            <Button variant="outline" size="icon" onClick={() => setIsMenuOpen(true)} aria-label="Открыть меню разделов" title="Меню">
              <Menu className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      {isMenuOpen ? (
        <>
          <button
            type="button"
            aria-label="Закрыть меню"
            className="fixed inset-0 z-40 bg-slate-950/55 backdrop-blur-sm"
            onClick={() => setIsMenuOpen(false)}
          />

          <div className="fixed inset-x-0 top-16 z-50 mx-auto w-[min(980px,calc(100vw-1rem))] max-h-[calc(100vh-4.5rem)] overflow-hidden rounded-[28px] border border-border/70 bg-background/95 shadow-[0_28px_120px_-40px_rgba(15,23,42,0.7)] backdrop-blur-xl">
            <div className="flex items-start justify-between gap-4 border-b border-border/60 px-4 py-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary">Разделы и действия</div>
              </div>
              <Button variant="outline" size="icon" onClick={() => setIsMenuOpen(false)} aria-label="Закрыть меню">
                <X className="h-4 w-4" />
              </Button>
            </div>

            <div className="max-h-[calc(100vh-10rem)] overflow-y-auto px-4 py-4">
              <div className="rounded-[20px] border border-border/60 bg-card/80 p-3.5">
                <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">Частые действия</div>
                <div className="mt-2.5 grid gap-2 sm:grid-cols-3">
                  {frequentActions.map((action) => {
                    const Icon = action.icon

                    return (
                      <Button key={action.href} asChild className="justify-between">
                        <Link href={action.href} onClick={() => setIsMenuOpen(false)}>
                          {action.label}
                          <Icon className="h-4 w-4" />
                        </Link>
                      </Button>
                    )
                  })}
                </div>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-3">
                {navigationSections.map((section) => (
                  <div key={section.title} className="rounded-[20px] border border-border/60 bg-card/80 p-3.5">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{section.title}</div>
                    <div className="mt-2.5 space-y-2">
                      {section.items.map((item) => {
                        const Icon = item.icon
                        const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`)

                        return (
                          <Link
                            key={item.href}
                            href={item.href}
                            onClick={() => setIsMenuOpen(false)}
                            className={cn(
                              "block rounded-[18px] border px-3 py-2.5 transition-colors",
                              isActive
                                ? "border-primary/20 bg-primary/10"
                                : "border-border/60 bg-background/70 hover:bg-background"
                            )}
                          >
                            <div className="flex items-start gap-3">
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-foreground/80">
                                <Icon className="h-4 w-4" />
                              </div>
                              <div className="min-w-0">
                                <div className="text-sm font-medium tracking-[-0.02em] text-foreground">{item.label}</div>
                                <div className="mt-0.5 text-xs leading-4.5 text-muted-foreground">{item.description}</div>
                              </div>
                            </div>
                          </Link>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-4 rounded-[20px] border border-border/60 bg-card/80 p-3.5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">{getUserDisplayName(user)}</div>
                    <div className="mt-1 text-xs leading-5 text-muted-foreground">{getUserSecondaryText(user)}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {accountItems.map((item) => {
                      const Icon = item.icon

                      return (
                        <Button key={item.href} asChild variant="outline">
                          <Link href={item.href} onClick={() => setIsMenuOpen(false)}>
                            <Icon className="h-4 w-4" />
                            {item.label}
                          </Link>
                        </Button>
                      )
                    })}

                    <Button variant="outline" onClick={handleLogout}>
                      <LogOut className="h-4 w-4" />
                      Выйти
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      ) : null}

      <main className="mx-auto w-full max-w-[1440px] px-3 py-4 sm:px-5 sm:py-5 lg:px-6">{children}</main>
    </div>
  )
}
