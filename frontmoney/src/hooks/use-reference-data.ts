"use client"

import { useQuery } from "@tanstack/react-query"

import { queryKeys } from "@/lib/query-keys"
import { CashFlowItemHierarchy, CashFlowItemService } from "@/services/cash-flow-item-service"
import { ProjectService } from "@/services/project-service"
import { WalletService } from "@/services/wallet-service"

function sortByName<T extends { name: string | null | undefined }>(items: T[]) {
  return [...items].sort((left, right) => (left.name ?? "").localeCompare(right.name ?? "", "ru"))
}

function pruneHierarchy(nodes: CashFlowItemHierarchy[], allowedIds: Set<string>): CashFlowItemHierarchy[] {
  return nodes.flatMap((node) => {
    if (!allowedIds.has(node.id)) {
      return []
    }

    return [
      {
        ...node,
        children: Array.isArray(node.children) ? pruneHierarchy(node.children, allowedIds) : [],
      },
    ]
  })
}

export function useActiveWalletsQuery() {
  return useQuery({
    queryKey: queryKeys.wallets.active,
    queryFn: async () => {
      const wallets = await WalletService.getWallets()
      return wallets.filter((wallet) => !wallet.deleted).sort((left, right) => left.name.localeCompare(right.name, "ru"))
    },
  })
}

export function useWalletsWithBalancesQuery() {
  return useQuery({
    queryKey: queryKeys.wallets.withBalances,
    queryFn: async () => {
      const wallets = await WalletService.getWallets()
      const activeWallets = wallets
        .filter((wallet) => !wallet.deleted)
        .sort((left, right) => left.name.localeCompare(right.name, "ru"))

      const balances = await Promise.all(
        activeWallets.map(async (wallet) => {
          try {
            const result = await WalletService.getWalletBalance(wallet.id)
            return [wallet.id, result.balance] as const
          } catch {
            return [wallet.id, 0] as const
          }
        })
      )

      return {
        wallets: activeWallets,
        balances: Object.fromEntries(balances),
      }
    },
  })
}

export function useWalletBalanceQuery(walletId: string) {
  return useQuery({
    queryKey: walletId ? queryKeys.wallets.balance(walletId) : ["wallet-balance", "idle"],
    enabled: Boolean(walletId),
    queryFn: () => WalletService.getWalletBalance(walletId),
  })
}

export function useActiveProjectsQuery() {
  return useQuery({
    queryKey: queryKeys.projects.active,
    queryFn: async () => {
      const projects = await ProjectService.getProjects()
      return projects.filter((project) => !project.deleted).sort((left, right) => left.name.localeCompare(right.name, "ru"))
    },
  })
}

export function useActiveCashFlowItemsQuery() {
  return useQuery({
    queryKey: queryKeys.cashFlowItems.active,
    queryFn: async () => {
      const items = await CashFlowItemService.getCashFlowItems()
      return sortByName(items.filter((item) => !item.deleted))
    },
  })
}

export function useCashFlowTreeQuery() {
  return useQuery({
    queryKey: queryKeys.cashFlowItems.tree,
    queryFn: async () => {
      const [items, hierarchy] = await Promise.all([
        CashFlowItemService.getCashFlowItems(),
        CashFlowItemService.getCashFlowItemHierarchy(),
      ])

      const activeItems = sortByName(items.filter((item) => !item.deleted))
      const allowedIds = new Set(activeItems.map((item) => item.id))

      return {
        items: activeItems,
        hierarchy: pruneHierarchy(hierarchy, allowedIds),
      }
    },
  })
}

export function useCashFlowParentOptionsQuery(excludedId?: string) {
  return useQuery({
    queryKey: queryKeys.cashFlowItems.parentOptions(excludedId),
    queryFn: async () => {
      const items = await CashFlowItemService.getCashFlowItems()
      return sortByName(items.filter((item) => !item.deleted && item.id !== excludedId))
    },
  })
}

export function useOperationReferenceDataQuery() {
  const walletsQuery = useActiveWalletsQuery()
  const cashFlowItemsQuery = useActiveCashFlowItemsQuery()

  return {
    walletsQuery,
    cashFlowItemsQuery,
    wallets: walletsQuery.data ?? [],
    cashFlowItems: cashFlowItemsQuery.data ?? [],
    isLoading: walletsQuery.isLoading || cashFlowItemsQuery.isLoading,
    isError: walletsQuery.isError || cashFlowItemsQuery.isError,
  }
}
