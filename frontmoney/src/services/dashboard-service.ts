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

export interface DashboardMonthTotals {
  start: string
  income: number
  expense: number
}

export interface DashboardMonthDifference {
  income: number
  expense: number
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
}
