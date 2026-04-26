import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime, toApiDateTime } from "@/types"

export interface DashboardWalletSummary {
  wallet_id: string
  wallet_name: string
  balance: number
}

export interface DashboardBudgetExpenseItem {
  cash_flow_item_id: string
  cash_flow_item_name: string
  remaining: number
  overrun: number
}

export interface DashboardBudgetExpenseBreakdownDetail {
  period: string
  document_id?: string | null
  document_type?: string | null
  entry_type: "budget" | "actual"
  amount: number
}

export interface DashboardBudgetExpenseBreakdown {
  date: string
  cash_flow_item_id: string
  cash_flow_item_name: string
  planned_total: number
  actual_total: number
  remaining: number
  overrun: number
  details: DashboardBudgetExpenseBreakdownDetail[]
}

export interface DashboardMonthTotals {
  start: string
  income: number
  expense: number
}

export interface DashboardMonthDifference {
  income: number
  expense: number
}

export type DashboardRecentActivity =
  | {
      id: string
      kind: "receipt"
      date: string
      amount: number
      description?: string
      wallet: string
      wallet_name?: string
      cash_flow_item: string
      cash_flow_item_name?: string
    }
  | {
      id: string
      kind: "expenditure"
      date: string
      amount: number
      description?: string
      wallet: string
      wallet_name?: string
      cash_flow_item: string
      cash_flow_item_name?: string
    }
  | {
      id: string
      kind: "transfer"
      date: string
      amount: number
      description?: string
      wallet_from: string
      wallet_from_name?: string
      wallet_to: string
      wallet_to_name?: string
    }

export interface DashboardOverview {
  date: string
  hide_hidden_wallets: boolean
  wallets: DashboardWalletSummary[]
  wallet_total: number
  cash_with_budget: number
  budget_income: {
    planned_total: number
    actual_total: number
    remaining_total: number
  }
  budget_expense: {
    items: DashboardBudgetExpenseItem[]
    remaining_total: number
    overrun_total: number
  }
  month_comparison: {
    previous_month: DashboardMonthTotals
    current_month: DashboardMonthTotals
    difference_percent: DashboardMonthDifference
  }
}

function mapMonthTotals(raw: any): DashboardMonthTotals {
  return {
    start: fromApiDateTime(raw?.start) ?? "",
    income: fromApiAmount(raw?.income),
    expense: fromApiAmount(raw?.expense),
  }
}

function mapRecentActivity(raw: any): DashboardRecentActivity {
  const base = {
    id: raw?.id ?? "",
    date: fromApiDateTime(raw?.date) ?? "",
    amount: fromApiAmount(raw?.amount),
    description: typeof raw?.description === "string" && raw.description.trim() ? raw.description : undefined,
  }

  if (raw?.kind === "transfer") {
    return {
      ...base,
      kind: "transfer",
      wallet_from: raw?.wallet_from ?? "",
      wallet_from_name: typeof raw?.wallet_from_name === "string" && raw.wallet_from_name.trim() ? raw.wallet_from_name : undefined,
      wallet_to: raw?.wallet_to ?? "",
      wallet_to_name: typeof raw?.wallet_to_name === "string" && raw.wallet_to_name.trim() ? raw.wallet_to_name : undefined,
    }
  }

  return {
    ...base,
    kind: raw?.kind === "receipt" ? "receipt" : "expenditure",
    wallet: raw?.wallet ?? "",
    wallet_name: typeof raw?.wallet_name === "string" && raw.wallet_name.trim() ? raw.wallet_name : undefined,
    cash_flow_item: raw?.cash_flow_item ?? "",
    cash_flow_item_name:
      typeof raw?.cash_flow_item_name === "string" && raw.cash_flow_item_name.trim() ? raw.cash_flow_item_name : undefined,
  }
}

export const DashboardService = {
  getOverview: async (options?: { date?: string; hideHiddenWallets?: boolean }) => {
    const params = {
      ...(options?.date ? { date: toApiDateTime(options.date) } : {}),
      ...(typeof options?.hideHiddenWallets === "boolean" ? { hide_hidden_wallets: options.hideHiddenWallets } : {}),
    }

    const { data } = await api.get<any>("/dashboard/overview/", { params })

    return {
      date: fromApiDateTime(data?.date) ?? "",
      hide_hidden_wallets: Boolean(data?.hide_hidden_wallets),
      wallets: Array.isArray(data?.wallets)
        ? data.wallets.map((wallet: any) => ({
            wallet_id: wallet.wallet_id,
            wallet_name: wallet.wallet_name,
            balance: fromApiAmount(wallet.balance),
          }))
        : [],
      wallet_total: fromApiAmount(data?.wallet_total),
      cash_with_budget: fromApiAmount(data?.cash_with_budget),
      budget_income: {
        planned_total: fromApiAmount(data?.budget_income?.planned_total),
        actual_total: fromApiAmount(data?.budget_income?.actual_total),
        remaining_total: fromApiAmount(data?.budget_income?.remaining_total),
      },
      budget_expense: {
        items: Array.isArray(data?.budget_expense?.items)
          ? data.budget_expense.items.map((item: any) => ({
              cash_flow_item_id: item.cash_flow_item_id,
              cash_flow_item_name: item.cash_flow_item_name,
              remaining: fromApiAmount(item.remaining),
              overrun: fromApiAmount(item.overrun),
            }))
          : [],
        remaining_total: fromApiAmount(data?.budget_expense?.remaining_total),
        overrun_total: fromApiAmount(data?.budget_expense?.overrun_total),
      },
      month_comparison: {
        previous_month: mapMonthTotals(data?.month_comparison?.previous_month),
        current_month: mapMonthTotals(data?.month_comparison?.current_month),
        difference_percent: {
          income: fromApiAmount(data?.month_comparison?.difference_percent?.income),
          expense: fromApiAmount(data?.month_comparison?.difference_percent?.expense),
        },
      },
    } satisfies DashboardOverview
  },

  getRecentActivity: async (options?: { date?: string; hideHiddenWallets?: boolean; limit?: number }) => {
    const params = {
      ...(options?.date ? { date: toApiDateTime(options.date) } : {}),
      ...(typeof options?.hideHiddenWallets === "boolean" ? { hide_hidden_wallets: options.hideHiddenWallets } : {}),
      ...(typeof options?.limit === "number" ? { limit: options.limit } : {}),
    }

    const { data } = await api.get<any>("/dashboard/recent-activity/", { params })
    return Array.isArray(data?.items) ? data.items.map(mapRecentActivity) : []
  },

  getBudgetExpenseBreakdown: async (options: { date?: string; cashFlowItemId: string }) => {
    const params = {
      ...(options?.date ? { date: toApiDateTime(options.date) } : {}),
      cash_flow_item: options.cashFlowItemId,
    }

    const { data } = await api.get<any>("/dashboard/budget-expense-breakdown/", { params })

    return {
      date: fromApiDateTime(data?.date) ?? "",
      cash_flow_item_id: data?.cash_flow_item_id ?? "",
      cash_flow_item_name: data?.cash_flow_item_name ?? "",
      planned_total: fromApiAmount(data?.planned_total),
      actual_total: fromApiAmount(data?.actual_total),
      remaining: fromApiAmount(data?.remaining),
      overrun: fromApiAmount(data?.overrun),
      details: Array.isArray(data?.details)
        ? data.details.map((row: any) => ({
            period: fromApiDateTime(row?.period) ?? "",
            document_id: row?.document_id ?? null,
            document_type: row?.document_type ?? null,
            entry_type: row?.entry_type === "budget" ? "budget" : "actual",
            amount: fromApiAmount(row?.amount),
          }))
        : [],
    } satisfies DashboardBudgetExpenseBreakdown
  },
}
