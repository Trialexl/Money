"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Bot, FileImage, Loader2, SendHorizontal, X } from "lucide-react"

import { AssistantReply } from "@/components/shared/assistant-reply"
import { DocumentEditDialog, type EditableDocumentKind } from "@/components/shared/document-edit-dialog"
import { PageHeader } from "@/components/shared/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { AiService, type AiAssistantMode, type AiAssistantResponse } from "@/services/ai-service"

type ChatRequest = {
  text: string
  image?: File | null
  imageName?: string
}

type ChatTurn = {
  id: string
  request: ChatRequest
  response: AiAssistantResponse
}

type OptionChoice = {
  label: string
  value: string
}

const QUICK_PROMPTS = [
  "Остатки по кошелькам",
  "Расходы июль",
  "Бюджет июль",
  "Покажи портфель",
]

function getStatusLabel(status: AiAssistantResponse["status"]) {
  if (status === "created") return "Готово"
  if (status === "needs_confirmation") return "Нужен ответ"
  if (status === "duplicate") return "Повтор"
  if (status === "balance") return "Остатки"
  if (status === "info") return "Ответ"
  return "Предпросмотр"
}

function modelToEditableKind(model?: string): EditableDocumentKind | null {
  const normalized = (model ?? "").toLowerCase()
  if (normalized === "receipt") return "receipt"
  if (normalized === "expenditure") return "expenditure"
  if (normalized === "transfer") return "transfer"
  return null
}

function parseOption(item: unknown, fallbackValue: string): OptionChoice | null {
  if (typeof item === "string" || typeof item === "number") {
    return { label: String(item), value: String(item) }
  }
  if (!item || typeof item !== "object") {
    return null
  }
  const candidate = item as Record<string, unknown>
  const label = String(candidate.label ?? candidate.name ?? candidate.title ?? candidate.value ?? fallbackValue)
  return {
    label,
    value: String(candidate.value ?? candidate.label ?? candidate.name ?? candidate.id ?? fallbackValue),
  }
}

function extractOptionChoices(input: AiAssistantResponse["options"]): OptionChoice[] {
  if (!input) return []

  const choices: OptionChoice[] = []
  if (Array.isArray(input)) {
    input.forEach((item, index) => {
      const choice = parseOption(item, String(index + 1))
      if (choice) choices.push(choice)
    })
  } else if (typeof input === "object") {
    Object.entries(input).forEach(([key, value]) => {
      if (Array.isArray(value)) {
        value.forEach((item, index) => {
          const choice = parseOption(item, `${key}-${index + 1}`)
          if (choice) choices.push(choice)
        })
        return
      }
      const choice = parseOption(value, key)
      if (choice) choices.push(choice)
    })
  }

  return choices.filter(
    (choice, index) => choices.findIndex((candidate) => candidate.label === choice.label) === index
  )
}

function responseChoices(response: AiAssistantResponse | null): OptionChoice[] {
  if (!response || response.status !== "needs_confirmation") return []
  if (response.missing_fields?.length === 1 && response.missing_fields[0] === "final_confirmation") {
    return [
      { label: "Создать", value: "Создать" },
      { label: "Отмена", value: "/cancel" },
    ]
  }
  return [
    ...extractOptionChoices(response.options),
    { label: "Отмена", value: "/cancel" },
  ]
}

export default function AssistantPage() {
  const [mode, setMode] = useState<AiAssistantMode>("classic")
  const [text, setText] = useState("")
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [editingDocument, setEditingDocument] = useState<{ kind: EditableDocumentKind; id: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const conversationEndRef = useRef<HTMLDivElement>(null)

  const latestResponse = turns.at(-1)?.response ?? null
  const choices = useMemo(() => responseChoices(latestResponse), [latestResponse])
  const awaitingAnswer = latestResponse?.status === "needs_confirmation"

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [turns, imageFile])

  const executeMutation = useMutation({
    mutationFn: (request: ChatRequest) =>
      AiService.execute({
        text: request.text || undefined,
        image: request.image ?? null,
        conversation: true,
        mode,
      }),
    onSuccess: (response, request) => {
      setTurns((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          request,
          response,
        },
      ])
    },
  })

  const sendMessage = async (messageText = text) => {
    const request: ChatRequest = {
      text: messageText.trim(),
      image: imageFile,
      imageName: imageFile?.name,
    }
    if ((!request.text && !request.image) || executeMutation.isPending) return

    setText("")
    setImageFile(null)
    try {
      await executeMutation.mutateAsync(request)
    } catch {
      setText(request.text)
      setImageFile(request.image ?? null)
    }
  }

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    void sendMessage()
  }

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Ассистент" title="Диалог" description="Вопрос и ответ" compact />

      <div className="flex flex-wrap items-center gap-2" aria-label="Режим ассистента">
        <Button
          type="button"
          variant={mode === "classic" ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("classic")}
          disabled={executeMutation.isPending}
        >
          Обычный
        </Button>
        <Button
          type="button"
          variant={mode === "agent" ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("agent")}
          disabled={executeMutation.isPending}
        >
          Умный режим
        </Button>
        <span className="text-sm text-muted-foreground">
          {mode === "agent" ? "Сам выбирает нужные действия" : "Текущий сценарий ассистента"}
        </span>
      </div>

      <Card className="overflow-hidden">
        <div className="flex min-h-[68vh] flex-col">
          <div className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-6">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                <Bot className="h-4 w-4" />
              </div>
              <div className="max-w-[min(88%,760px)] rounded-md border border-border/70 bg-muted/45 px-4 py-3 text-sm leading-6">
                {mode === "agent"
                  ? "Опишите результат или приложите скриншот — я выберу нужные действия."
                  : "Напишите сообщение."}
              </div>
            </div>

            {turns.length === 0 ? (
              <div className="flex flex-wrap gap-2 pl-12">
                {QUICK_PROMPTS.map((prompt) => (
                  <Button key={prompt} type="button" variant="outline" size="sm" onClick={() => void sendMessage(prompt)}>
                    {prompt}
                  </Button>
                ))}
              </div>
            ) : null}

            {turns.map((turn, turnIndex) => {
              const createdObjects = turn.response.created_objects?.length
                ? turn.response.created_objects
                : turn.response.created_object
                  ? [turn.response.created_object]
                  : []
              const isLatest = turnIndex === turns.length - 1

              return (
                <div key={turn.id} className="space-y-4">
                  <div className="flex justify-end">
                    <div className="max-w-[min(88%,760px)] rounded-md bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground">
                      {turn.request.text ? <div className="whitespace-pre-wrap break-words">{turn.request.text}</div> : null}
                      {turn.request.imageName ? (
                        <div className="mt-2 flex items-center gap-2 text-xs opacity-85">
                          <FileImage className="h-4 w-4" />
                          <span className="truncate">{turn.request.imageName}</span>
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <Bot className="h-4 w-4" />
                    </div>
                    <div className="max-w-[min(88%,760px)] space-y-3 rounded-md border border-border/70 bg-muted/45 px-4 py-3 text-sm leading-6">
                      <AssistantReply response={turn.response} />
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={turn.response.status === "created" ? "success" : "secondary"}>
                          {getStatusLabel(turn.response.status)}
                        </Badge>
                        {createdObjects.map((item) => {
                          const kind = modelToEditableKind(item.model)
                          return kind ? (
                            <Button
                              key={item.id}
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => setEditingDocument({ kind, id: item.id })}
                            >
                              Открыть #{item.number}
                            </Button>
                          ) : null
                        })}
                      </div>
                      {isLatest && choices.length ? (
                        <div className="flex flex-wrap gap-2 pt-1">
                          {choices.slice(0, 9).map((choice) => (
                            <Button
                              key={`${choice.label}-${choice.value}`}
                              type="button"
                              variant={choice.value === "/cancel" ? "outline" : "default"}
                              size="sm"
                              disabled={executeMutation.isPending}
                              onClick={() => void sendMessage(choice.value)}
                            >
                              {choice.label}
                            </Button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              )
            })}

            {executeMutation.isPending ? (
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                  <Bot className="h-4 w-4" />
                </div>
                <div className="flex items-center gap-2 rounded-md border border-border/70 bg-muted/45 px-4 py-3 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Обрабатываю
                </div>
              </div>
            ) : null}

            <div ref={conversationEndRef} />
          </div>

          <form className="border-t border-border/70 bg-background/95 p-3 sm:p-4" onSubmit={handleSubmit}>
            {imageFile ? (
              <div className="mb-3 flex max-w-md items-center justify-between gap-3 rounded-md border border-border/70 bg-muted/45 px-3 py-2 text-sm">
                <span className="flex min-w-0 items-center gap-2">
                  <FileImage className="h-4 w-4 shrink-0 text-primary" />
                  <span className="truncate">{imageFile.name}</span>
                </span>
                <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={() => setImageFile(null)} aria-label="Убрать изображение">
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ) : null}

            {executeMutation.isError ? (
              <div className="mb-3 text-sm text-destructive">Не удалось получить ответ. Повторите отправку.</div>
            ) : null}

            <div className="flex items-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  setImageFile(event.target.files?.[0] ?? null)
                  event.target.value = ""
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-11 w-11 shrink-0"
                onClick={() => fileInputRef.current?.click()}
                title="Добавить изображение"
                aria-label="Добавить изображение"
                disabled={executeMutation.isPending}
              >
                <FileImage className="h-5 w-5" />
              </Button>
              <Textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault()
                    void sendMessage()
                  }
                }}
                placeholder={awaitingAnswer ? "Ответьте ассистенту" : "Введите сообщение"}
                rows={1}
                className="min-h-11 max-h-36 resize-none py-3"
                disabled={executeMutation.isPending}
              />
              <Button
                type="submit"
                size="icon"
                className="h-11 w-11 shrink-0"
                disabled={executeMutation.isPending || (!text.trim() && !imageFile)}
                title="Отправить"
                aria-label="Отправить"
              >
                {executeMutation.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <SendHorizontal className="h-5 w-5" />}
              </Button>
            </div>
          </form>
        </div>
      </Card>

      <DocumentEditDialog
        document={editingDocument}
        onOpenChange={(open) => {
          if (!open) setEditingDocument(null)
        }}
      />
    </div>
  )
}
