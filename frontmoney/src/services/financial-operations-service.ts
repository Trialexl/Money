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

export type PageSizeOption = 20 | 50 | 100

export interface PaginatedResult<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
  page: number
  pageSize: number
  totalPages: number
}

interface BaseOperationListParams {
  search?: string
  dateFrom?: string
  dateTo?: string
  amountMin?: number | string
  amountMax?: number | string
  page?: number
  pageSize?: PageSizeOption
}

export interface ReceiptListParams extends BaseOperationListParams {
  wallet?: string
  cashFlowItem?: string
}

export interface ExpenditureListParams extends ReceiptListParams {
  includedInBudget?: boolean
}

export interface TransferListParams extends BaseOperationListParams {
  walletFrom?: string
  walletTo?: string
}

function buildCommonOperationListParams(params?: BaseOperationListParams) {
  return {
    ...(params?.search?.trim() ? { search: params.search.trim() } : {}),
    ...(params?.dateFrom ? { date_from: params.dateFrom } : {}),
    ...(params?.dateTo ? { date_to: params.dateTo } : {}),
    ...(params?.amountMin !== undefined && params.amountMin !== "" ? { amount_min: toApiAmount(params.amountMin) } : {}),
    ...(params?.amountMax !== undefined && params.amountMax !== "" ? { amount_max: toApiAmount(params.amountMax) } : {}),
    ...(params?.page ? { page: params.page } : {}),
    ...(params?.pageSize ? { page_size: params.pageSize } : {}),
  }
}

function mapReceipt(raw: any): Receipt {
  return {
    id: raw.id,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
    date: fromApiDateTime(raw.date) ?? "",
    amount: fromApiAmount(raw.amount),
    number: raw.number ?? undefined,
    description: raw.comment ?? undefined,
    graphic_contract: raw.graphic_contract ?? null,
    wallet: fromApiRelationId(raw.wallet ?? raw.wallet_id),
    cash_flow_item: fromApiRelationId(raw.cash_flow_item ?? raw.cash_flow_item_id),
    wallet_name: fromApiRelationName(raw.wallet, raw.wallet_name),
    cash_flow_item_name: fromApiRelationName(raw.cash_flow_item, raw.cash_flow_item_name),
    project: fromApiRelationId(raw.project ?? raw.project_id) || undefined,
    deleted: raw.deleted,
  }
}

function mapExpenditure(raw: any): Expenditure {
  return {
    id: raw.id,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
    date: fromApiDateTime(raw.date) ?? "",
    amount: fromApiAmount(raw.amount),
    number: raw.number ?? undefined,
    description: raw.comment ?? undefined,
    graphic_contract: raw.graphic_contract ?? null,
    wallet: fromApiRelationId(raw.wallet ?? raw.wallet_id),
    cash_flow_item: fromApiRelationId(raw.cash_flow_item ?? raw.cash_flow_item_id),
    include_in_budget: !!raw.include_in_budget,
    wallet_name: fromApiRelationName(raw.wallet, raw.wallet_name),
    cash_flow_item_name: fromApiRelationName(raw.cash_flow_item, raw.cash_flow_item_name),
    project: fromApiRelationId(raw.project ?? raw.project_id) || undefined,
    deleted: raw.deleted,
  }
}

function mapTransfer(raw: any): Transfer {
  return {
    id: raw.id,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
    date: fromApiDateTime(raw.date) ?? "",
    amount: fromApiAmount(raw.amount),
    number: raw.number ?? undefined,
    description: raw.comment ?? undefined,
    graphic_contract: raw.graphic_contract ?? null,
    wallet_from: fromApiRelationId(raw.wallet_out),
    wallet_to: fromApiRelationId(raw.wallet_in),
    deleted: raw.deleted,
  }
}

function mapPaginatedResponse<T>(data: any, mapper: (raw: any) => T, page: number, pageSize: number): PaginatedResult<T> {
  if (Array.isArray(data)) {
    return {
      count: data.length,
      next: null,
      previous: null,
      results: data.map(mapper),
      page,
      pageSize,
      totalPages: data.length === 0 ? 1 : Math.ceil(data.length / pageSize),
    }
  }

  const count = typeof data?.count === "number" ? data.count : 0
  const results = Array.isArray(data?.results) ? data.results.map(mapper) : []

  return {
    count,
    next: typeof data?.next === "string" ? data.next : null,
    previous: typeof data?.previous === "string" ? data.previous : null,
    results,
    page,
    pageSize,
    totalPages: count === 0 ? 1 : Math.ceil(count / pageSize),
  }
}

async function fetchAllPaginated<T>(
  path: string,
  params: Record<string, unknown>,
  mapper: (raw: any) => T,
): Promise<T[]> {
  const pageSize = 100
  let page = 1
  const items: T[] = []

  while (true) {
    const { data } = await api.get<any>(path, { params: { ...params, page, page_size: pageSize } })
    const paginated = mapPaginatedResponse(data, mapper, page, pageSize)
    items.push(...paginated.results)

    if (!paginated.next || items.length >= paginated.count) {
      break
    }

    page += 1
  }

  return items
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
  getReceiptsPage: async (params: ReceiptListParams = {}) => {
    const page = params.page ?? 1
    const pageSize = params.pageSize ?? 20
    const query = {
      ...buildCommonOperationListParams(params),
      ...(params.wallet ? { wallet: params.wallet } : {}),
      ...(params.cashFlowItem ? { cash_flow_item: params.cashFlowItem } : {}),
    }
    const response = await api.get<any>("/receipts/", { params: query })
    return mapPaginatedResponse(response.data, mapReceipt, page, pageSize)
  },

  getReceipts: async () => {
    return fetchAllPaginated("/receipts/", {}, mapReceipt)
  },

  getReceipt: async (id: string) => {
    const { data: r } = await api.get<any>(`/receipts/${id}/`)
    const mapped = mapReceipt(r)

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
  getExpendituresPage: async (params: ExpenditureListParams = {}) => {
    const page = params.page ?? 1
    const pageSize = params.pageSize ?? 20
    const query = {
      ...buildCommonOperationListParams(params),
      ...(params.wallet ? { wallet: params.wallet } : {}),
      ...(params.cashFlowItem ? { cash_flow_item: params.cashFlowItem } : {}),
      ...(params.includedInBudget !== undefined ? { include_in_budget: params.includedInBudget } : {}),
    }
    const response = await api.get<any>("/expenditures/", { params: query })
    return mapPaginatedResponse(response.data, mapExpenditure, page, pageSize)
  },

  getExpenditures: async (includedInBudget?: boolean) => {
    const params = includedInBudget !== undefined ? { include_in_budget: includedInBudget } : {}
    return fetchAllPaginated("/expenditures/", params, mapExpenditure)
  },

  getExpenditure: async (id: string) => {
    const { data: e } = await api.get<any>(`/expenditures/${id}/`)
    const mapped = mapExpenditure(e)

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
  getTransfersPage: async (params: TransferListParams = {}) => {
    const page = params.page ?? 1
    const pageSize = params.pageSize ?? 20
    const query = {
      ...buildCommonOperationListParams(params),
      ...(params.walletFrom ? { wallet_from: params.walletFrom } : {}),
      ...(params.walletTo ? { wallet_to: params.walletTo } : {}),
    }
    const response = await api.get<any>("/transfers/", { params: query })
    return mapPaginatedResponse(response.data, mapTransfer, page, pageSize)
  },

  getTransfers: async () => {
    return fetchAllPaginated("/transfers/", {}, mapTransfer)
  },

  getTransfer: async (id: string) => {
    const { data: t } = await api.get<any>(`/transfers/${id}/`)
    const mapped = mapTransfer(t)
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
