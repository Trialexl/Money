"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import {
  LayoutDashboard,
  Wallet,
  PieChart,
  Layers,
  ArrowUpRight,
  ArrowDownRight,
  ArrowRightLeft,
  Calendar,
  BarChart4,
  Bot,
  LogOut,
  Settings,
  Menu,
  X,
} from "lucide-react"
import { useState } from "react"
import { ModeToggle } from "@/components/ui/mode-toggle"
import { Button } from "@/components/ui/button"
import { getUserDisplayName, getUserSecondaryText } from "@/lib/user-profile"
import { useAuthStore } from "@/store/auth-store"

const sidebarItems = [
  {
    title: "Дашборд",
    href: "/dashboard",
    icon: <LayoutDashboard className="h-5 w-5" />,
  },
  {
    title: "Кошельки",
    href: "/wallets",
    icon: <Wallet className="h-5 w-5" />,
  },
  {
    title: "Статьи",
    href: "/cash-flow-items",
    icon: <PieChart className="h-5 w-5" />,
  },
  {
    title: "Проекты",
    href: "/projects",
    icon: <Layers className="h-5 w-5" />,
  },
  {
    title: "Приходы",
    href: "/receipts",
    icon: <ArrowUpRight className="h-5 w-5" />,
  },
  {
    title: "Расходы",
    href: "/expenditures",
    icon: <ArrowDownRight className="h-5 w-5" />,
  },
  {
    title: "Переводы",
    href: "/transfers",
    icon: <ArrowRightLeft className="h-5 w-5" />,
  },
  {
    title: "Бюджеты",
    href: "/budgets",
    icon: <Calendar className="h-5 w-5" />,
  },
  {
    title: "Автоплатежи",
    href: "/auto-payments",
    icon: <Calendar className="h-5 w-5" />,
  },
  {
    title: "Отчеты",
    href: "/reports",
    icon: <BarChart4 className="h-5 w-5" />,
  },
  {
    title: "Ассистент",
    href: "/assistant",
    icon: <Bot className="h-5 w-5" />,
  },
  {
    title: "Настройки",
    href: "/settings",
    icon: <Settings className="h-5 w-5" />,
  },
]

export function SidebarNav() {
  const pathname = usePathname()
  const [isOpen, setIsOpen] = useState(false)
  const { logout, user } = useAuthStore()

  const handleLogout = async () => {
    await logout()
    window.location.href = "/auth/login"
  }

  return (
    <>
      {/* Mobile menu button */}
      <div className="fixed top-4 left-4 z-50 md:hidden">
        <Button
          variant="outline"
          size="icon"
          onClick={() => setIsOpen(!isOpen)}
          aria-label="Открыть или закрыть меню"
        >
          {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </Button>
      </div>

      {/* Overlay */}
      {isOpen && (
        <div 
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm md:hidden"
          onClick={() => setIsOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div className={cn(
        "fixed top-0 left-0 z-40 h-screen w-64 bg-background border-r transition-transform duration-300 ease-in-out",
        isOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
      )}>
        <div className="flex flex-col h-full">
          <div className="flex h-16 items-center px-4 border-b">
            <Link href="/dashboard" className="flex items-center">
              <span className="text-lg font-bold">FrontMoney</span>
            </Link>
          </div>
          <div className="flex-1 overflow-y-auto py-4 px-3">
            <nav className="space-y-1">
              {sidebarItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center px-3 py-2 text-sm rounded-md",
                    pathname === item.href || pathname.startsWith(`${item.href}/`)
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-muted"
                  )}
                >
                  {item.icon}
                  <span className="ml-3">{item.title}</span>
                </Link>
              ))}
            </nav>
          </div>
          <div className="border-t p-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex flex-col">
                <span className="text-sm font-medium">{getUserDisplayName(user)}</span>
                <span className="text-xs text-muted-foreground">{getUserSecondaryText(user)}</span>
              </div>
              <ModeToggle />
            </div>
            <Button
              variant="outline"
              className="w-full"
              onClick={handleLogout}
            >
              <LogOut className="h-4 w-4 mr-2" />
              Выйти
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
