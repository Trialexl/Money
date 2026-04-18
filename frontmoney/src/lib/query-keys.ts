export const queryKeys = {
  dashboardOverview: ["dashboard-overview"] as const,
  reportsAnalytics: ["reports-analytics"] as const,
  profile: ["profile"] as const,
  wallets: {
    all: ["wallets"] as const,
    active: ["wallets", "active"] as const,
    withBalances: ["wallets", "with-balances"] as const,
    detail: (id: string) => ["wallet", id] as const,
    duplicate: (id: string) => ["wallet-duplicate", id] as const,
    balance: (id: string) => ["wallet-balance", id] as const,
  },
  projects: {
    all: ["projects"] as const,
    active: ["projects", "active"] as const,
    detail: (id: string) => ["project", id] as const,
    duplicate: (id: string) => ["project-duplicate", id] as const,
  },
  cashFlowItems: {
    all: ["cash-flow-items"] as const,
    active: ["cash-flow-items", "active"] as const,
    tree: ["cash-flow-items", "tree"] as const,
    detail: (id: string) => ["cash-flow-item", id] as const,
    parentOptions: (excludedId?: string) => ["cash-flow-items", "parent-options", excludedId ?? "root"] as const,
  },
  receipts: {
    all: ["receipts"] as const,
    detail: (id: string) => ["receipt", id] as const,
    duplicate: (id: string) => ["receipt-duplicate", id] as const,
  },
  expenditures: {
    all: ["expenditures"] as const,
    detail: (id: string) => ["expenditure", id] as const,
    duplicate: (id: string) => ["expenditure-duplicate", id] as const,
  },
  transfers: {
    all: ["transfers"] as const,
    detail: (id: string) => ["transfer", id] as const,
    duplicate: (id: string) => ["transfer-duplicate", id] as const,
  },
  budgets: {
    all: ["budgets"] as const,
    detail: (id: string) => ["budget", id] as const,
    duplicate: (id: string) => ["budget-duplicate", id] as const,
  },
  autoPayments: {
    all: ["auto-payments"] as const,
    detail: (id: string) => ["auto-payment", id] as const,
    duplicate: (id: string) => ["auto-payment-duplicate", id] as const,
  },
}
