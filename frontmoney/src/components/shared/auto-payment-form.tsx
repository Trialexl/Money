"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Save, X } from "lucide-react"

import { useOperationReferenceDataQuery, useWalletBalanceQuery } from "@/hooks/use-reference-data"
import { PageHeader } from "@/components/shared/page-header"
import { PlanningGraphicsPanel } from "@/components/shared/planning-graphics-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { formatCurrency, formatDate, formatDateForInput } from "@/lib/formatters"
import { AutoPayment, AutoPaymentService } from "@/services/financial-operations-service"
import { PlanningGraphicDraft, PlanningService } from "@/services/planning-service"

function getDaysUntil(dateString?: string) {
  if (!dateString) {
    return null
  }

  const target = new Date(dateString)
  if (Number.isNaN(target.getTime())) {
    return null
  }

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  target.setHours(0, 0, 0, 0)

  return Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
}

interface AutoPaymentFormProps {
  autoPayment?: AutoPayment
  isEdit?: boolean
}

export default function AutoPaymentForm({ autoPayment, isEdit = false }: AutoPaymentFormProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const duplicateId = searchParams.get("duplicate")
  const defaultWalletFromId = searchParams.get("wallet_from") || ""
  const defaultWalletToId = searchParams.get("wallet_to") || ""
  const defaultCashFlowItemId = searchParams.get("cash_flow_item") || ""
  const isDuplicateMode = Boolean(duplicateId) && !isEdit
  const planningDraftStorageKey = !isEdit ? "planning-draft:auto-payment:new" : undefined
  const [amount, setAmount] = useState("")
  const [dateStart, setDateStart] = useState(formatDateForInput())
  const [description, setDescription] = useState("")
  const [amountMonth, setAmountMonth] = useState("12")
  const [isTransfer, setIsTransfer] = useState(false)
  const [walletFromId, setWalletFromId] = useState<string | undefined>(undefined)
  const [walletToId, setWalletToId] = useState<string | undefined>(undefined)
  const [cashFlowItemId, setCashFlowItemId] = useState<string | undefined>(undefined)
  const [planningDraftRows, setPlanningDraftRows] = useState<PlanningGraphicDraft[] | null>(isEdit ? null : [])
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setAmount(autoPayment?.amount?.toString() || "")
    setDateStart(
      isDuplicateMode
        ? formatDateForInput()
        : autoPayment?.date_start
          ? formatDateForInput(new Date(autoPayment.date_start))
          : formatDateForInput()
    )
    setDescription(autoPayment?.description || "")
    setAmountMonth(autoPayment?.amount_month != null ? String(autoPayment.amount_month) : "12")
    setIsTransfer(autoPayment?.is_transfer ?? false)
    setWalletFromId(undefined)
    setWalletToId(undefined)
    setCashFlowItemId(undefined)
    setValidationError(null)
  }, [autoPayment, defaultCashFlowItemId, defaultWalletFromId, defaultWalletToId, isDuplicateMode])

  useEffect(() => {
    if (!planningDraftStorageKey) {
      setPlanningDraftRows(isEdit ? null : [])
      return
    }

    setPlanningDraftRows(PlanningService.getDraftRows(planningDraftStorageKey))
  }, [isEdit, planningDraftStorageKey])

  const referencesQuery = useOperationReferenceDataQuery()
  const baseWalletFromId = autoPayment?.wallet_from || defaultWalletFromId || ""
  const baseWalletToId = autoPayment?.wallet_to || defaultWalletToId || ""
  const baseCashFlowItemId = autoPayment?.cash_flow_item || defaultCashFlowItemId || ""
  const effectiveWalletFromId = walletFromId ?? baseWalletFromId
  const effectiveWalletToId = walletToId ?? baseWalletToId
  const effectiveCashFlowItemId = cashFlowItemId ?? baseCashFlowItemId
  const balanceQuery = useWalletBalanceQuery(effectiveWalletFromId)

  const autoPaymentMutation = useMutation({
    mutationFn: async () => {
      const parsedAmount = Number.parseFloat(amount)
      const parsedAmountMonth = Number.parseInt(amountMonth, 10)
      const payload: Partial<AutoPayment> = {
        amount: parsedAmount,
        date_start: dateStart,
        description: description.trim() || undefined,
        amount_month: parsedAmountMonth,
        is_transfer: isTransfer,
        wallet_from: effectiveWalletFromId,
        wallet_to: isTransfer ? effectiveWalletToId : undefined,
        cash_flow_item: isTransfer ? undefined : effectiveCashFlowItemId,
      }

      if (isEdit && autoPayment) {
        return AutoPaymentService.updateAutoPayment(autoPayment.id, payload)
      }

      return AutoPaymentService.createAutoPayment(payload)
    },
    onSuccess: async (savedAutoPayment) => {
      const shouldReplacePlanningRows = isEdit ? planningDraftRows !== null : Boolean(planningDraftRows?.length)

      if (shouldReplacePlanningRows) {
        await PlanningService.replaceGraphicsRows("auto-payment", savedAutoPayment.id, planningDraftRows ?? [])
        if (planningDraftStorageKey) {
          PlanningService.clearDraftRows(planningDraftStorageKey)
        }
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["auto-payments"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
      ])
      router.push("/auto-payments")
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)

    const parsedAmount = Number.parseFloat(amount)
    const parsedAmountMonth = Number.parseInt(amountMonth, 10)

    if (!effectiveWalletFromId || !dateStart || Number.isNaN(parsedAmount) || parsedAmount <= 0) {
      setValidationError("Укажи источник, следующую дату и сумму. Сумма должна быть больше нуля.")
      return
    }

    if (Number.isNaN(parsedAmountMonth) || parsedAmountMonth <= 0) {
      setValidationError("Количество месяцев должно быть положительным числом.")
      return
    }

    if (isTransfer && !effectiveWalletToId) {
      setValidationError("Для автоперевода нужно указать кошелек назначения.")
      return
    }

    if (!isTransfer && !effectiveCashFlowItemId) {
      setValidationError("Для автосписания нужно указать статью расхода.")
      return
    }

    if (isTransfer && effectiveWalletFromId === effectiveWalletToId) {
      setValidationError("Кошелек отправления и кошелек назначения должны отличаться.")
      return
    }

    try {
      await autoPaymentMutation.mutateAsync()
    } catch {}
  }

  const wallets = referencesQuery.wallets
  const cashFlowItems = referencesQuery.cashFlowItems
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
  const cashFlowItemOptions = useMemo(() => {
    if (!effectiveCashFlowItemId || cashFlowItems.some((item) => item.id === effectiveCashFlowItemId)) {
      return cashFlowItems
    }

    return [
      ...cashFlowItems,
      {
        id: effectiveCashFlowItemId,
        name: "Загружаем статью",
        code: null,
        created_at: "",
        updated_at: "",
        deleted: false,
      },
    ]
  }, [effectiveCashFlowItemId, cashFlowItems])
  const parsedAmount = Number.parseFloat(amount)
  const parsedAmountMonth = Number.parseInt(amountMonth, 10)
  const hasAmount = !Number.isNaN(parsedAmount) && parsedAmount > 0
  const destinationWallets = walletOptions.filter((wallet) => wallet.id !== effectiveWalletFromId)
  const selectedWalletFromLabel = effectiveWalletFromId
    ? walletOptions.find((wallet) => wallet.id === effectiveWalletFromId)?.name || "Загружаем кошелек"
    : "Выбери источник"
  const selectedWalletToLabel = effectiveWalletToId
    ? walletOptions.find((wallet) => wallet.id === effectiveWalletToId)?.name || "Загружаем кошелек"
    : "Выбери назначение"
  const selectedCashFlowItemLabel = effectiveCashFlowItemId
    ? cashFlowItemOptions.find((item) => item.id === effectiveCashFlowItemId)?.name || "Загружаем статью"
    : "Выбери статью расхода"
  const errorMessage =
    validationError ||
    (autoPaymentMutation.error as any)?.response?.data?.detail ||
    (autoPaymentMutation.error ? "Не удалось сохранить автоплатеж. Проверь поля и попробуй снова." : null) ||
    null

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Регулярные правила"
        title={isEdit ? "Редактирование автоплатежа" : "Новый автоплатеж"}
        description={
          isEdit
            ? "Обнови тип, интервал и следующую дату срабатывания. Автоплатежи должны быть прозрачны и легко читаемы."
            : "Создай правило повторяющегося перевода или регулярного списания, чтобы не хранить такие сценарии в голове."
        }
        actions={
          <Button asChild variant="outline" size="icon">
            <Link href="/auto-payments" aria-label="К списку" title="К списку">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
        }
      />

      <div>
        <Card>
          <CardHeader>
            <CardTitle>Параметры правила</CardTitle>
            <CardDescription>Здесь важно быстро понять три вещи: что повторяется, из какого источника и когда случится следующее срабатывание.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-5 rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm leading-5 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            {referencesQuery.isError ? (
              <div className="rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-3 text-sm leading-5 text-destructive">
                Не удалось загрузить кошельки и статьи для формы. Проверь backend API и попробуй обновить страницу.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
                <div className="space-y-3">
                  <Label>Тип правила</Label>
                  <RadioGroup
                    value={isTransfer ? "transfer" : "expense"}
                    onValueChange={(value) => setIsTransfer(value === "transfer")}
                    className="grid gap-3 sm:grid-cols-2"
                  >
                    <label className="flex cursor-pointer items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                      <RadioGroupItem value="transfer" id="autopayment-transfer" className="mt-1" />
                      <div className="space-y-1">
                        <div className="font-medium text-foreground">Автоперевод</div>
                        <div className="text-sm leading-5 text-muted-foreground">Регулярное перемещение денег между своими кошельками.</div>
                      </div>
                    </label>
                    <label className="flex cursor-pointer items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                      <RadioGroupItem value="expense" id="autopayment-expense" className="mt-1" />
                      <div className="space-y-1">
                        <div className="font-medium text-foreground">Автосписание</div>
                        <div className="text-sm leading-5 text-muted-foreground">Регулярный расход по одной и той же статье.</div>
                      </div>
                    </label>
                  </RadioGroup>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="autopayment-amount">Сумма</Label>
                    <Input
                      id="autopayment-amount"
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
                      <Label htmlFor="autopayment-next-date">Следующая дата</Label>
                      <Input
                        id="autopayment-next-date"
                        type="date"
                        value={dateStart}
                        onChange={(event) => setDateStart(event.target.value)}
                        required
                      />
                    </div>

                  <div className="space-y-2">
                    <Label htmlFor="autopayment-period">Месяцев в графике</Label>
                      <Input
                        id="autopayment-period"
                        type="number"
                        min="1"
                        step="1"
                        value={amountMonth}
                        onChange={(event) => setAmountMonth(event.target.value)}
                        placeholder="12"
                        required
                      />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="autopayment-wallet-from">Кошелек отправления</Label>
                  {referencesQuery.isLoading ? (
                    <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
                      Загружаем кошельки...
                    </div>
                  ) : (
                    <Select value={effectiveWalletFromId || "unselected"} onValueChange={(value) => setWalletFromId(value === "unselected" ? "" : value)}>
                      <SelectTrigger id="autopayment-wallet-from" className="h-12 rounded-2xl bg-background/80 px-4">
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
                  <div className="text-xs leading-5 text-muted-foreground">
                    {balanceQuery.isLoading
                      ? "Проверяем текущий баланс..."
                      : typeof balanceQuery.data?.balance === "number"
                        ? `Сейчас на кошельке ${formatCurrency(balanceQuery.data.balance)}`
                        : "Баланс будет показан после выбора кошелька"}
                  </div>
                </div>

                {isTransfer ? (
                  <div className="space-y-2">
                    <Label htmlFor="autopayment-wallet-to">Кошелек назначения</Label>
                    {referencesQuery.isLoading ? (
                      <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
                        Загружаем кошельки...
                      </div>
                    ) : (
                      <Select value={effectiveWalletToId || "unselected"} onValueChange={(value) => setWalletToId(value === "unselected" ? "" : value)}>
                        <SelectTrigger id="autopayment-wallet-to" className="h-12 rounded-2xl bg-background/80 px-4">
                          <span className={effectiveWalletToId ? "truncate" : "truncate text-muted-foreground"}>
                            {selectedWalletToLabel}
                          </span>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="unselected">Не выбрано</SelectItem>
                          {destinationWallets.map((wallet) => (
                            <SelectItem key={wallet.id} value={wallet.id}>
                              {wallet.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label htmlFor="autopayment-cashflow-item">Статья расхода</Label>
                    {referencesQuery.isLoading ? (
                      <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
                        Загружаем статьи...
                      </div>
                    ) : (
                      <Select
                        value={effectiveCashFlowItemId || "unselected"}
                        onValueChange={(value) => setCashFlowItemId(value === "unselected" ? "" : value)}
                      >
                        <SelectTrigger id="autopayment-cashflow-item" className="h-12 rounded-2xl bg-background/80 px-4">
                          <span className={effectiveCashFlowItemId ? "truncate" : "truncate text-muted-foreground"}>
                            {selectedCashFlowItemLabel}
                          </span>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="unselected">Не выбрано</SelectItem>
                          {cashFlowItemOptions.map((item) => (
                            <SelectItem key={item.id} value={item.id}>
                              {item.name || "Без названия"}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    )}
                  </div>
                )}

                <div className="space-y-2">
                  <Label htmlFor="autopayment-description">Комментарий</Label>
                  <Textarea
                    id="autopayment-description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Коротко опиши сценарий, чтобы потом быстро отличать похожие правила"
                    rows={4}
                  />
                </div>

                <div className="flex flex-wrap gap-3">
                  <Button type="submit" disabled={autoPaymentMutation.isPending || referencesQuery.isLoading || referencesQuery.isError}>
                    <Save className="h-4 w-4" />
                    {autoPaymentMutation.isPending ? "Сохраняем..." : isEdit ? "Сохранить и выйти" : "Создать автоплатеж и выйти"}
                  </Button>
                  <Button asChild variant="outline" size="icon">
                    <Link href="/auto-payments" aria-label="Отмена" title="Отмена">
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
        kind="auto-payment"
        documentId={isEdit ? autoPayment?.id : undefined}
        graphicContract={autoPayment?.graphic_contract}
        draftRows={planningDraftRows ?? undefined}
        draftStorageKey={planningDraftStorageKey}
        onDraftRowsChange={setPlanningDraftRows}
        onTotalAmountChange={(nextAmount) => setAmount(String(nextAmount))}
        distributionSource={{
          totalAmount: hasAmount ? parsedAmount : 0,
          startDate: dateStart,
        }}
      />
    </div>
  )
}
