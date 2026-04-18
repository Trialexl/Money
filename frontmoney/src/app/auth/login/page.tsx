"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowRight, CheckCircle2, ShieldCheck, WalletCards } from "lucide-react"

import { BrandMark } from "@/components/shared/brand-mark"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ModeToggle } from "@/components/ui/mode-toggle"
import { isAuthenticated } from "@/lib/auth"
import { useAuthStore } from "@/store/auth-store"

const loginAdvantages = [
  "Новый рабочий стол с понятной иерархией блоков",
  "Быстрые переходы между кошельками, отчетами и документами",
  "Понятные ошибки сети, API и авторизации вместо ложных подсказок",
]

export default function LoginPage() {
  const router = useRouter()
  const { login } = useAuthStore()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (isAuthenticated()) {
      router.replace("/dashboard")
    }
  }, [router])

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setIsLoading(true)

    try {
      await login(username, password)
      router.push("/dashboard")
    } catch (err: any) {
      if (!err?.response) {
        setError("Не удалось подключиться к API. Проверь backend, CORS и адрес NEXT_PUBLIC_API_URL.")
      } else {
        setError(err.response?.data?.detail || "Ошибка входа. Проверь логин и пароль.")
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-6 sm:px-6 lg:px-8">
      <div className="absolute right-4 top-4 z-10 sm:right-6 sm:top-6">
        <ModeToggle />
      </div>

      <div className="mx-auto grid min-h-[calc(100vh-3rem)] max-w-7xl items-center gap-10 lg:grid-cols-[1.08fr_minmax(420px,520px)]">
        <section className="relative overflow-hidden rounded-[36px] border border-border/70 bg-slate-950 px-7 py-10 text-white shadow-soft sm:px-10 sm:py-12">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(45,212,191,0.23),transparent_26%),radial-gradient(circle_at_bottom_right,rgba(251,146,60,0.22),transparent_24%)]" />
          <div className="relative space-y-10">
            <BrandMark />

            <div className="max-w-2xl space-y-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-100">
                FrontMoney rebuild
              </div>
              <h1 className="text-4xl font-semibold tracking-[-0.05em] text-white sm:text-5xl">
                Финансовый интерфейс должен помогать принимать решения, а не мешать.
              </h1>
              <p className="max-w-xl text-base leading-8 text-slate-300 sm:text-lg">
                Мы пересобираем приложение как нормальный продуктовый кабинет: сильная навигация, чистые формы, ясные метрики и понятный рабочий ритм.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-[28px] border border-white/10 bg-white/10 p-5 backdrop-blur">
                <WalletCards className="h-5 w-5 text-cyan-200" />
                <div className="mt-4 text-2xl font-semibold tracking-[-0.04em]">1 UI system</div>
                <div className="mt-2 text-sm leading-6 text-slate-300">Одна система для всех разделов вместо набора случайных экранов.</div>
              </div>
              <div className="rounded-[28px] border border-white/10 bg-white/10 p-5 backdrop-blur">
                <ShieldCheck className="h-5 w-5 text-emerald-200" />
                <div className="mt-4 text-2xl font-semibold tracking-[-0.04em]">API-first</div>
                <div className="mt-2 text-sm leading-6 text-slate-300">Интерфейс строится вокруг реального backend-контракта, а не догадок.</div>
              </div>
              <div className="rounded-[28px] border border-white/10 bg-white/10 p-5 backdrop-blur">
                <CheckCircle2 className="h-5 w-5 text-amber-200" />
                <div className="mt-4 text-2xl font-semibold tracking-[-0.04em]">Less friction</div>
                <div className="mt-2 text-sm leading-6 text-slate-300">Быстрые действия, хорошие состояния загрузки и понятные ошибки.</div>
              </div>
            </div>

            <div className="rounded-[30px] border border-white/10 bg-white/8 p-6 backdrop-blur">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-100">Что уже меняется</div>
              <div className="mt-4 grid gap-3">
                {loginAdvantages.map((item) => (
                  <div key={item} className="flex items-start gap-3 text-sm leading-7 text-slate-200">
                    <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-300" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <Card className="border-border/80 bg-card/95">
          <CardHeader className="space-y-4 p-8 pb-0">
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">Secure access</div>
            <div className="space-y-2">
              <CardTitle className="text-3xl">Вход в систему</CardTitle>
              <CardDescription>
                Используй логин пользователя, не email. Для стандартной учетки это обычно `admin`.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="p-8">
            {error ? (
              <div className="mb-6 rounded-[24px] border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm leading-6 text-destructive">
                {error}
              </div>
            ) : null}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="username">Логин</Label>
                <Input
                  id="username"
                  autoComplete="username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="admin"
                  required
                />
                <p className="text-xs leading-5 text-muted-foreground">Если backend не поддерживает вход по email, используй username.</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Пароль</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Введите пароль"
                  required
                />
              </div>

              <Button type="submit" className="w-full justify-center" disabled={isLoading}>
                {isLoading ? "Входим..." : "Открыть рабочий стол"}
                {!isLoading ? <ArrowRight className="h-4 w-4" /> : null}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  )
}
