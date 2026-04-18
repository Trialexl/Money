"use client"

import { useEffect, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Building2, Save, Settings, ShieldCheck, UserRound, WalletCards } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { PageHeader } from "@/components/shared/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { AuthService, ProfileStatus } from "@/services/auth-service"
import { useAuthStore } from "@/store/auth-store"
import { getUserDisplayName, getUserSecondaryText, getUserStatusLabel } from "@/lib/user-profile"

export default function SettingsPage() {
  const { user, setUser, loadProfile } = useAuthStore()
  const [username, setUsername] = useState("")
  const [fullName, setFullName] = useState("")
  const [taxId, setTaxId] = useState("")
  const [status, setStatus] = useState<ProfileStatus>("PRIV")
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setUsername(user?.username || "")
    setFullName(user?.full_name || "")
    setTaxId(user?.tax_id || "")
    setStatus(user?.status === "COMP" ? "COMP" : "PRIV")
    setValidationError(null)
  }, [user])

  const profileMutation = useMutation({
    mutationFn: async () => {
      return AuthService.updateProfile({
        id: user?.id,
        username: username.trim(),
        full_name: fullName.trim() || null,
        tax_id: taxId.trim() || null,
        status,
      })
    },
    onSuccess: (updatedProfile) => {
      setUser(updatedProfile)
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)

    if (!username.trim()) {
      setValidationError("Имя пользователя обязательно.")
      return
    }

    if (!user || !user.id) {
      setValidationError("Профиль пока не готов к сохранению. Обнови страницу и попробуй снова.")
      return
    }

    try {
      await profileMutation.mutateAsync()
    } catch {}
  }

  if (!user) {
    return (
      <EmptyState
        icon={Settings}
        title="Профиль пока не загружен"
        description="Не удалось получить данные текущего пользователя. Попробуй загрузить профиль заново."
        action={<Button onClick={() => loadProfile()}>Загрузить профиль</Button>}
      />
    )
  }

  const errorMessage =
    validationError ||
    (profileMutation.error as any)?.response?.data?.detail ||
    (profileMutation.error ? "Не удалось сохранить настройки профиля. Проверь поля и попробуй снова." : null) ||
    null

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Профиль"
        title="Настройки профиля"
        description="Основные данные аккаунта и тип профиля."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Основные данные</CardTitle>
            <CardDescription>Логин, имя, ИНН и тип профиля.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-5 rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm leading-5 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="settings-username">Имя пользователя</Label>
                <Input
                  id="settings-username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Например, admin"
                  maxLength={150}
                  required
                />
                <p className="text-xs leading-4 text-muted-foreground">Используется для входа.</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="settings-full-name">Полное имя / наименование</Label>
                <Input
                  id="settings-full-name"
                  value={fullName}
                  onChange={(event) => setFullName(event.target.value)}
                  placeholder="Например, Алексей Алфимов или FrontMoney LLC"
                  maxLength={250}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="settings-tax-id">ИНН</Label>
                <Input
                  id="settings-tax-id"
                  value={taxId}
                  onChange={(event) => setTaxId(event.target.value.replace(/[^\d]/g, ""))}
                  placeholder="10 или 12 цифр"
                  maxLength={12}
                  inputMode="numeric"
                />
                <p className="text-xs leading-4 text-muted-foreground">Если ИНН нужен в твоем сценарии учета.</p>
              </div>

              <div className="space-y-3">
                <Label>Тип профиля</Label>
                <RadioGroup value={status} onValueChange={(value) => setStatus(value as ProfileStatus)} className="grid gap-3 sm:grid-cols-2">
                  <label className="flex cursor-pointer items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                    <RadioGroupItem value="PRIV" id="settings-status-private" className="mt-1" />
                    <div className="space-y-1">
                      <div className="font-medium text-foreground">Частное лицо</div>
                      <div className="text-sm leading-5 text-muted-foreground">Для личного и семейного учета.</div>
                    </div>
                  </label>
                  <label className="flex cursor-pointer items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                    <RadioGroupItem value="COMP" id="settings-status-company" className="mt-1" />
                    <div className="space-y-1">
                      <div className="font-medium text-foreground">Компания</div>
                      <div className="text-sm leading-5 text-muted-foreground">Для рабочего или юридического контура.</div>
                    </div>
                  </label>
                </RadioGroup>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={profileMutation.isPending || !username.trim()}>
                  <Save className="h-4 w-4" />
                  {profileMutation.isPending ? "Сохраняем..." : "Сохранить настройки"}
                </Button>
                <Button type="button" variant="outline" onClick={() => {
                  setUsername(user.username || "")
                  setFullName(user.full_name || "")
                  setTaxId(user.tax_id || "")
                  setStatus(user.status === "COMP" ? "COMP" : "PRIV")
                  setValidationError(null)
                }}>
                  Сбросить изменения
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Как выглядит профиль</CardTitle>
              <CardDescription>Так он читается в приложении.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-[18px] border border-border/70 bg-background/70 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-lg font-semibold tracking-[-0.03em]">
                      {fullName.trim() || username.trim() || getUserDisplayName(user)}
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">@{username.trim() || user.username}</div>
                  </div>
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <UserRound className="h-5 w-5" />
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Badge variant="secondary">{status === "COMP" ? "Компания" : "Частное лицо"}</Badge>
                  {taxId.trim() ? <Badge variant="outline">ИНН {taxId.trim()}</Badge> : null}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Сводка профиля</CardTitle>
              <CardDescription>Коротко о текущем состоянии профиля.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm leading-5 text-muted-foreground">
              <div className="flex items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 p-3">
                <ShieldCheck className="mt-1 h-4 w-4 text-primary" />
                <div>
                  В шапке и навигации профиль будет показан по отображаемому имени, а если оно не заполнено, по логину.
                </div>
              </div>
              <div className="flex items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 p-3">
                <Building2 className="mt-1 h-4 w-4 text-primary" />
                <div>
                  Тип профиля: <span className="font-medium text-foreground">{status === "COMP" ? "Компания" : "Частное лицо"}</span>.
                </div>
              </div>
              <div className="flex items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 p-3">
                <WalletCards className="mt-1 h-4 w-4 text-primary" />
                <div>
                  Налоговый идентификатор: <span className="font-medium text-foreground">{taxId.trim() || "не заполнен"}</span>.
                </div>
              </div>
              <div className="rounded-[18px] border border-border/70 bg-background/70 p-3">
                Этот экран намеренно короткий: только те поля, которые действительно нужны для ежедневной работы и не перегружают настройки лишними деталями.
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
