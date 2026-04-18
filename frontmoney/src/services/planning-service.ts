import api from "@/lib/api"
import { addMonths } from "date-fns"
import { fromApiAmount, fromApiDateTime, toApiAmount, toApiDateTime } from "@/types"

export type PlanningDocumentKind = "expenditure" | "transfer" | "budget" | "auto-payment"

export interface PlanningGraphic {
  id: number
  date_start: string
  amount: number
  document: string
}

export interface PlanningGraphicDraft {
  id: string
  date_start: string
  amount: number
}

const basePathMap: Record<PlanningDocumentKind, string> = {
  expenditure: "/expenditure-graphics/",
  transfer: "/transfer-graphics/",
  budget: "/budget-graphics/",
  "auto-payment": "/auto-payment-graphics/",
}

const generatePathMap: Partial<Record<PlanningDocumentKind, string>> = {
  budget: "/budgets",
  "auto-payment": "/auto-payments",
}

function mapGraphic(raw: any): PlanningGraphic {
  return {
    id: Number(raw?.id),
    date_start: fromApiDateTime(raw?.date_start) ?? "",
    amount: fromApiAmount(raw?.amount),
    document: raw?.document ?? "",
  }
}

function mapDraftRow(raw: any): PlanningGraphicDraft | null {
  const dateStart = typeof raw?.date_start === "string" ? raw.date_start : ""
  const amount = Number(raw?.amount)
  const id = typeof raw?.id === "string" ? raw.id : `draft-${Math.random().toString(36).slice(2, 10)}`

  if (!dateStart || Number.isNaN(amount) || amount <= 0) {
    return null
  }

  return {
    id,
    date_start: dateStart,
    amount,
  }
}

export const PlanningService = {
  getGraphics: async (kind: PlanningDocumentKind, documentId: string) => {
    const { data } = await api.get<any[]>(basePathMap[kind], {
      params: { document: documentId },
    })
    return Array.isArray(data) ? data.map(mapGraphic).sort((left, right) => left.date_start.localeCompare(right.date_start)) : []
  },

  createGraphic: async (
    kind: PlanningDocumentKind,
    payload: { document: string; date_start: string; amount: number }
  ) => {
    const { data } = await api.post<any>(basePathMap[kind], {
      document: payload.document,
      date_start: toApiDateTime(payload.date_start),
      amount: toApiAmount(payload.amount),
    })
    return mapGraphic(data)
  },

  deleteGraphic: async (kind: PlanningDocumentKind, graphicId: number) => {
    await api.delete(`${basePathMap[kind]}${graphicId}/`)
  },

  replaceGraphicsRows: async (kind: PlanningDocumentKind, documentId: string, rows: PlanningGraphicDraft[]) => {
    const currentRows = await PlanningService.getGraphics(kind, documentId)

    await Promise.all(currentRows.map((row) => PlanningService.deleteGraphic(kind, row.id)))

    const normalizedRows = [...rows]
      .filter((row) => row.date_start && row.amount > 0)
      .sort((left, right) => left.date_start.localeCompare(right.date_start))

    for (const row of normalizedRows) {
      await PlanningService.createGraphic(kind, {
        document: documentId,
        date_start: row.date_start,
        amount: row.amount,
      })
    }
  },

  buildDistributedRows: ({
    totalAmount,
    startDate,
    monthCount,
  }: {
    totalAmount: number
    startDate: string
    monthCount: number
  }) => {
    if (!startDate || Number.isNaN(totalAmount) || totalAmount <= 0 || !Number.isFinite(monthCount) || monthCount <= 0) {
      return [] as PlanningGraphicDraft[]
    }

    const start = new Date(`${startDate}T12:00:00`)
    if (Number.isNaN(start.getTime())) {
      return [] as PlanningGraphicDraft[]
    }

    const totalCents = Math.round(totalAmount * 100)
    const basePart = Math.trunc(totalCents / monthCount)
    const remainder = totalCents - basePart * monthCount

    return Array.from({ length: monthCount }, (_, index) => {
      const date = addMonths(start, index)
      const rowCents = basePart + (index < remainder ? 1 : 0)

      return {
        id: `draft-${index}-${date.getTime()}`,
        date_start: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
        amount: rowCents / 100,
      }
    })
  },

  getDraftRows: (storageKey: string) => {
    if (typeof window === "undefined") {
      return [] as PlanningGraphicDraft[]
    }

    try {
      const raw = window.localStorage.getItem(storageKey)
      if (!raw) {
        return [] as PlanningGraphicDraft[]
      }

      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? parsed.map(mapDraftRow).filter(Boolean) as PlanningGraphicDraft[] : []
    } catch {
      return [] as PlanningGraphicDraft[]
    }
  },

  saveDraftRows: (storageKey: string, rows: PlanningGraphicDraft[]) => {
    if (typeof window === "undefined") {
      return
    }

    window.localStorage.setItem(storageKey, JSON.stringify(rows))
  },

  clearDraftRows: (storageKey: string) => {
    if (typeof window === "undefined") {
      return
    }

    window.localStorage.removeItem(storageKey)
  },

  generateGraphics: async (
    kind: Extract<PlanningDocumentKind, "budget" | "auto-payment">,
    documentId: string,
    payload: Record<string, unknown>
  ) => {
    const basePath = generatePathMap[kind]
    if (!basePath) {
      throw new Error("Generate graphics is not supported for this document kind")
    }

    await api.post(`${basePath}/${documentId}/generate-graphics/`, payload)
  },
}
