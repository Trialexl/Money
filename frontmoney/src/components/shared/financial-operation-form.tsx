"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDownRight, ArrowLeft, ArrowUpRight, Save, X } from "lucide-react"

import { useOperationReferenceDataQuery } from "@/hooks/use-reference-data"
import { PageHeader } from "@/components/shared/page-header"
import { PlanningGraphicsPanel } from "@/components/shared/planning-graphics-panel"
import { SearchableSelect, type SearchableSelectGroup, type SearchableSelectOption } from "@/components/shared/searchable-select"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { formatDateForInput } from "@/lib/formatters"
import { resolveReturnHref } from "@/lib/return-navigation"
import { CashFlowItemService } from "@/services/cash-flow-item-service"
import {
  Expenditure,
  ExpenditureService,
  Receipt,
  ReceiptService,
} from "@/services/financial-operations-service"
import { WalletService } from "@/services/wallet-service"
import { PlanningGraphicDraft, PlanningService } from "@/services/planning-service"

type OperationMode = "receipt" | "expenditure"
type OperationEntity = Receipt | Expenditure

interface FinancialOperationFormProps {
  mode: OperationMode
  operation?: OperationEntity
  isEdit?: boolean
}

const FORM_CONFIG = {
  receipt: {
    accentIcon: ArrowDownRight,
    badgeVariant: "success" as const,
    badgeLabel: "Приход",
    cancelHref: "/receipts",
    categoryLabel: "Статья прихода",
    createActionLabel: "Создать приход",
    editActionLabel: "Сохранить изменения",
    formTitle: "Параметры прихода",
    listQueryKey: "receipts",
    loadingReferenceLabel: "Загружаем кошельки и статьи...",
    newDescription:
      "Зафиксируй поступление денег: зарплата, возврат, перевод извне, продажа или любое другое пополнение кошелька.",
    newTitle: "Новый приход",
    pageEyebrow: "Движение денег",
    previewHint: "После сохранения операция попадет в ленту приходов и повлияет на баланс выбранного кошелька.",
    previewTitle: "Предпросмотр прихода",
    routeHref: "/receipts",
    submitErrorFallback: "Не удалось сохранить приход. Проверь поля и попробуй снова.",
  },
  expenditure: {
    accentIcon: ArrowUpRight,
    badgeVariant: "secondary" as const,
    badgeLabel: "Расход",
    cancelHref: "/expenditures",
    categoryLabel: "Статья расхода",
    createActionLabel: "Создать расход",
    editActionLabel: "Сохранить изменения",
    formTitle: "Параметры расхода",
    listQueryKey: "expenditures",
    loadingReferenceLabel: "Загружаем кошельки и статьи...",
    newDescription:
      "Зафиксируй отток денег: покупку, платеж, комиссию, снятие наличных или любую другую расходную операцию.",
    newTitle: "Новый расход",
    pageEyebrow: "Движение денег",
    previewHint: "Бюджетный флаг управляет тем, попадет ли операция в план-факт слой без дополнительных ручных действий.",
    previewTitle: "Предпросмотр расхода",
    routeHref: "/expenditures",
    submitErrorFallback: "Не удалось сохранить расход. Проверь поля и попробуй снова.",
  },
} as const

function isExpenditureOperation(operation: OperationEntity | undefined): operation is Expenditure {
  return Boolean(operation && "include_in_budget" in operation)
}

function normalizeLookupValue(value: string | null | undefined) {
  return (value ?? "").trim().toLocaleLowerCase("ru")
}

function toCashFlowItemOption(
  item: { id: string; name?: string | null; code?: string | null },
  description?: string
): SearchableSelectOption {
  return {
    value: item.id,
    label: item.name || "Без названия",
    description: description || (item.code ? `Код ${item.code}` : undefined),
    keywords: [item.code ?? ""],
  }
}

export default function FinancialOperationForm({
  mode,
  operation,
  isEdit = false,
}: FinancialOperationFormProps) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const config = FORM_CONFIG[mode]
  const AccentIcon = config.accentIcon
  const defaultWalletId = searchParams.get("wallet") || ""
  const defaultCashFlowItemId = searchParams.get("cash_flow_item") || ""
  const duplicateId = searchParams.get("duplicate")
  const returnToHref = searchParams.get("return_to")
  const cancelHref = resolveReturnHref(returnToHref, config.routeHref)
  const isDuplicateMode = Boolean(duplicateId) && !isEdit
  const planningDraftStorageKey = !isEdit && mode === "expenditure" ? "planning-draft:expenditure:new" : undefined

  const [amount, setAmount] = useState("")
  const [date, setDate] = useState(formatDateForInput())
  const [description, setDescription] = useState("")
  const [walletId, setWalletId] = useState<string | undefined>(undefined)
  const [cashFlowItemId, setCashFlowItemId] = useState<string | undefined>(undefined)
  const [includeInBudget, setIncludeInBudget] = useState(false)
  const [planningDraftRows, setPlanningDraftRows] = useState<PlanningGraphicDraft[] | null>(isEdit ? null : [])
  const [validationError, setValidationError] = useState<string | null>(null)

  useEffect(() => {
    setAmount(operation?.amount?.toString() || "")
    setDate(isDuplicateMode ? formatDateForInput() : operation?.date ? formatDateForInput(new Date(operation.date)) : formatDateForInput())
    setDescription(operation?.description || "")
    setWalletId(undefined)
    setCashFlowItemId(undefined)
    setIncludeInBudget(isExpenditureOperation(operation) ? operation.include_in_budget : false)
    setValidationError(null)
  }, [defaultCashFlowItemId, defaultWalletId, isDuplicateMode, operation])

  useEffect(() => {
    if (!planningDraftStorageKey) {
      setPlanningDraftRows(isEdit ? null : [])
      return
    }

    setPlanningDraftRows(PlanningService.getDraftRows(planningDraftStorageKey))
  }, [isEdit, planningDraftStorageKey])

  const referencesQuery = useOperationReferenceDataQuery()
  const sortedWallets = referencesQuery.wallets
  const baseWalletId = operation?.wallet || defaultWalletId || ""
  const baseCashFlowItemId = operation?.cash_flow_item || defaultCashFlowItemId || ""
  const recentItemsQuery = useQuery({
    queryKey: ["recent-operation-items", mode],
    enabled: !isEdit,
    queryFn: async () => {
      const operations = mode === "receipt" ? await ReceiptService.getReceipts() : await ExpenditureService.getExpenditures()
      const threshold = new Date()
      threshold.setHours(0, 0, 0, 0)
      threshold.setDate(threshold.getDate() - 60)

      return operations
        .filter((item) => !item.deleted)
        .filter((item) => {
          const operationDate = new Date(`${item.date}T12:00:00`)
          return !Number.isNaN(operationDate.getTime()) && operationDate >= threshold
        })
    },
    staleTime: 60_000,
  })
  const missingWalletQuery = useQuery({
    queryKey: ["wallet", "selected-fallback", walletId ?? baseWalletId],
    enabled: Boolean(walletId ?? baseWalletId) && !sortedWallets.some((wallet) => wallet.id === (walletId ?? baseWalletId)),
    queryFn: () => WalletService.getWallet((walletId ?? baseWalletId) as string),
    staleTime: 60_000,
  })
  const walletNameFallbackQuery = useQuery({
    queryKey: ["wallets", "selected-by-name", operation?.wallet_name ?? null],
    enabled: Boolean(operation?.wallet_name) && !baseWalletId && walletId == null,
    queryFn: () => WalletService.getWallets(),
    staleTime: 60_000,
  })
  const missingCashFlowItemQuery = useQuery({
    queryKey: ["cash-flow-item", "selected-fallback", cashFlowItemId ?? baseCashFlowItemId],
    enabled:
      Boolean(cashFlowItemId ?? baseCashFlowItemId) &&
      !referencesQuery.cashFlowItems.some((item) => item.id === (cashFlowItemId ?? baseCashFlowItemId)),
    queryFn: () => CashFlowItemService.getCashFlowItem((cashFlowItemId ?? baseCashFlowItemId) as string),
    staleTime: 60_000,
  })
  const cashFlowItemNameFallbackQuery = useQuery({
    queryKey: ["cash-flow-items", "selected-by-name", operation?.cash_flow_item_name ?? null],
    enabled: Boolean(operation?.cash_flow_item_name) && !baseCashFlowItemId && cashFlowItemId == null,
    queryFn: () => CashFlowItemService.getCashFlowItems(),
    staleTime: 60_000,
  })

  const matchedWalletByName = useMemo(
    () =>
      walletNameFallbackQuery.data?.find(
        (wallet) => normalizeLookupValue(wallet.name) === normalizeLookupValue(operation?.wallet_name)
      ),
    [operation?.wallet_name, walletNameFallbackQuery.data]
  )

  const effectiveWalletId = walletId ?? (baseWalletId || matchedWalletByName?.id || "")

  const walletOptions = useMemo(() => {
    const fallbackWallets = [...sortedWallets]

    if (missingWalletQuery.data && !fallbackWallets.some((wallet) => wallet.id === missingWalletQuery.data.id)) {
      fallbackWallets.push(missingWalletQuery.data)
    }

    if (matchedWalletByName && !fallbackWallets.some((wallet) => wallet.id === matchedWalletByName.id)) {
      fallbackWallets.push(matchedWalletByName)
    }

    return fallbackWallets.sort((left, right) => left.name.localeCompare(right.name, "ru"))
  }, [matchedWalletByName, missingWalletQuery.data, sortedWallets])

  const matchedCashFlowItemByName = useMemo(
    () =>
      cashFlowItemNameFallbackQuery.data?.find(
        (item) => normalizeLookupValue(item.name) === normalizeLookupValue(operation?.cash_flow_item_name)
      ),
    [cashFlowItemNameFallbackQuery.data, operation?.cash_flow_item_name]
  )

  const effectiveCashFlowItemId = cashFlowItemId ?? (baseCashFlowItemId || matchedCashFlowItemByName?.id || "")

  const cashFlowItems = useMemo(() => {
    const fallbackItems = [...referencesQuery.cashFlowItems]

    if (missingCashFlowItemQuery.data && !fallbackItems.some((item) => item.id === missingCashFlowItemQuery.data.id)) {
      fallbackItems.push(missingCashFlowItemQuery.data)
    }

    if (matchedCashFlowItemByName && !fallbackItems.some((item) => item.id === matchedCashFlowItemByName.id)) {
      fallbackItems.push(matchedCashFlowItemByName)
    }

    if (effectiveCashFlowItemId && !fallbackItems.some((item) => item.id === effectiveCashFlowItemId)) {
      fallbackItems.push({
        id: effectiveCashFlowItemId,
        name: operation?.cash_flow_item_name || "Загружаем статью",
        code: null,
        created_at: "",
        updated_at: "",
        deleted: false,
      })
    }

    return fallbackItems.sort((left, right) => (left.name ?? "").localeCompare(right.name ?? "", "ru"))
  }, [
    effectiveCashFlowItemId,
    matchedCashFlowItemByName,
    missingCashFlowItemQuery.data,
    operation?.cash_flow_item_name,
    referencesQuery.cashFlowItems,
  ])

  const cashFlowItemUsage = useMemo(() => {
    const usage = new Map<string, number>()
    for (const item of recentItemsQuery.data ?? []) {
      usage.set(item.cash_flow_item, (usage.get(item.cash_flow_item) ?? 0) + 1)
    }
    return usage
  }, [recentItemsQuery.data])

  const popularCashFlowItems = useMemo(
    () =>
      cashFlowItems
        .filter((item) => (cashFlowItemUsage.get(item.id) ?? 0) > 0)
        .sort((left, right) => {
          const usageDelta = (cashFlowItemUsage.get(right.id) ?? 0) - (cashFlowItemUsage.get(left.id) ?? 0)
          return usageDelta !== 0 ? usageDelta : (left.name ?? "").localeCompare(right.name ?? "", "ru")
        }),
    [cashFlowItemUsage, cashFlowItems]
  )

  const regularCashFlowItems = useMemo(
    () => cashFlowItems.filter((item) => !cashFlowItemUsage.has(item.id)),
    [cashFlowItemUsage, cashFlowItems]
  )
  const selectedWalletLabel = effectiveWalletId
    ? walletOptions.find((wallet) => wallet.id === effectiveWalletId)?.name || operation?.wallet_name || "Загружаем кошелек"
    : operation?.wallet_name || "Выбери кошелек"
  const cashFlowItemSelectGroups: SearchableSelectGroup[] = [
    {
      options: [{ value: "unselected", label: "Не выбрано" }],
    },
    popularCashFlowItems.length > 0
      ? {
          label: "Часто за 60 дней",
          options: popularCashFlowItems.map((item) =>
            toCashFlowItemOption(item, `${cashFlowItemUsage.get(item.id) ?? 0} операций`)
          ),
        }
      : null,
    {
      label: popularCashFlowItems.length > 0 ? "Все статьи" : "Статьи",
      options: regularCashFlowItems.map((item) => toCashFlowItemOption(item)),
    },
  ].filter(Boolean) as SearchableSelectGroup[]

  const operationMutation = useMutation({
    mutationFn: async () => {
      const parsedAmount = Number.parseFloat(amount)

      if (mode === "receipt") {
        const payload: Partial<Receipt> = {
          amount: parsedAmount,
          date,
          description: description.trim() || undefined,
          wallet: effectiveWalletId,
          cash_flow_item: effectiveCashFlowItemId,
        }

        if (isEdit && operation) {
          return ReceiptService.updateReceipt(operation.id, payload)
        }

        return ReceiptService.createReceipt(payload)
      }

      const payload: Partial<Expenditure> = {
        amount: parsedAmount,
        date,
        description: description.trim() || undefined,
        wallet: effectiveWalletId,
        cash_flow_item: effectiveCashFlowItemId,
        include_in_budget: includeInBudget,
      }

      if (isEdit && operation) {
        return ExpenditureService.updateExpenditure(operation.id, payload)
      }

      return ExpenditureService.createExpenditure(payload)
    },
    onSuccess: async (savedOperation) => {
      const shouldReplacePlanningRows =
        mode === "expenditure" && savedOperation.id && (isEdit ? planningDraftRows !== null : Boolean(planningDraftRows?.length))

      if (shouldReplacePlanningRows) {
        await PlanningService.replaceGraphicsRows("expenditure", savedOperation.id, planningDraftRows ?? [])
        if (planningDraftStorageKey) {
          PlanningService.clearDraftRows(planningDraftStorageKey)
        }
      }

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: [config.listQueryKey] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] }),
        queryClient.invalidateQueries({ queryKey: ["wallets"] }),
      ])
      router.push(resolveReturnHref(returnToHref, config.routeHref, savedOperation.id || operation?.id, { resetPage: !isEdit }))
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setValidationError(null)

    const parsedAmount = Number.parseFloat(amount)

    if (!effectiveWalletId || !effectiveCashFlowItemId || !date || Number.isNaN(parsedAmount) || parsedAmount <= 0) {
      setValidationError("Укажи дату, сумму, кошелек и статью. Сумма должна быть больше нуля.")
      return
    }

    try {
      await operationMutation.mutateAsync()
    } catch {}
  }

  const numericAmount = Number.parseFloat(amount)
  const hasAmount = !Number.isNaN(numericAmount) && numericAmount > 0
  const errorMessage =
    validationError ||
    (operationMutation.error as any)?.response?.data?.detail ||
    (operationMutation.error ? config.submitErrorFallback : null) ||
    null

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={config.pageEyebrow}
        title={isEdit ? `Редактирование ${mode === "receipt" ? "прихода" : "расхода"}` : config.newTitle}
        description={isEdit ? config.previewHint : config.newDescription}
        actions={
          <Button asChild variant="outline" size="icon">
            <Link href={cancelHref} aria-label="К списку" title="К списку">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
        }
      />

      <div>
        <Card>
          <CardHeader>
            <CardTitle>{config.formTitle}</CardTitle>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-5 rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-2.5 text-sm leading-5 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            {referencesQuery.isError ? (
              <div className="rounded-[18px] border border-destructive/20 bg-destructive/10 px-3 py-3 text-sm leading-5 text-destructive">
                Не удалось загрузить справочники для формы. Проверь backend API и попробуй обновить страницу.
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-5">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor={`${mode}-amount`}>Сумма</Label>
                    <Input
                      id={`${mode}-amount`}
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
                    <Label htmlFor={`${mode}-date`}>Дата операции</Label>
                    <Input
                      id={`${mode}-date`}
                      type="date"
                      value={date}
                      onChange={(event) => setDate(event.target.value)}
                      required
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor={`${mode}-wallet`}>Кошелек</Label>
                    {referencesQuery.isLoading ? (
                      <div className="rounded-[16px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
                        {config.loadingReferenceLabel}
                      </div>
                    ) : (
                      <Select value={effectiveWalletId || "unselected"} onValueChange={(value) => setWalletId(value === "unselected" ? "" : value)}>
                        <SelectTrigger id={`${mode}-wallet`} className="h-11 rounded-xl bg-background/80 px-3">
                          <span className={effectiveWalletId ? "truncate" : "truncate text-muted-foreground"}>
                            {selectedWalletLabel}
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
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor={`${mode}-category`}>{config.categoryLabel}</Label>
                  {referencesQuery.isLoading ? (
                      <div className="rounded-[16px] border border-border/70 bg-background/70 px-3 py-2.5 text-sm text-muted-foreground">
                        {config.loadingReferenceLabel}
                      </div>
                    ) : (
                    <SearchableSelect
                      id={`${mode}-category`}
                      value={effectiveCashFlowItemId || "unselected"}
                      onValueChange={(value) => setCashFlowItemId(value === "unselected" ? "" : value)}
                      groups={cashFlowItemSelectGroups}
                      placeholder="Выбери статью"
                      searchPlaceholder="Найти статью по названию или коду"
                      emptyLabel="Статья не найдена"
                    />
                  )}
                  {popularCashFlowItems.length > 0 ? (
                    <p className="text-xs leading-4 text-muted-foreground">Сверху показаны самые частые статьи за последние 60 дней.</p>
                  ) : null}
                </div>

                <div className="space-y-2">
                  <Label htmlFor={`${mode}-description`}>Комментарий</Label>
                  <Textarea
                    id={`${mode}-description`}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="Короткая пометка, чтобы потом быстро понять суть операции"
                    rows={4}
                  />
                </div>

                {mode === "expenditure" ? (
                  <div className="flex items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 px-3 py-3">
                    <Checkbox
                      id="expenditure-budget"
                      checked={includeInBudget}
                      onCheckedChange={(value) => setIncludeInBudget(Boolean(value))}
                      className="mt-1"
                    />
                    <div>
                      <Label htmlFor="expenditure-budget" className="cursor-pointer">
                        Включать в бюджет
                      </Label>
                    </div>
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-3">
                  <Button
                    type="submit"
                    disabled={operationMutation.isPending || referencesQuery.isLoading || referencesQuery.isError}
                  >
                    <Save className="h-4 w-4" />
                    {operationMutation.isPending
                      ? "Сохраняем..."
                      : isEdit
                        ? "Сохранить и выйти"
                        : mode === "receipt"
                          ? "Создать приход и выйти"
                          : "Создать расход и выйти"}
                  </Button>
                  <Button asChild variant="outline" size="icon">
                    <Link href={cancelHref} aria-label="Отмена" title="Отмена">
                      <X className="h-4 w-4" />
                    </Link>
                  </Button>
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      </div>

      {mode === "expenditure" ? (
        <PlanningGraphicsPanel
          kind="expenditure"
          documentId={isEdit ? operation?.id : undefined}
          graphicContract={operation?.graphic_contract}
          draftRows={planningDraftRows ?? undefined}
          draftStorageKey={planningDraftStorageKey}
          onDraftRowsChange={setPlanningDraftRows}
          onTotalAmountChange={(nextAmount) => setAmount(String(nextAmount))}
          distributionSource={{
            totalAmount: hasAmount ? numericAmount : 0,
            startDate: date,
          }}
        />
      ) : null}
    </div>
  )
}
