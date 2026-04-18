import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime, toApiDateTime } from "@/types"

type BaseReportFilters = {
  dateFrom?: string
  dateTo?: string
  limitByToday?: boolean
}

type CashFlowReportFilters = BaseReportFilters & {
  wallet?: string
  cashFlowItem?: string
}

type BudgetReportFilters = BaseReportFilters & {
  project?: string
  cashFlowItem?: string
}

export interface CashFlowReportMonth {
  period: string
  income: number
  expense: number
}

export interface CashFlowReportDetail {
  period: string
  document_id?: string | null
  document_type?: string | null
  wallet_id?: string | null
  wallet_name?: string | null
  cash_flow_item_id?: string | null
  cash_flow_item_name?: string | null
  income: number
  expense: number
}

export interface CashFlowReportResponse {
  filters: Record<string, unknown>
  totals: {
    income: number
    expense: number
  }
  months: CashFlowReportMonth[]
  details: CashFlowReportDetail[]
}

export interface BudgetReportSummary {
  period: string
  project_id?: string | null
  project_name?: string | null
  cash_flow_item_id?: string | null
  cash_flow_item_name?: string | null
  actual: number
  budget: number
  balance: number
}

export interface BudgetReportDetail {
  period: string
  document_id?: string | null
  document_type?: string | null
  entry_type: string
  project_id?: string | null
  project_name?: string | null
  cash_flow_item_id?: string | null
  cash_flow_item_name?: string | null
  amount: number
}

export interface BudgetReportResponse {
  filters: Record<string, unknown>
  totals: {
    actual: number
    budget: number
    balance: number
  }
  summary: BudgetReportSummary[]
  details: BudgetReportDetail[]
}

function buildCommonParams(filters?: BaseReportFilters) {
  return {
    ...(filters?.dateFrom ? { date_from: toApiDateTime(filters.dateFrom) } : {}),
    ...(filters?.dateTo ? { date_to: toApiDateTime(filters.dateTo) } : {}),
    ...(typeof filters?.limitByToday === "boolean" ? { limit_by_today: filters.limitByToday } : {}),
  }
}

function mapCashFlowReport(raw: any): CashFlowReportResponse {
  return {
    filters: raw?.filters ?? {},
    totals: {
      income: fromApiAmount(raw?.totals?.income),
      expense: fromApiAmount(raw?.totals?.expense),
    },
    months: Array.isArray(raw?.months)
      ? raw.months.map((month: any) => ({
          period: fromApiDateTime(month?.period) ?? "",
          income: fromApiAmount(month?.income),
          expense: fromApiAmount(month?.expense),
        }))
      : [],
    details: Array.isArray(raw?.details)
      ? raw.details.map((detail: any) => ({
          period: fromApiDateTime(detail?.period) ?? "",
          document_id: detail?.document_id ?? null,
          document_type: detail?.document_type ?? null,
          wallet_id: detail?.wallet_id ?? null,
          wallet_name: detail?.wallet_name ?? null,
          cash_flow_item_id: detail?.cash_flow_item_id ?? null,
          cash_flow_item_name: detail?.cash_flow_item_name ?? null,
          income: fromApiAmount(detail?.income),
          expense: fromApiAmount(detail?.expense),
        }))
      : [],
  }
}

function mapBudgetReport(raw: any): BudgetReportResponse {
  return {
    filters: raw?.filters ?? {},
    totals: {
      actual: fromApiAmount(raw?.totals?.actual),
      budget: fromApiAmount(raw?.totals?.budget),
      balance: fromApiAmount(raw?.totals?.balance),
    },
    summary: Array.isArray(raw?.summary)
      ? raw.summary.map((row: any) => ({
          period: fromApiDateTime(row?.period) ?? "",
          project_id: row?.project_id ?? null,
          project_name: row?.project_name ?? null,
          cash_flow_item_id: row?.cash_flow_item_id ?? null,
          cash_flow_item_name: row?.cash_flow_item_name ?? null,
          actual: fromApiAmount(row?.actual),
          budget: fromApiAmount(row?.budget),
          balance: fromApiAmount(row?.balance),
        }))
      : [],
    details: Array.isArray(raw?.details)
      ? raw.details.map((row: any) => ({
          period: fromApiDateTime(row?.period) ?? "",
          document_id: row?.document_id ?? null,
          document_type: row?.document_type ?? null,
          entry_type: row?.entry_type ?? "",
          project_id: row?.project_id ?? null,
          project_name: row?.project_name ?? null,
          cash_flow_item_id: row?.cash_flow_item_id ?? null,
          cash_flow_item_name: row?.cash_flow_item_name ?? null,
          amount: fromApiAmount(row?.amount),
        }))
      : [],
  }
}

export const ReportService = {
  getCashFlowReport: async (filters?: CashFlowReportFilters) => {
    const params = {
      ...buildCommonParams(filters),
      ...(filters?.wallet ? { wallet: filters.wallet } : {}),
      ...(filters?.cashFlowItem ? { cash_flow_item: filters.cashFlowItem } : {}),
    }

    const { data } = await api.get<any>("/reports/cash-flow/", { params })
    return mapCashFlowReport(data)
  },

  getBudgetIncomeReport: async (filters?: BudgetReportFilters) => {
    const params = {
      ...buildCommonParams(filters),
      ...(filters?.project ? { project: filters.project } : {}),
      ...(filters?.cashFlowItem ? { cash_flow_item: filters.cashFlowItem } : {}),
    }

    const { data } = await api.get<any>("/reports/budget-income/", { params })
    return mapBudgetReport(data)
  },

  getBudgetExpenseReport: async (filters?: BudgetReportFilters) => {
    const params = {
      ...buildCommonParams(filters),
      ...(filters?.project ? { project: filters.project } : {}),
      ...(filters?.cashFlowItem ? { cash_flow_item: filters.cashFlowItem } : {}),
    }

    const { data } = await api.get<any>("/reports/budget-expense/", { params })
    return mapBudgetReport(data)
  },
}
