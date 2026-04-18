import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime, toApiAmount, toApiDateTime } from "@/types"

function fromApiRelationId(value: unknown): string {
  if (typeof value === "string") {
    return value
  }

  if (value && typeof value === "object") {
    for (const key of ["id", "uuid", "pk", "value", "wallet_id", "cash_flow_item_id", "project_id"] as const) {
      const candidate = (value as Record<string, unknown>)[key]
      if (typeof candidate === "string") {
        return candidate
      }
    }
  }

  return ""
}

function fromApiRelationName(value: unknown, directName?: unknown): string | undefined {
  if (typeof directName === "string" && directName.trim()) {
    return directName
  }

  if (value && typeof value === "object") {
    for (const key of ["name", "title", "wallet_name", "cash_flow_item_name", "project_name"] as const) {
      const candidate = (value as Record<string, unknown>)[key]
      if (typeof candidate === "string" && candidate.trim()) {
        return candidate
      }
    }
  }

  return undefined
}

// Base interface for financial operations
export interface FinancialOperation {
  id: string
  created_at?: string
  updated_at?: string
  deleted?: boolean
  graphic_contract?: Record<string, unknown> | null
  date: string
  amount: number
  number?: string
  description?: string
  project?: string
}

// Receipts (Income)
export interface Receipt extends FinancialOperation {
  wallet: string
  cash_flow_item: string
  wallet_name?: string
  cash_flow_item_name?: string
}

// Expenditures (Expenses)
export interface Expenditure extends FinancialOperation {
  wallet: string
  cash_flow_item: string
  include_in_budget: boolean
  wallet_name?: string
  cash_flow_item_name?: string
}

// Transfers
export interface Transfer extends FinancialOperation {
  wallet_from: string
  wallet_to: string
}

// Budgets
export interface Budget extends FinancialOperation {
  type: 'income' | 'expense'
  cash_flow_item: string
  date_start?: string
  amount_month?: number
}

// Auto-payments
export interface AutoPayment extends FinancialOperation {
  is_transfer: boolean
  wallet_from: string
  wallet_to?: string
  cash_flow_item?: string
  amount_month?: number
  date_start?: string
}

// Receipt service
export const ReceiptService = {
  getReceipts: async () => {
    const response = await api.get<any[]>("/receipts/")
    return response.data.map((r) => ({
      id: r.id,
      created_at: r.created_at,
      updated_at: r.updated_at,
      date: fromApiDateTime(r.date) ?? "",
      amount: fromApiAmount(r.amount),
      number: r.number ?? undefined,
      description: r.comment ?? undefined,
      graphic_contract: r.graphic_contract ?? null,
      wallet: fromApiRelationId(r.wallet ?? r.wallet_id),
      cash_flow_item: fromApiRelationId(r.cash_flow_item ?? r.cash_flow_item_id),
      wallet_name: fromApiRelationName(r.wallet, r.wallet_name),
      cash_flow_item_name: fromApiRelationName(r.cash_flow_item, r.cash_flow_item_name),
      project: fromApiRelationId(r.project ?? r.project_id) || undefined,
      deleted: r.deleted,
    })) as Receipt[]
  },

  getReceipt: async (id: string) => {
    const { data: r } = await api.get<any>(`/receipts/${id}/`)
    const mapped: Receipt = {
      id: r.id,
      created_at: r.created_at,
      updated_at: r.updated_at,
      date: fromApiDateTime(r.date) ?? "",
      amount: fromApiAmount(r.amount),
      number: r.number ?? undefined,
      description: r.comment ?? undefined,
      graphic_contract: r.graphic_contract ?? null,
      wallet: fromApiRelationId(r.wallet ?? r.wallet_id),
      cash_flow_item: fromApiRelationId(r.cash_flow_item ?? r.cash_flow_item_id),
      wallet_name: fromApiRelationName(r.wallet, r.wallet_name),
      cash_flow_item_name: fromApiRelationName(r.cash_flow_item, r.cash_flow_item_name),
      project: fromApiRelationId(r.project ?? r.project_id) || undefined,
      deleted: r.deleted,
    }

    if (!mapped.wallet || !mapped.cash_flow_item) {
      const source = (await ReceiptService.getReceipts()).find((item) => item.id === id)

      return {
        ...mapped,
        wallet: mapped.wallet || source?.wallet || "",
        cash_flow_item: mapped.cash_flow_item || source?.cash_flow_item || "",
      }
    }

    return mapped
  },

  createReceipt: async (data: Partial<Receipt>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      amount: toApiAmount(data.amount),
      comment: data.description,
      wallet: data.wallet,
      cash_flow_item: data.cash_flow_item,
    }
    const response = await api.post<any>("/receipts/", payload)
    return ReceiptService.getReceipt(response.data.id)
  },

  updateReceipt: async (id: string, data: Partial<Receipt>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      amount: toApiAmount(data.amount),
      comment: data.description,
      wallet: data.wallet,
      cash_flow_item: data.cash_flow_item,
    }
    await api.patch<any>(`/receipts/${id}/`, payload)
    return ReceiptService.getReceipt(id)
  },

  deleteReceipt: async (id: string) => {
    await api.delete(`/receipts/${id}/`)
  }
}

// Expenditure service
export const ExpenditureService = {
  getExpenditures: async (includedInBudget?: boolean) => {
    const params = includedInBudget !== undefined ? { include_in_budget: includedInBudget } : {}
    const { data } = await api.get<any[]>("/expenditures/", { params })
    return data.map((e) => ({
      id: e.id,
      created_at: e.created_at,
      updated_at: e.updated_at,
      date: fromApiDateTime(e.date) ?? "",
      amount: fromApiAmount(e.amount),
      number: e.number ?? undefined,
      description: e.comment ?? undefined,
      graphic_contract: e.graphic_contract ?? null,
      wallet: fromApiRelationId(e.wallet ?? e.wallet_id),
      cash_flow_item: fromApiRelationId(e.cash_flow_item ?? e.cash_flow_item_id),
      include_in_budget: !!e.include_in_budget,
      wallet_name: fromApiRelationName(e.wallet, e.wallet_name),
      cash_flow_item_name: fromApiRelationName(e.cash_flow_item, e.cash_flow_item_name),
      project: fromApiRelationId(e.project ?? e.project_id) || undefined,
      deleted: e.deleted,
    })) as Expenditure[]
  },

  getExpenditure: async (id: string) => {
    const { data: e } = await api.get<any>(`/expenditures/${id}/`)
    const mapped: Expenditure = {
      id: e.id,
      created_at: e.created_at,
      updated_at: e.updated_at,
      date: fromApiDateTime(e.date) ?? "",
      amount: fromApiAmount(e.amount),
      number: e.number ?? undefined,
      description: e.comment ?? undefined,
      graphic_contract: e.graphic_contract ?? null,
      wallet: fromApiRelationId(e.wallet ?? e.wallet_id),
      cash_flow_item: fromApiRelationId(e.cash_flow_item ?? e.cash_flow_item_id),
      include_in_budget: !!e.include_in_budget,
      wallet_name: fromApiRelationName(e.wallet, e.wallet_name),
      cash_flow_item_name: fromApiRelationName(e.cash_flow_item, e.cash_flow_item_name),
      project: fromApiRelationId(e.project ?? e.project_id) || undefined,
      deleted: e.deleted,
    }

    if (!mapped.wallet || !mapped.cash_flow_item) {
      const source = (await ExpenditureService.getExpenditures()).find((item) => item.id === id)

      return {
        ...mapped,
        wallet: mapped.wallet || source?.wallet || "",
        cash_flow_item: mapped.cash_flow_item || source?.cash_flow_item || "",
      }
    }

    return mapped
  },

  createExpenditure: async (data: Partial<Expenditure>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      amount: toApiAmount(data.amount),
      comment: data.description,
      wallet: data.wallet,
      cash_flow_item: data.cash_flow_item,
      include_in_budget: data.include_in_budget,
    }
    const response = await api.post<any>("/expenditures/", payload)
    return ExpenditureService.getExpenditure(response.data.id)
  },

  updateExpenditure: async (id: string, data: Partial<Expenditure>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      amount: toApiAmount(data.amount),
      comment: data.description,
      wallet: data.wallet,
      cash_flow_item: data.cash_flow_item,
      include_in_budget: data.include_in_budget,
    }
    await api.patch<any>(`/expenditures/${id}/`, payload)
    return ExpenditureService.getExpenditure(id)
  },

  deleteExpenditure: async (id: string) => {
    await api.delete(`/expenditures/${id}/`)
  }
}

// Transfer service
export const TransferService = {
  getTransfers: async () => {
    const { data } = await api.get<any[]>("/transfers/")
    return data.map((t) => ({
      id: t.id,
      created_at: t.created_at,
      updated_at: t.updated_at,
      date: fromApiDateTime(t.date) ?? "",
      amount: fromApiAmount(t.amount),
      number: t.number ?? undefined,
      description: t.comment ?? undefined,
      graphic_contract: t.graphic_contract ?? null,
      wallet_from: fromApiRelationId(t.wallet_out),
      wallet_to: fromApiRelationId(t.wallet_in),
      deleted: t.deleted,
    })) as Transfer[]
  },

  getTransfer: async (id: string) => {
    const { data: t } = await api.get<any>(`/transfers/${id}/`)
    const mapped: Transfer = {
      id: t.id,
      created_at: t.created_at,
      updated_at: t.updated_at,
      date: fromApiDateTime(t.date) ?? "",
      amount: fromApiAmount(t.amount),
      number: t.number ?? undefined,
      description: t.comment ?? undefined,
      graphic_contract: t.graphic_contract ?? null,
      wallet_from: fromApiRelationId(t.wallet_out),
      wallet_to: fromApiRelationId(t.wallet_in),
      deleted: t.deleted,
    }
    return mapped
  },

  createTransfer: async (data: Partial<Transfer>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      amount: toApiAmount(data.amount),
      comment: data.description,
      wallet_out: data.wallet_from,
      wallet_in: data.wallet_to,
    }
    const response = await api.post<any>("/transfers/", payload)
    return TransferService.getTransfer(response.data.id)
  },

  updateTransfer: async (id: string, data: Partial<Transfer>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      amount: toApiAmount(data.amount),
      comment: data.description,
      wallet_out: data.wallet_from,
      wallet_in: data.wallet_to,
    }
    await api.patch<any>(`/transfers/${id}/`, payload)
    return TransferService.getTransfer(id)
  },

  deleteTransfer: async (id: string) => {
    await api.delete(`/transfers/${id}/`)
  }
}

// Budget service
export const BudgetService = {
  getBudgets: async (type?: 'income' | 'expense') => {
    const params = type ? { type } : {}
    const { data } = await api.get<any[]>("/budgets/", { params })
    return data.map((b) => ({
      id: b.id,
      created_at: b.created_at,
      updated_at: b.updated_at,
      date: fromApiDateTime(b.date) ?? "",
      date_start: fromApiDateTime(b.date_start) ?? undefined,
      amount: fromApiAmount(b.amount),
      amount_month: b.amount_month != null ? Number(b.amount_month) : undefined,
      number: b.number ?? undefined,
      description: b.comment ?? undefined,
      graphic_contract: b.graphic_contract ?? null,
      type: b.type_of_budget ? 'income' : 'expense',
      cash_flow_item: fromApiRelationId(b.cash_flow_item),
      project: fromApiRelationId(b.project) || undefined,
      deleted: b.deleted,
    })) as Budget[]
  },

  getBudget: async (id: string) => {
    const { data: b } = await api.get<any>(`/budgets/${id}/`)
    const mapped: Budget = {
      id: b.id,
      created_at: b.created_at,
      updated_at: b.updated_at,
      date: fromApiDateTime(b.date) ?? "",
      date_start: fromApiDateTime(b.date_start) ?? undefined,
      amount: fromApiAmount(b.amount),
      amount_month: b.amount_month != null ? Number(b.amount_month) : undefined,
      number: b.number ?? undefined,
      description: b.comment ?? undefined,
      graphic_contract: b.graphic_contract ?? null,
      type: b.type_of_budget ? 'income' : 'expense',
      cash_flow_item: fromApiRelationId(b.cash_flow_item),
      project: fromApiRelationId(b.project) || undefined,
      deleted: b.deleted,
    }
    return mapped
  },

  createBudget: async (data: Partial<Budget>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      date_start: toApiDateTime((data as any).date_start),
      amount: toApiAmount(data.amount),
      amount_month: (data as any).amount_month != null ? Number((data as any).amount_month) : 0,
      comment: data.description,
      type_of_budget: data.type === 'income',
      cash_flow_item: data.cash_flow_item,
      project: data.project,
    }
    const response = await api.post<any>("/budgets/", payload)
    return BudgetService.getBudget(response.data.id)
  },

  updateBudget: async (id: string, data: Partial<Budget>) => {
    const payload = {
      number: (data as any).number,
      date: toApiDateTime(data.date),
      date_start: toApiDateTime((data as any).date_start),
      amount: toApiAmount(data.amount),
      amount_month: (data as any).amount_month != null ? Number((data as any).amount_month) : 0,
      comment: data.description,
      type_of_budget: data.type === 'income',
      cash_flow_item: data.cash_flow_item,
      project: data.project,
    }
    await api.patch<any>(`/budgets/${id}/`, payload)
    return BudgetService.getBudget(id)
  },

  deleteBudget: async (id: string) => {
    await api.delete(`/budgets/${id}/`)
  }
}

// Auto-payment service
export const AutoPaymentService = {
  getAutoPayments: async (isTransfer?: boolean) => {
    const params = isTransfer !== undefined ? { is_transfer: isTransfer } : {}
    const { data } = await api.get<any[]>("/auto-payments/", { params })
    return data.map((a) => ({
      id: a.id,
      created_at: a.created_at,
      updated_at: a.updated_at,
      date: fromApiDateTime(a.date ?? a.date_start) ?? "",
      amount: fromApiAmount(a.amount),
      number: a.number ?? undefined,
      description: a.comment ?? undefined,
      graphic_contract: a.graphic_contract ?? null,
      is_transfer: !!a.is_transfer,
      wallet_from: fromApiRelationId(a.wallet_out),
      wallet_to: fromApiRelationId(a.wallet_in) || undefined,
      cash_flow_item: fromApiRelationId(a.cash_flow_item) || undefined,
      amount_month: a.amount_month != null ? Number(a.amount_month) : undefined,
      date_start: fromApiDateTime(a.date_start) ?? undefined,
      deleted: a.deleted,
    })) as AutoPayment[]
  },

  getAutoPayment: async (id: string) => {
    const { data: a } = await api.get<any>(`/auto-payments/${id}/`)
    const mapped: AutoPayment = {
      id: a.id,
      created_at: a.created_at,
      updated_at: a.updated_at,
      date: fromApiDateTime(a.date ?? a.date_start) ?? "",
      amount: fromApiAmount(a.amount),
      number: a.number ?? undefined,
      description: a.comment ?? undefined,
      graphic_contract: a.graphic_contract ?? null,
      is_transfer: !!a.is_transfer,
      wallet_from: fromApiRelationId(a.wallet_out),
      wallet_to: fromApiRelationId(a.wallet_in) || undefined,
      cash_flow_item: fromApiRelationId(a.cash_flow_item) || undefined,
      amount_month: a.amount_month != null ? Number(a.amount_month) : undefined,
      date_start: fromApiDateTime(a.date_start) ?? undefined,
      deleted: a.deleted,
    }
    return mapped
  },

  createAutoPayment: async (data: Partial<AutoPayment>) => {
    const payload = {
      amount: toApiAmount(data.amount),
      comment: data.description,
      is_transfer: data.is_transfer,
      date_start: toApiDateTime(data.date_start ?? data.date),
      amount_month: data.amount_month != null ? Number(data.amount_month) : undefined,
      wallet_out: data.wallet_from,
      wallet_in: data.wallet_to,
      cash_flow_item: data.cash_flow_item,
    }
    const response = await api.post<any>("/auto-payments/", payload)
    return AutoPaymentService.getAutoPayment(response.data.id)
  },

  updateAutoPayment: async (id: string, data: Partial<AutoPayment>) => {
    const payload = {
      amount: toApiAmount(data.amount),
      comment: data.description,
      is_transfer: data.is_transfer,
      date_start: toApiDateTime(data.date_start ?? data.date),
      amount_month: data.amount_month != null ? Number(data.amount_month) : undefined,
      wallet_out: data.wallet_from,
      wallet_in: data.wallet_to,
      cash_flow_item: data.cash_flow_item,
    }
    await api.patch<any>(`/auto-payments/${id}/`, payload)
    return AutoPaymentService.getAutoPayment(id)
  },

  deleteAutoPayment: async (id: string) => {
    await api.delete(`/auto-payments/${id}/`)
  }
}
