import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime } from "@/types"

export type AiAssistantStatus = "created" | "preview" | "needs_confirmation" | "balance" | "duplicate" | "info"
export type AiAssistantMode = "classic" | "agent"
export type AiAssistantHistoryMessage = { role: "user" | "assistant"; content: string; image?: File | null }

export interface AiAssistantCreatedObject {
  model: string
  id: string
  number: string
}

export interface AiAssistantBalanceRow {
  wallet_id: string
  wallet_name: string
  balance: number
}

export interface AiAssistantEntityLink {
  kind: "wallet" | "cash_flow_item"
  id: string
  label: string
}

export interface AiAssistantResponse {
  status: AiAssistantStatus
  intent: string
  provider: string
  confidence: number
  reply_text: string
  reply_parse_mode?: string
  missing_fields?: string[]
  created_object?: AiAssistantCreatedObject | null
  created_objects?: AiAssistantCreatedObject[]
  preview?: Record<string, unknown> | null
  balances?: AiAssistantBalanceRow[]
  options?: Record<string, unknown> | unknown[] | null
  parsed?: Record<string, unknown> | null
  entity_links?: AiAssistantEntityLink[]
}

export interface TelegramLinkTokenResponse {
  code: string
  expires_at: string
}

function normalizeAiResponse(raw: any): AiAssistantResponse {
  return {
    status: raw?.status ?? "preview",
    intent: raw?.intent ?? "unknown",
    provider: raw?.provider ?? "unknown",
    confidence: typeof raw?.confidence === "number" ? raw.confidence : Number(raw?.confidence ?? 0),
    reply_text: raw?.reply_text ?? "",
    reply_parse_mode: raw?.reply_parse_mode ?? undefined,
    missing_fields: Array.isArray(raw?.missing_fields) ? raw.missing_fields : [],
    created_object: raw?.created_object
      ? {
          model: raw.created_object.model,
          id: raw.created_object.id,
          number: raw.created_object.number,
        }
      : null,
    created_objects: Array.isArray(raw?.created_objects)
      ? raw.created_objects
          .map((item: any) =>
            item
              ? {
                  model: item.model,
                  id: item.id,
                  number: item.number,
                }
              : null
          )
          .filter((item: AiAssistantCreatedObject | null): item is AiAssistantCreatedObject => Boolean(item))
      : [],
    preview: raw?.preview ?? null,
    balances: Array.isArray(raw?.balances ?? raw?.wallet_balances)
      ? (raw.balances ?? raw.wallet_balances).map((row: any) => ({
          wallet_id: row.wallet_id,
          wallet_name: row.wallet_name,
          balance: fromApiAmount(row.balance),
        }))
      : [],
    options: raw?.options ?? null,
    parsed: raw?.parsed ?? null,
    entity_links: Array.isArray(raw?.entity_links)
      ? raw.entity_links
          .map((item: any) =>
            item &&
            (item.kind === "wallet" || item.kind === "cash_flow_item") &&
            typeof item.id === "string" &&
            typeof item.label === "string"
              ? {
                  kind: item.kind,
                  id: item.id,
                  label: item.label,
                }
              : null
          )
          .filter((item: AiAssistantEntityLink | null): item is AiAssistantEntityLink => Boolean(item))
      : [],
  }
}

export const AiService = {
  execute: async (payload: {
    text?: string
    wallet?: string
    dryRun?: boolean
    image?: File | null
    conversation?: boolean
    mode?: AiAssistantMode
    history?: AiAssistantHistoryMessage[]
  }) => {
    const recentHistory = (payload.history ?? []).slice(-20)
    const imageMessages = payload.mode === "agent"
      ? recentHistory.filter((item) => item.role === "user" && item.image).slice(-3)
      : []
    const history = recentHistory.map((item) => {
      const imageIndex = imageMessages.indexOf(item)
      return {
        role: item.role,
        content: item.content,
        ...(imageIndex >= 0 ? { image_index: imageIndex } : {}),
      }
    })
    const hasImage = Boolean(payload.image) || imageMessages.length > 0

    if (hasImage) {
      const formData = new FormData()
      if (payload.text?.trim()) {
        formData.append("text", payload.text.trim())
      }
      if (payload.wallet) {
        formData.append("wallet", payload.wallet)
      }
      if (typeof payload.dryRun === "boolean") {
        formData.append("dry_run", String(payload.dryRun))
      }
      if (typeof payload.conversation === "boolean") {
        formData.append("conversation", String(payload.conversation))
      }
      if (payload.mode) {
        formData.append("mode", payload.mode)
      }
      if (history.length) {
        formData.append("history", JSON.stringify(history))
      }
      for (const item of imageMessages) {
        formData.append("history_images", item.image!)
      }
      if (payload.image) {
        formData.append("image", payload.image)
      }

      const { data } = await api.post("/ai/execute/", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      })
      return normalizeAiResponse(data)
    }

    const { data } = await api.post("/ai/execute/", {
      text: payload.text?.trim() || undefined,
      wallet: payload.wallet || undefined,
      dry_run: payload.dryRun ?? false,
      conversation: payload.conversation ?? false,
      mode: payload.mode ?? "classic",
      history,
    })

    return normalizeAiResponse(data)
  },

  createTelegramLinkToken: async () => {
    const { data } = await api.post<any>("/ai/telegram-link-token/", {})
    return {
      code: data?.code ?? "",
      expires_at: fromApiDateTime(data?.expires_at) ?? data?.expires_at ?? "",
    } satisfies TelegramLinkTokenResponse
  },
}
