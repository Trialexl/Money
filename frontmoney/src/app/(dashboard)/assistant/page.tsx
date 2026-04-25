"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import {
  Bot,
  CheckCircle2,
  Copy,
  ImagePlus,
  Link2,
  Loader2,
  RefreshCw,
  ScanSearch,
  SendHorizonal,
  Sparkles,
  Wallet2,
} from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useActiveWalletsQuery } from "@/hooks/use-reference-data"
import { formatCurrency, formatDate } from "@/lib/formatters"
import { AiService, type AiAssistantResponse, type TelegramLinkTokenResponse } from "@/services/ai-service"

type HistoryEntry = {
  id: string
  request: {
    text: string
    dryRun: boolean
    walletId?: string
    imageFile?: File | null
    imageName?: string
  }
  response: AiAssistantResponse
}

type OptionChoice = {
  label: string
  value: string
}

const QUICK_PROMPTS = [
  "Расход с карты на продукты 2450",
  "Перевод со Сбера на Альфу 12000",
  "Покажи остатки по кошелькам",
  "Подготовь предпросмотр по скриншоту",
]

function formatConfidence(value: number) {
  return `${Math.round(value * 100)}%`
}

function getStatusTone(status: AiAssistantResponse["status"]) {
  if (status === "created") return "success"
  if (status === "duplicate") return "secondary"
  if (status === "needs_confirmation") return "outline"
  if (status === "info") return "secondary"
  return "secondary"
}

function getStatusLabel(status: AiAssistantResponse["status"]) {
  if (status === "created") return "Создано"
  if (status === "preview") return "Предпросмотр"
  if (status === "needs_confirmation") return "Нужно уточнение"
  if (status === "balance") return "Остатки"
  if (status === "duplicate") return "Дубликат"
  if (status === "info") return "Справка"
  return status
}

function modelToRoute(model?: string) {
  const normalized = (model ?? "").toLowerCase()
  if (normalized === "receipt") return "receipts"
  if (normalized === "expenditure") return "expenditures"
  if (normalized === "transfer") return "transfers"
  return null
}

function extractOptionChoices(input: AiAssistantResponse["options"]): OptionChoice[] {
  if (!input) {
    return []
  }

  if (Array.isArray(input)) {
    return input
      .map((item, index) => {
        if (typeof item === "string" || typeof item === "number") {
          return {
            label: String(item),
            value: String(item),
          }
        }

        if (item && typeof item === "object") {
          const candidate = item as Record<string, unknown>
          const value = String(candidate.value ?? candidate.id ?? candidate.code ?? index + 1)
          const label = String(candidate.label ?? candidate.name ?? candidate.title ?? value)
          return { label, value }
        }

        return null
      })
      .filter((item): item is OptionChoice => Boolean(item))
  }

  if (typeof input === "object") {
    return Object.entries(input).map(([key, value]) => ({
      label: typeof value === "string" ? value : key,
      value: key,
    }))
  }

  return []
}

function JsonPreview({ value }: { value: unknown }) {
  if (!value || (typeof value === "object" && Object.keys(value as Record<string, unknown>).length === 0)) {
    return null
  }

  return (
    <pre className="overflow-x-auto rounded-[20px] border border-border/70 bg-background/80 p-4 text-xs leading-6 text-muted-foreground">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export default function AssistantPage() {
  const walletsQuery = useActiveWalletsQuery()
  const [text, setText] = useState("")
  const [walletId, setWalletId] = useState<string>("all")
  const [dryRun, setDryRun] = useState(false)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [telegramToken, setTelegramToken] = useState<TelegramLinkTokenResponse | null>(null)
  const [copyState, setCopyState] = useState<"idle" | "done">("idle")
  const [dataView, setDataView] = useState<"preview" | "parsed">("preview")

  const wallets = walletsQuery.data ?? []
  const selectedWallet = wallets.find((wallet) => wallet.id === walletId)
  const latestEntry = history[0] ?? null
  const latestResponse = latestEntry?.response ?? null
  const optionChoices = useMemo(() => extractOptionChoices(latestResponse?.options), [latestResponse?.options])
  const isAwaitingClarification = latestResponse?.status === "needs_confirmation"
  const inputLabel = isAwaitingClarification ? "Ответ ассистенту" : "Запрос"
  const inputPlaceholder = isAwaitingClarification
    ? "Например: 1, Сбер, 2500, коммуналка, /cancel"
    : "Например: расход сбер еда 2500, перевод альфа сбер 12000, остатки по кошелькам"
  const submitLabel = isAwaitingClarification ? "Отправить уточнение" : "Отправить ассистенту"
  const createdCount = history.filter((entry) => entry.response.status === "created").length
  const clarificationCount = history.filter((entry) => entry.response.status === "needs_confirmation").length
  const previewCount = history.filter((entry) => entry.response.status === "preview").length
  const latestRoute = latestResponse?.created_object ? modelToRoute(latestResponse.created_object.model) : null
  const hasPreviewData = Boolean(latestResponse?.preview && Object.keys(latestResponse.preview).length > 0)
  const hasParsedData = Boolean(latestResponse?.parsed && Object.keys(latestResponse.parsed).length > 0)
  const canConfirmPreview = latestResponse?.status === "preview" && Boolean(latestEntry)

  const buildRequestSnapshot = () => ({
    text: text.trim(),
    dryRun,
    walletId: walletId !== "all" ? walletId : undefined,
    imageFile,
    imageName: imageFile?.name,
  })

  const appendHistoryEntry = (
    request: HistoryEntry["request"],
    response: AiAssistantResponse
  ) => {
    setHistory((current) => [
      {
        id: crypto.randomUUID(),
        request,
        response,
      },
      ...current,
    ])
  }

  const executeMutation = useMutation({
    mutationFn: async (request: HistoryEntry["request"]) =>
      AiService.execute({
        text: request.text || undefined,
        wallet: request.walletId,
        dryRun: request.dryRun,
        image: request.imageFile ?? null,
      }),
    onSuccess: (response, request) => {
      appendHistoryEntry(request, response)

      if (response.status !== "needs_confirmation") {
        setText("")
      }

      setImageFile(null)
    },
  })

  const confirmPreviewMutation = useMutation({
    mutationFn: async (entry: HistoryEntry) =>
      AiService.execute({
        text: entry.request.text || undefined,
        wallet: entry.request.walletId,
        dryRun: false,
        image: entry.request.imageFile ?? null,
      }),
    onSuccess: (response, entry) => {
      appendHistoryEntry(
        {
          ...entry.request,
          dryRun: false,
        },
        response
      )
    },
  })

  const telegramMutation = useMutation({
    mutationFn: AiService.createTelegramLinkToken,
    onSuccess: (token) => {
      setTelegramToken(token)
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!text.trim() && !imageFile) {
      return
    }

    await executeMutation.mutateAsync(buildRequestSnapshot())
  }

  const handleApplyOption = (choice: OptionChoice) => {
    setText(choice.value)
  }

  const handleConfirmPreview = async () => {
    if (!latestEntry) {
      return
    }

    await confirmPreviewMutation.mutateAsync(latestEntry)
  }

  const handleCopyCode = async () => {
    if (!telegramToken?.code) {
      return
    }

    await navigator.clipboard.writeText(telegramToken.code)
    setCopyState("done")
    window.setTimeout(() => setCopyState("idle"), 1500)
  }

  if (walletsQuery.isError) {
    return (
        <EmptyState
        icon={Bot}
        title="AI-ассистент пока недоступен"
        description="Не удалось загрузить данные, которые нужны ассистенту для работы с кошельками и операциями. Проверь API и попробуй снова."
        action={<Button onClick={() => walletsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Ассистент"
        title="Ассистент операций"
        description="Ввод операций текстом или по скриншоту."
      />

      {isAwaitingClarification ? (
        <Card className="border-primary/20 bg-primary/5">
          <CardHeader>
            <CardTitle>Нужно уточнение, чтобы продолжить</CardTitle>
            <CardDescription>Ответь на вопрос или выбери вариант.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-[18px] border border-border/70 bg-background/80 p-3 text-sm leading-5">
              {latestResponse?.reply_text}
            </div>

            {latestResponse?.missing_fields?.length ? (
              <div className="space-y-2">
                <div className="text-sm font-medium">Что нужно уточнить</div>
                <div className="flex flex-wrap gap-2">
                  {latestResponse.missing_fields.map((field) => (
                    <Badge key={field} variant="outline">{field}</Badge>
                  ))}
                </div>
              </div>
            ) : null}

            {optionChoices.length ? (
              <div className="space-y-3">
                <div className="text-sm font-medium">Быстрый ответ</div>
                <div className="flex flex-wrap gap-2">
                  {optionChoices.map((choice) => (
                    <Button key={`${choice.value}-${choice.label}`} type="button" variant="outline" size="sm" onClick={() => handleApplyOption(choice)}>
                      {choice.label}
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="text-sm leading-5 text-muted-foreground">
              После ответа ассистент продолжит текущий сценарий.
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Последний статус"
          value={latestResponse ? getStatusLabel(latestResponse.status) : "Нет данных"}
          hint={latestResponse ? latestResponse.intent : "Отправь запрос ассистенту"}
          icon={Sparkles}
          tone={latestResponse?.status === "created" ? "positive" : latestResponse?.status === "balance" ? "positive" : "neutral"}
        />
        <StatCard
          label="Создано за сессию"
          value={String(createdCount)}
          hint={clarificationCount > 0 ? `${clarificationCount} запросов ждут уточнения` : "Без зависших сценариев"}
          icon={CheckCircle2}
          tone={createdCount > 0 ? "positive" : "neutral"}
        />
        <StatCard
          label="Предпросмотров"
          value={String(previewCount)}
          hint={latestResponse ? `Уверенность ${formatConfidence(latestResponse.confidence)}` : "Появится после первого ответа"}
          icon={ScanSearch}
        />
        <StatCard
          label="Код Telegram"
          value={telegramToken?.code || "Не создан"}
          hint={telegramToken ? `До ${formatDate(telegramToken.expires_at)}` : "Сгенерируй одноразовый код"}
          icon={Link2}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <Card>
          <CardHeader>
            <CardTitle>{isAwaitingClarification ? "Ответ ассистенту" : "Новый запрос"}</CardTitle>
            <CardDescription>
              {isAwaitingClarification
                ? "Уточни данные, выбери вариант или отмени `/cancel`."
                : "Опиши операцию, приложи изображение или запроси остатки."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-5" onSubmit={handleSubmit}>
              {!isAwaitingClarification ? (
                <div className="space-y-3">
                  <div className="text-sm font-medium">Быстрый старт</div>
                  <div className="flex flex-wrap gap-2">
                    {QUICK_PROMPTS.map((prompt) => (
                      <Button key={prompt} type="button" variant="outline" size="sm" onClick={() => setText(prompt)}>
                        {prompt}
                      </Button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="space-y-2">
                <Label htmlFor="assistant-text">{inputLabel}</Label>
                <Textarea
                  id="assistant-text"
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  placeholder={inputPlaceholder}
                />
              </div>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
                <div className="space-y-2">
                  <Label htmlFor="assistant-wallet">Контекст кошелька</Label>
                  <Select value={walletId} onValueChange={setWalletId}>
                    <SelectTrigger id="assistant-wallet">
                      <SelectValue placeholder="Без привязки к конкретному кошельку" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Без привязки</SelectItem>
                      {wallets.map((wallet) => (
                        <SelectItem key={wallet.id} value={wallet.id}>
                          {wallet.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs leading-4 text-muted-foreground">
                    {selectedWallet ? `Запрос будет связан с кошельком «${selectedWallet.name}».` : "Подходит для общих запросов, когда конкретный кошелек не нужен."}
                  </p>
                </div>

                <div className="space-y-3 rounded-[18px] border border-border/70 bg-background/70 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium">Режим предпросмотра</div>
                      <div className="mt-1 text-xs leading-4 text-muted-foreground">
                        {isAwaitingClarification
                          ? "Для уточнения обычно не нужен."
                          : "Сначала покажет, что понял из запроса."}
                      </div>
                    </div>
                    <Switch checked={dryRun} onCheckedChange={setDryRun} />
                  </div>
                </div>
              </div>

              <div className="space-y-3 rounded-[18px] border border-dashed border-border/80 bg-background/60 p-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <ImagePlus className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-sm font-medium">Банковский скриншот</div>
                    <div className="text-xs leading-4 text-muted-foreground">Ассистент попробует распознать данные автоматически.</div>
                  </div>
                </div>
                <Input
                  type="file"
                  accept="image/*"
                  onChange={(event) => setImageFile(event.target.files?.[0] ?? null)}
                />
                {imageFile ? (
                  <div className="flex items-center justify-between gap-3 rounded-[16px] border border-border/70 bg-card/70 px-3 py-2.5 text-sm">
                    <span className="truncate">{imageFile.name}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => setImageFile(null)}>
                      Убрать
                    </Button>
                  </div>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={executeMutation.isPending || (!text.trim() && !imageFile)}>
                  {executeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizonal className="h-4 w-4" />}
                  {executeMutation.isPending ? "Отправляем..." : submitLabel}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setText("")
                    setWalletId("all")
                    setDryRun(false)
                    setImageFile(null)
                  }}
                >
                  Сбросить
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Как использовать</CardTitle>
              <CardDescription>Три быстрых сценария.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="rounded-[18px] border border-border/60 bg-background/70 p-3">
                <div className="text-sm font-medium text-foreground">1. Быстрый ввод текстом</div>
                <div className="mt-1 text-sm leading-5 text-muted-foreground">Короткой фразы обычно достаточно для создания документа.</div>
              </div>
              <div className="rounded-[18px] border border-border/60 bg-background/70 p-3">
                <div className="text-sm font-medium text-foreground">2. Скриншот банка</div>
                <div className="mt-1 text-sm leading-5 text-muted-foreground">Добавь изображение, если так быстрее.</div>
              </div>
              <div className="rounded-[18px] border border-border/60 bg-background/70 p-3">
                <div className="text-sm font-medium text-foreground">3. Уточнение без потери контекста</div>
                <div className="mt-1 text-sm leading-5 text-muted-foreground">Если данных не хватает, ассистент доведёт сценарий до конца.</div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Привязка Telegram</CardTitle>
              <CardDescription>Сгенерируй код и отправь `/link CODE` боту.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-[18px] border border-border/70 bg-background/70 p-4">
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Текущий код</div>
                <div className="mt-2 text-2xl font-semibold tracking-[0.12em]">
                  {telegramToken?.code || "------"}
                </div>
                <div className="mt-2 text-sm text-muted-foreground">
                  {telegramToken ? `Истекает ${formatDate(telegramToken.expires_at)}` : "Код ещё не создан"}
                </div>
              </div>
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => telegramMutation.mutate()} disabled={telegramMutation.isPending}>
                  {telegramMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  {telegramToken ? "Обновить код" : "Создать код"}
                </Button>
                <Button type="button" variant="outline" onClick={handleCopyCode} disabled={!telegramToken?.code}>
                  {copyState === "done" ? <CheckCircle2 className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copyState === "done" ? "Скопировано" : "Скопировать"}
                </Button>
              </div>
            </CardContent>
          </Card>

          {latestResponse ? (
            <Card>
              <CardHeader>
                <CardTitle>Последний ответ ассистента</CardTitle>
                <CardDescription>Что понял ассистент и что делать дальше.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge variant={getStatusTone(latestResponse.status) as "success" | "secondary" | "outline"}>{getStatusLabel(latestResponse.status)}</Badge>
                  <Badge variant="outline">{latestResponse.intent}</Badge>
                  <Badge variant="outline">Источник: {latestResponse.provider}</Badge>
                  <Badge variant="outline">Уверенность {formatConfidence(latestResponse.confidence)}</Badge>
                </div>

                <div className="rounded-[18px] border border-border/70 bg-background/80 p-3 text-sm leading-5">
                  {latestResponse.reply_text || "Ассистент не вернул текстового пояснения."}
                </div>

                {canConfirmPreview ? (
                  <div className="rounded-[18px] border border-primary/20 bg-primary/5 p-3">
                    <div className="text-sm font-medium text-foreground">Предпросмотр готов к созданию</div>
                    <div className="mt-2 text-sm leading-5 text-muted-foreground">
                      Если разбор корректный, создай документ из этого же запроса.
                    </div>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <Button type="button" onClick={handleConfirmPreview} disabled={confirmPreviewMutation.isPending}>
                        {confirmPreviewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        {confirmPreviewMutation.isPending ? "Создаем..." : "Подтвердить и создать"}
                      </Button>
                      {latestEntry?.request.text ? (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => {
                            setText(latestEntry.request.text)
                            setWalletId(latestEntry.request.walletId || "all")
                            setDryRun(true)
                          }}
                        >
                          Вернуть в форму
                        </Button>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {latestResponse.created_object ? (
                  <div className="rounded-[18px] border border-emerald-500/20 bg-emerald-500/10 p-3 text-sm">
                    <div className="font-medium text-foreground">
                      Документ создан: #{latestResponse.created_object.number}
                    </div>
                    <div className="mt-2 text-muted-foreground">
                      Ассистент завершил сценарий и уже положил документ в рабочий раздел.
                    </div>
                    {latestRoute ? (
                      <Button asChild variant="outline" size="sm" className="mt-4">
                        <Link href={`/${latestRoute}/${latestResponse.created_object.id}/edit`}>Открыть документ</Link>
                      </Button>
                    ) : null}
                  </div>
                ) : null}

                {latestResponse.missing_fields?.length && !isAwaitingClarification ? (
                  <div className="space-y-2">
                    <div className="text-sm font-medium">Не хватает полей</div>
                    <div className="flex flex-wrap gap-2">
                      {latestResponse.missing_fields.map((field) => (
                        <Badge key={field} variant="outline">{field}</Badge>
                      ))}
                    </div>
                  </div>
                ) : null}

                {optionChoices.length && !isAwaitingClarification ? (
                  <div className="space-y-3">
                    <div className="text-sm font-medium">Варианты уточнения</div>
                    <div className="flex flex-wrap gap-2">
                      {optionChoices.map((choice) => (
                        <Button key={`${choice.value}-${choice.label}`} type="button" variant="outline" size="sm" onClick={() => handleApplyOption(choice)}>
                          {choice.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {latestResponse.balances?.length ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Wallet2 className="h-4 w-4 text-primary" />
                      Остатки
                    </div>
                    <div className="space-y-2">
                      {latestResponse.balances.map((row) => (
                        <div key={row.wallet_id} className="flex items-center justify-between rounded-[18px] border border-border/70 bg-background/70 px-4 py-3 text-sm">
                          <span>{row.wallet_name}</span>
                          <span className="font-medium">{formatCurrency(row.balance)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {hasPreviewData || hasParsedData ? (
                  <div className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-sm font-medium">Данные запроса</div>
                      <div className="flex gap-2 rounded-[20px] border border-border/70 bg-background/70 p-1">
                        {hasPreviewData ? (
                          <Button type="button" size="sm" variant={dataView === "preview" ? "default" : "ghost"} onClick={() => setDataView("preview")}>
                            Предпросмотр
                          </Button>
                        ) : null}
                        {hasParsedData ? (
                          <Button type="button" size="sm" variant={dataView === "parsed" ? "default" : "ghost"} onClick={() => setDataView("parsed")}>
                            Разбор
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    <JsonPreview value={dataView === "parsed" && hasParsedData ? latestResponse.parsed : latestResponse.preview} />
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>История запросов</CardTitle>
          <CardDescription>Локальный журнал текущей сессии. Помогает не терять контекст, если ассистент просит уточнение или показывает предпросмотр.</CardDescription>
        </CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-border/70 px-5 py-12 text-center text-sm text-muted-foreground">
              История пока пустая. Отправь первый запрос ассистенту.
            </div>
          ) : (
            <div className="space-y-3">
              {history.map((entry) => (
                <div key={entry.id} className="rounded-[24px] border border-border/70 bg-background/70 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={getStatusTone(entry.response.status) as "success" | "secondary" | "outline"}>{getStatusLabel(entry.response.status)}</Badge>
                        {entry.request.dryRun ? <Badge variant="outline">Предпросмотр</Badge> : null}
                        {entry.request.walletId ? <Badge variant="outline">Кошелек</Badge> : null}
                        {entry.request.imageName ? <Badge variant="outline">Изображение</Badge> : null}
                      </div>
                      <div className="text-sm font-medium text-foreground">{entry.request.text || "Запрос без текста"}</div>
                      {entry.request.imageName ? <div className="text-xs text-muted-foreground">Файл: {entry.request.imageName}</div> : null}
                    </div>
                    <div className="text-right text-sm text-muted-foreground">
                      <div>{entry.response.provider}</div>
                      <div>Уверенность {formatConfidence(entry.response.confidence)}</div>
                    </div>
                  </div>
                  <div className="mt-3 rounded-[18px] border border-border/60 bg-card/70 px-4 py-3 text-sm leading-6">
                    {entry.response.reply_text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
