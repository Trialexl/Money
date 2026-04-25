import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime } from "@/types"

export type AiAssistantStatus = "created" | "preview" | "needs_confirmation" | "balance" | "duplicate" | "info"

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

export interface AiAssistantResponse {
  status: AiAssistantStatus
  intent: string
  provider: string
  confidence: number
  reply_text: string
  missing_fields?: string[]
  created_object?: AiAssistantCreatedObject | null
  created_objects?: AiAssistantCreatedObject[]
  preview?: Record<string, unknown> | null
  balances?: AiAssistantBalanceRow[]
  options?: Record<string, unknown> | unknown[] | null
  parsed?: Record<string, unknown> | null
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
    balances: Array.isArray(raw?.balances)
      ? raw.balances.map((row: any) => ({
          wallet_id: row.wallet_id,
          wallet_name: row.wallet_name,
          balance: fromApiAmount(row.balance),
        }))
      : [],
    options: raw?.options ?? null,
    parsed: raw?.parsed ?? null,
  }
}

export const AiService = {
  execute: async (payload: {
    text?: string
    wallet?: string
    dryRun?: boolean
    image?: File | null
  }) => {
    const hasImage = Boolean(payload.image)

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
