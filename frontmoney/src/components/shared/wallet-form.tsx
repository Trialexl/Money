"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Eye, EyeOff, Save } from "lucide-react"

import { PageHeader } from "@/components/shared/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Wallet, WalletService } from "@/services/wallet-service"

interface WalletFormProps {
  wallet?: Wallet
  isEdit?: boolean
}

export default function WalletForm({ wallet, isEdit = false }: WalletFormProps) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [name, setName] = useState(wallet?.name || "")
  const [hidden, setHidden] = useState<boolean>(wallet?.hidden ?? false)

  useEffect(() => {
    setName(wallet?.name || "")
    setHidden(wallet?.hidden ?? false)
  }, [wallet])

  const walletMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name: name.trim(),
        hidden,
      }

      if (isEdit && wallet) {
        return WalletService.updateWallet(wallet.id, payload)
      }

      return WalletService.createWallet(payload)
    },
    onSuccess: async (savedWallet) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["wallets"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
        wallet?.id ? queryClient.invalidateQueries({ queryKey: ["wallet", wallet.id] }) : Promise.resolve(),
      ])

      router.push(`/wallets/${savedWallet.id}`)
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await walletMutation.mutateAsync()
  }

  const errorMessage = walletMutation.error
    ? (walletMutation.error as any)?.response?.data?.detail || "Не удалось сохранить кошелек. Проверь поля и попробуй еще раз."
    : null

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Wallets"
        title={isEdit ? "Редактирование кошелька" : "Новый кошелек"}
        description={
          isEdit
            ? "Обнови название и режим отображения. Скрытые кошельки остаются в системе, но уходят из стандартного набора."
            : "Создай новый источник денег: банковский счет, карту, наличные или технический кошелек для внутреннего учета."
        }
        actions={
          <Button asChild variant="outline">
            <Link href={isEdit && wallet ? `/wallets/${wallet.id}` : "/wallets"}>Отмена</Link>
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Основные параметры</CardTitle>
            <CardDescription>Сначала введи понятное название. Остальные технические поля backend назначит сам.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-6 rounded-[24px] border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm leading-6 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="wallet-name">Название</Label>
                <Input
                  id="wallet-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Например, Т-Банк Black"
                  maxLength={25}
                  required
                />
              </div>

              <div className="flex items-start justify-between gap-4 rounded-[24px] border border-border/70 bg-background/70 px-4 py-4">
                <div className="space-y-1">
                  <Label htmlFor="wallet-hidden">Скрытый кошелек</Label>
                  <p className="text-sm leading-6 text-muted-foreground">
                    Удобно для инвестиционных, служебных и других кошельков, которые не нужны в ежедневном учете.
                  </p>
                </div>
                <Switch id="wallet-hidden" checked={hidden} onCheckedChange={setHidden} />
              </div>

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={walletMutation.isPending || !name.trim()}>
                  <Save className="h-4 w-4" />
                  {walletMutation.isPending ? "Сохраняем..." : isEdit ? "Сохранить изменения" : "Создать кошелек"}
                </Button>
                <Button asChild variant="outline">
                  <Link href={isEdit && wallet ? `/wallets/${wallet.id}` : "/wallets"}>Отмена</Link>
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Предпросмотр</CardTitle>
            <CardDescription>Как кошелек будет выглядеть в новой системе.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-[24px] border border-border/70 bg-background/70 p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold tracking-[-0.03em]">{name.trim() || "Новый кошелек"}</div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    {wallet?.code ? `Код: ${wallet.code}` : "Код назначим автоматически"}
                  </div>
                </div>
                {hidden ? <Badge variant="outline">Hidden</Badge> : <Badge variant="default">Active</Badge>}
              </div>
              <div className="mt-8 flex items-center gap-3 text-sm text-muted-foreground">
                {hidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                {hidden ? "Кошелек будет скрыт из стандартного списка." : "Кошелек будет сразу виден в основном наборе."}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
