// Shared API-aligned types and helpers

export type Uuid = string

// Common helpers
export const toApiAmount = (amount: number | string | undefined | null): string | undefined => {
  if (amount === undefined || amount === null || amount === "") return undefined
  const num = typeof amount === "number" ? amount : parseFloat(String(amount))
  if (Number.isNaN(num)) return undefined
  return num.toFixed(2)
}

export const fromApiAmount = (amount: string | number | undefined | null): number => {
  if (amount === undefined || amount === null || amount === "") return 0
  return typeof amount === "number" ? amount : parseFloat(amount)
}

export const fromApiDateTime = (dateInput?: string | null): string | undefined => {
  if (!dateInput) return undefined

  if (/^\d{4}-\d{2}-\d{2}$/.test(dateInput)) {
    return dateInput
  }

  if (dateInput.includes("T")) {
    const [datePart] = dateInput.split("T")
    if (/^\d{4}-\d{2}-\d{2}$/.test(datePart)) {
      return datePart
    }
  }

  const parsed = new Date(dateInput)
  if (Number.isNaN(parsed.getTime())) {
    return undefined
  }

  return parsed.toISOString().split("T")[0]
}

export const toApiDateTime = (dateInput?: string): string | undefined => {
  if (!dateInput) return undefined
  // dateInput expected as YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateInput)) {
    return `${dateInput}T00:00:00Z`
  }
  // if already datetime pass through
  return dateInput
}

export interface ApiBaseDocument {
  id?: Uuid
  number?: string
  date?: string // ISO datetime
  deleted?: boolean
  comment?: string
}

export interface ApiReceipt extends ApiBaseDocument {
  amount?: string
  wallet?: Uuid | null
  cash_flow_item?: Uuid | null
}

export interface ApiExpenditure extends ApiBaseDocument {
  amount?: string
  include_in_budget?: boolean
  wallet?: Uuid | null
  cash_flow_item?: Uuid | null
}

export interface ApiTransfer extends ApiBaseDocument {
  amount?: string
  include_in_budget?: boolean
  wallet_in?: Uuid | null
  wallet_out?: Uuid | null
  cash_flow_item?: Uuid | null
}

