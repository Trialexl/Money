"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRightLeft, Save, X } from "lucide-react"

import { useActiveWalletsQuery, useWalletBalanceQuery } from "@/hooks/use-reference-data"
import { PageHeader } from "@/components/shared/page-header"
import { PlanningGraphicsPanel } from "@/components/shared/planning-graphics-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { formatCurrency, formatDate, formatDateForInput } from "@/lib/formatters"
import { Transfer, TransferService } from "@/services/financial-operations-service"
import { PlanningGraphicDraft, PlanningService } from "@/services/planning-service"

interface TransferFormProps {
  transfer?: Transfer
  isEdit?: boolean
}

export default function TransferForm({ transfer, isEdit = false }: TransferFormProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const duplicateId = searchParams.get("duplicate")
  const defaultWalletFromId = searchParams.get("wallet_from") || ""
  const defaultWalletToId = searchParams.get("wallet_to") || ""
  const isDuplicateMode = Boolean(duplicateId) && !isEdit
  const planningDraftStorageKey = !isEdit ? "planning-draft:transfer:new" : undefined
  const [amount, setAmount] = useState("")
  const [date, setDate] = useState(formatDateForInput())
  const [description, setDescription] = useState("")
  const [walletFromId, setWalletFromId] = useState<string | undefined>(undefined)
  const [walletToId, setWalletToId] = useState<string | undefined>(undefined)
  const [planningDraftRows, setPlanningDraftRows] = useState<PlanningGraphicDraft[]>([])
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setAmount(transfer?.amount?.toString() || "")
    setDate(isDuplicateMode ? formatDateForInput() : transfer?.date ? formatDateForInput(new Date(transfer.date)) : formatDateForInput())
    setDescription(transfer?.description || "")
    setWalletFromId(undefined)
    setWalletToId(undefined)
    setValidationError(null)
  }, [defaultWalletFromId, defaultWalletToId, isDuplicateMode, transfer])

  useEffect(() => {
    if (!planningDraftStorageKey) {
      setPlanningDraftRows([])
      return
    }

    setPlanningDraftRows(PlanningService.getDraftRows(planningDraftStorageKey))
  }, [planningDraftStorageKey])

  const walletsQuery = useActiveWalletsQuery()
  const baseWalletFromId = transfer?.wallet_from || defaultWalletFromId || ""
  const baseWalletToId = transfer?.wallet_to || defaultWalletToId || ""
  const effectiveWalletFromId = walletFromId ?? baseWalletFromId
  const effectiveWalletToId = walletToId ?? baseWalletToId
  const balanceQuery = useWalletBalanceQuery(effectiveWalletFromId)

  const transferMutation = useMutation({
    mutationFn: async () => {
      const parsedAmount = Number.parseFloat(amount)
      const payload: Partial<Transfer> = {
        amount: parsedAmount,
        date,
        description: description.trim() || undefined,
        wallet_from: effectiveWalletFromId,
        wallet_to: effectiveWalletToId,
      }

      if (isEdit && transfer) {
        return TransferService.updateTransfer(transfer.id, payload)
      }

      return TransferService.createTransfer(payload)
    },
    onSuccess: async (savedTransfer) => {
      if (!isEdit && planningDraftRows.length > 0) {
        await PlanningService.replaceGraphicsRows("transfer", savedTransfer.id, planningDraftRows)
        if (planningDraftStorageKey) {
          PlanningService.clearDraftRows(planningDraftStorageKey)
        }
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["transfers"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
        queryClient.invalidateQueries({ queryKey: ["wallets"] }),
      ])
      router.push("/transfers")
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)

    const parsedAmount = Number.parseFloat(amount)

    if (!effectiveWalletFromId || !effectiveWalletToId || !date || Number.isNaN(parsedAmount) || parsedAmount <= 0) {
      setValidationError("Укажи дату, сумму и оба кошелька. Сумма должна быть больше нуля.")
      return
    }

    if (effectiveWalletFromId === effectiveWalletToId) {
      setValidationError("Кошелек отправления и кошелек получения должны отличаться.")
      return
    }

    const availableBalance = balanceQuery.data?.balance
    if (typeof availableBalance === "number" && parsedAmount > availableBalance) {
      setValidationError(`Недостаточно средств. Сейчас на кошельке доступно ${formatCurrency(availableBalance)}.`)
      return
    }

    try {
      await transferMutation.mutateAsync()
    } catch {}
  }

  const wallets = walletsQuery.data || []
  const walletOptions = useMemo(() => {
    const options = [...wallets]

    for (const id of [effectiveWalletFromId, effectiveWalletToId]) {
      if (id && !options.some((wallet) => wallet.id === id)) {
        options.push({
          id,
          name: "Загружаем кошелек",
          code: null,
          hidden: false,
          created_at: "",
          updated_at: "",
          deleted: false,
        })
      }
    }

    return options
  }, [effectiveWalletFromId, effectiveWalletToId, wallets])
  const availableDestinationWallets = walletOptions.filter((wallet) => wallet.id !== effectiveWalletFromId)
  const selectedWalletFromLabel = effectiveWalletFromId
    ? walletOptions.find((wallet) => wallet.id === effectiveWalletFromId)?.name || "Загружаем кошелек"
    : "Выбери источник"
  const selectedWalletToLabel = effectiveWalletToId
    ? walletOptions.find((wallet) => wallet.id === effectiveWalletToId)?.name || "Загружаем кошелек"
    : "Выбери назначение"
  const parsedAmount = Number.parseFloat(amount)
  const errorMessage =
    validationError ||
    (transferMutation.error as any)?.response?.data?.detail ||
    (transferMutation.error ? "Не удалось сохранить перевод. Проверь поля и попробуй снова." : null) ||
    null

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Движение денег"
        title={isEdit ? "Редактирование перевода" : "Новый перевод"}
        description={
          isEdit
            ? "Обнови маршрут перевода, сумму и описание. Переводы должны читаться как технически чистые перемещения между кошельками."
            : "Создай внутренний перевод между кошельками. Этот поток не должен смешиваться с доходами и расходами."
        }
        actions={
          <Button asChild variant="outline" size="icon">
            <Link href="/transfers" aria-label="К списку" title="К списку">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
        }
      />

      <div>
        <Card>
          <CardHeader>
            <CardTitle>Параметры перевода</CardTitle>
            <CardDescription>Сильный сценарий здесь один: быстро указать источник, назначение и сумму, не создавая ложную сложность.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-5 rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm leading-5 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            {walletsQuery.isError ? (
              <div className="rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-3 text-sm leading-5 text-destructive">
                Не удалось загрузить список кошельков для перевода. Проверь backend API и попробуй обновить страницу.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="transfer-amount">Сумма</Label>
                    <Input
                      id="transfer-amount"
                      type="number"
                      min="0"
                      step="0.01"
                      value={amount}
                      onChange={(event) => setAmount(event.target.value)}
                      placeholder="0.00"
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="transfer-date">Дата перевода</Label>
                    <Input
                      id="transfer-date"
                      type="date"
                      value={date}
                      onChange={(event) => setDate(event.target.value)}
                      required
                    />
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-start">
                  <div className="space-y-2">
                    <Label htmlFor="transfer-wallet-from">Кошелек отправления</Label>
                    {walletsQuery.isLoading ? (
                      <div className="rounded-[16px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
                        Загружаем кошельки...
                      </div>
                    ) : (
                      <Select value={effectiveWalletFromId || "unselected"} onValueChange={(value) => setWalletFromId(value === "unselected" ? "" : value)}>
                        <SelectTrigger id="transfer-wallet-from" className="h-11 rounded-xl bg-background/80 px-3">
                          <span className={effectiveWalletFromId ? "truncate" : "truncate text-muted-foreground"}>
                            {selectedWalletFromLabel}
                          </span>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="unselected">Не выбрано</SelectItem>
                          {walletOptions.map((wallet) => (
                            <SelectItem key={wallet.id} value={wallet.id}>
                              {wallet.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                    <div className="text-xs leading-4 text-muted-foreground">
                      {balanceQuery.isLoading
                        ? "Проверяем доступный баланс..."
                        : typeof balanceQuery.data?.balance === "number"
                          ? `Доступно: ${formatCurrency(balanceQuery.data.balance)}`
                          : "Баланс будет показан после выбора кошелька"}
                    </div>
                  </div>

                  <div className="flex h-11 items-center justify-center md:pt-7">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                      <ArrowRightLeft className="h-5 w-5" />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="transfer-wallet-to">Кошелек получения</Label>
                    {walletsQuery.isLoading ? (
                      <div className="rounded-[16px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
                        Загружаем кошельки...
                      </div>
                    ) : (
                      <Select value={effectiveWalletToId || "unselected"} onValueChange={(value) => setWalletToId(value === "unselected" ? "" : value)}>
                        <SelectTrigger id="transfer-wallet-to" className="h-11 rounded-xl bg-background/80 px-3">
                          <span className={effectiveWalletToId ? "truncate" : "truncate text-muted-foreground"}>
                            {selectedWalletToLabel}
                          </span>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="unselected">Не выбрано</SelectItem>
                          {availableDestinationWallets.map((wallet) => (
                            <SelectItem key={wallet.id} value={wallet.id}>
                              {wallet.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="transfer-description">Комментарий</Label>
                  <Textarea
                    id="transfer-description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Короткое пояснение для сверки движения"
                    rows={4}
                  />
                </div>

                <div className="flex flex-wrap gap-3">
                  <Button type="submit" disabled={transferMutation.isPending || walletsQuery.isLoading || walletsQuery.isError}>
                    <Save className="h-4 w-4" />
                    {transferMutation.isPending ? "Сохраняем..." : isEdit ? "Сохранить изменения" : "Создать перевод"}
                  </Button>
                  <Button asChild variant="outline" size="icon">
                    <Link href="/transfers" aria-label="Отмена" title="Отмена">
                      <X className="h-4 w-4" />
                    </Link>
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </div>

      <PlanningGraphicsPanel
        kind="transfer"
        documentId={isEdit ? transfer?.id : undefined}
        graphicContract={transfer?.graphic_contract}
        draftRows={planningDraftRows}
        draftStorageKey={planningDraftStorageKey}
        onDraftRowsChange={setPlanningDraftRows}
        distributionSource={{
          totalAmount: !Number.isNaN(parsedAmount) && parsedAmount > 0 ? parsedAmount : 0,
          startDate: date,
        }}
      />
    </div>
  )
}
