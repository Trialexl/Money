import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime } from "@/types"

export interface Wallet {
  id: string
  name: string
  code?: string | null
  hidden?: boolean
  created_at: string
  updated_at: string
  deleted: boolean
}

export interface WalletBalanceResponse {
  wallet_id: string
  wallet_name: string
  balance: number
  currency: string
  last_updated?: string
}

export interface WalletBalancesSnapshot {
  balances: WalletBalanceResponse[]
  total_balance: number
  total_wallets: number
}

export const WalletService = {
  getWallets: async () => {
    const { data } = await api.get<any[]>("/wallets/")
    return data.map((w) => ({
      id: w.id,
      name: w.name,
      code: w.code ?? null,
      hidden: !!w.hidden,
      created_at: w.created_at,
      updated_at: w.updated_at,
      deleted: !!w.deleted,
    })) as Wallet[]
  },

  getWallet: async (id: string) => {
    const { data: w } = await api.get<any>(`/wallets/${id}/`)
    const mapped: Wallet = {
      id: w.id,
      name: w.name,
      code: w.code ?? null,
      hidden: !!w.hidden,
      created_at: w.created_at,
      updated_at: w.updated_at,
      deleted: !!w.deleted,
    }
    return mapped
  },

  createWallet: async (data: Partial<Wallet>) => {
    const payload = {
      name: data.name,
      hidden: data.hidden,
    }
    const response = await api.post<any>("/wallets/", payload)
    return WalletService.getWallet(response.data.id)
  },

  updateWallet: async (id: string, data: Partial<Wallet>) => {
    const payload = {
      name: data.name,
      hidden: data.hidden,
    }
    await api.patch<any>(`/wallets/${id}/`, payload)
    return WalletService.getWallet(id)
  },

  deleteWallet: async (id: string) => {
    await api.delete(`/wallets/${id}/`)
  },

  getWalletBalance: async (id: string) => {
    const { data } = await api.get<any>(`/wallets/${id}/balance/`)

    return {
      wallet_id: data?.wallet_id ?? id,
      wallet_name: data?.wallet_name ?? "",
      balance: fromApiAmount(data?.balance),
      currency: data?.currency ?? "RUB",
      last_updated: fromApiDateTime(data?.last_updated) ?? data?.last_updated ?? undefined,
    } satisfies WalletBalanceResponse
  },

  getWalletBalances: async () => {
    const { data } = await api.get<any>("/wallets/balances/")

    if (data && typeof data === "object" && Array.isArray(data.balances)) {
      return {
        balances: data.balances.map((wallet: any) => ({
          wallet_id: wallet.wallet_id,
          wallet_name: wallet.wallet_name,
          balance: fromApiAmount(wallet.balance),
          currency: wallet.currency ?? "RUB",
          last_updated: fromApiDateTime(wallet.last_updated) ?? wallet.last_updated ?? undefined,
        })),
        total_balance: fromApiAmount(data.total_balance),
        total_wallets: Number(data.total_wallets ?? data.balances.length ?? 0),
      } satisfies WalletBalancesSnapshot
    }

    return {
      balances: [],
      total_balance: 0,
      total_wallets: 0,
    } satisfies WalletBalancesSnapshot
  }
}
