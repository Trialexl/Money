import api from "@/lib/api"
import { fromApiAmount, fromApiDateTime, toApiAmount, toApiDateTime } from "@/types"

export type InstrumentType = "crypto" | "stock"
export type InvestmentOperationType = "buy" | "sell" | "transfer_instrument" | "correction"

export interface Instrument {
  id: string
  type: InstrumentType
  ticker: string
  name: string
  provider_symbol: string
  quote_currency: string
  precision: number
  is_active: boolean
}

export interface InvestmentPortfolio {
  id: string
  name: string
  base_currency: string
  project?: string | null
  is_default: boolean
}

export interface InvestmentAccount {
  id: string
  portfolio: string
  portfolio_name?: string
  name: string
  type: string
  currency: string
  hidden: boolean
}

export interface InvestmentOperation {
  id: string
  number?: string
  date: string
  portfolio: string
  portfolio_name?: string
  account: string
  account_name?: string
  account_to?: string | null
  account_to_name?: string
  instrument: string
  instrument_ticker?: string
  instrument_name?: string
  operation_type: InvestmentOperationType
  quantity: number
  price_usd?: number
  amount_usd: number
  fee_usd: number
  comment?: string
  deleted: boolean
  posted: boolean
}

export interface InstrumentPriceSnapshot {
  id: string
  instrument: string
  instrument_ticker?: string
  instrument_name?: string
  captured_at: string
  price: number
  price_currency: string
  fx_rate_to_usd: number
  price_usd: number
  source: string
}

export interface InstrumentPriceLookup {
  found: boolean
  instrument: string
  instrument_ticker?: string
  date: string
  snapshot_id?: string
  snapshot_date?: string
  is_exact_date?: boolean
  stale_days?: number
  price?: number
  price_currency?: string
  fx_rate_to_usd?: number
  price_usd?: number
  source?: string
  detail?: string
}

export interface FxRateSnapshot {
  id: string
  captured_at: string
  base_currency: string
  quote_currency: string
  rate: number
  source: string
}

export interface InvestmentPosition {
  instrument_id: string
  instrument_ticker: string
  instrument_name: string
  quantity: number
  cost_basis_usd: number
  average_buy_price_usd: number
  latest_price_usd?: number | null
  latest_price_at?: string | null
  current_value_usd?: number | null
  realized_pl_usd: number
  unrealized_pl_usd?: number | null
  total_pl_usd: number
  return_percent?: number | null
  bought_usd: number
  sold_usd: number
  allocation_percent?: number | null
  target_allocation_percent?: number | null
  tolerance_percent?: number | null
  allocation_deviation_percent?: number | null
  target_value_usd?: number | null
  allocation_deviation_usd?: number | null
  rebalance_action?: "buy" | "sell" | "hold" | null
  rebalance_amount_usd?: number | null
  is_within_tolerance?: boolean | null
}

export interface InvestmentOverview {
  portfolio: InvestmentPortfolio | null
  cost_basis_usd: number
  current_value_usd: number
  realized_pl_usd: number
  unrealized_pl_usd: number
  total_pl_usd: number
  return_percent?: number | null
  valuation_complete: boolean
  bought_usd: number
  sold_usd: number
  largest_asset?: InvestmentPosition | null
  latest_price_at?: string | null
  positions: InvestmentPosition[]
}

export interface InvestmentPerformancePoint {
  label: string
  date: string
  period_start?: string | null
  period_end: string
  cost_basis_usd: number
  current_value_usd: number
  realized_pl_usd: number
  unrealized_pl_usd: number
  total_pl_usd: number
  bought_usd: number
  sold_usd: number
  valuation_complete: boolean
  display_currency: string
  fx_rate_to_display?: number | null
  fx_rate_at?: string | null
  display_valuation_complete: boolean
  cost_basis_display?: number | null
  current_value_display?: number | null
  realized_pl_display?: number | null
  unrealized_pl_display?: number | null
  total_pl_display?: number | null
  bought_display?: number | null
  sold_display?: number | null
}

export interface InvestmentPerformance {
  portfolio_id: string
  date_from: string
  date_to: string
  group_by: "day" | "month"
  display_currency: string
  opening: InvestmentPerformancePoint
  points: InvestmentPerformancePoint[]
}

export interface InvestmentTargetAllocation {
  id: string
  portfolio: string
  portfolio_name?: string
  instrument: string
  instrument_ticker?: string
  instrument_name?: string
  target_percent: number
  tolerance_percent: number
}

export interface InvestmentRebalanceStatus {
  portfolio_id: string
  current_value_usd: number
  positions: InvestmentPosition[]
  disclaimer: string
}

export type InstrumentPayload = Omit<Instrument, "id">
export type InvestmentPortfolioPayload = Pick<InvestmentPortfolio, "name" | "is_default"> & {
  project?: string | null
}
export type InvestmentAccountPayload = Omit<InvestmentAccount, "id" | "portfolio_name">
export type InvestmentOperationPayload = Omit<
  InvestmentOperation,
  "id" | "number" | "portfolio_name" | "account_name" | "account_to_name" | "instrument_ticker" | "instrument_name"
>
export type InstrumentPriceSnapshotPayload = Omit<InstrumentPriceSnapshot, "id" | "instrument_ticker" | "instrument_name">
export type FxRateSnapshotPayload = Omit<FxRateSnapshot, "id">
export type InvestmentTargetAllocationPayload = Omit<
  InvestmentTargetAllocation,
  "id" | "portfolio_name" | "instrument_ticker" | "instrument_name"
>

function fromApiNullableAmount(amount: string | number | undefined | null): number | null {
  if (amount === undefined || amount === null || amount === "") {
    return null
  }
  return fromApiAmount(amount)
}

function mapInstrument(raw: any): Instrument {
  return {
    id: raw.id,
    type: raw.type,
    ticker: raw.ticker ?? "",
    name: raw.name ?? "",
    provider_symbol: raw.provider_symbol ?? "",
    quote_currency: raw.quote_currency ?? "USD",
    precision: Number(raw.precision ?? 8),
    is_active: !!raw.is_active,
  }
}

function mapPortfolio(raw: any): InvestmentPortfolio {
  return {
    id: raw.id,
    name: raw.name ?? "",
    base_currency: raw.base_currency ?? "USD",
    project: raw.project ?? null,
    is_default: !!raw.is_default,
  }
}

function mapAccount(raw: any): InvestmentAccount {
  return {
    id: raw.id,
    portfolio: raw.portfolio ?? "",
    portfolio_name: raw.portfolio_name ?? undefined,
    name: raw.name ?? "",
    type: raw.type ?? "manual",
    currency: raw.currency ?? "USD",
    hidden: !!raw.hidden,
  }
}

function mapOperation(raw: any): InvestmentOperation {
  return {
    id: raw.id,
    number: raw.number ?? undefined,
    date: fromApiDateTime(raw.date) ?? "",
    portfolio: raw.portfolio ?? "",
    portfolio_name: raw.portfolio_name ?? undefined,
    account: raw.account ?? "",
    account_name: raw.account_name ?? undefined,
    account_to: raw.account_to ?? null,
    account_to_name: raw.account_to_name ?? undefined,
    instrument: raw.instrument ?? "",
    instrument_ticker: raw.instrument_ticker ?? undefined,
    instrument_name: raw.instrument_name ?? undefined,
    operation_type: raw.operation_type,
    quantity: fromApiAmount(raw.quantity),
    price_usd: raw.price_usd === null || raw.price_usd === undefined ? undefined : fromApiAmount(raw.price_usd),
    amount_usd: fromApiAmount(raw.amount_usd),
    fee_usd: fromApiAmount(raw.fee_usd),
    comment: raw.comment ?? undefined,
    deleted: !!raw.deleted,
    posted: !!raw.posted,
  }
}

function mapPriceSnapshot(raw: any): InstrumentPriceSnapshot {
  return {
    id: raw.id,
    instrument: raw.instrument ?? "",
    instrument_ticker: raw.instrument_ticker ?? undefined,
    instrument_name: raw.instrument_name ?? undefined,
    captured_at: fromApiDateTime(raw.captured_at) ?? "",
    price: fromApiAmount(raw.price),
    price_currency: raw.price_currency ?? "USD",
    fx_rate_to_usd: fromApiAmount(raw.fx_rate_to_usd),
    price_usd: fromApiAmount(raw.price_usd),
    source: raw.source ?? "manual",
  }
}

function mapPriceLookup(raw: any): InstrumentPriceLookup {
  return {
    found: !!raw.found,
    instrument: raw.instrument ?? "",
    instrument_ticker: raw.instrument_ticker ?? undefined,
    date: raw.date ?? "",
    snapshot_id: raw.snapshot_id ?? undefined,
    snapshot_date: raw.snapshot_date ?? undefined,
    is_exact_date: raw.is_exact_date ?? undefined,
    stale_days: raw.stale_days === undefined || raw.stale_days === null ? undefined : Number(raw.stale_days),
    price: fromApiNullableAmount(raw.price) ?? undefined,
    price_currency: raw.price_currency ?? undefined,
    fx_rate_to_usd: fromApiNullableAmount(raw.fx_rate_to_usd) ?? undefined,
    price_usd: fromApiNullableAmount(raw.price_usd) ?? undefined,
    source: raw.source ?? undefined,
    detail: raw.detail ?? undefined,
  }
}

function mapFxRateSnapshot(raw: any): FxRateSnapshot {
  return {
    id: raw.id,
    captured_at: fromApiDateTime(raw.captured_at) ?? "",
    base_currency: raw.base_currency ?? "",
    quote_currency: raw.quote_currency ?? "USD",
    rate: fromApiAmount(raw.rate),
    source: raw.source ?? "manual",
  }
}

function mapPosition(raw: any): InvestmentPosition {
  return {
    instrument_id: raw.instrument_id,
    instrument_ticker: raw.instrument_ticker ?? "",
    instrument_name: raw.instrument_name ?? "",
    quantity: fromApiAmount(raw.quantity),
    cost_basis_usd: fromApiAmount(raw.cost_basis_usd),
    average_buy_price_usd: fromApiAmount(raw.average_buy_price_usd),
    latest_price_usd: fromApiNullableAmount(raw.latest_price_usd),
    latest_price_at: fromApiDateTime(raw.latest_price_at) ?? null,
    current_value_usd: fromApiNullableAmount(raw.current_value_usd),
    realized_pl_usd: fromApiAmount(raw.realized_pl_usd),
    unrealized_pl_usd: fromApiNullableAmount(raw.unrealized_pl_usd),
    total_pl_usd: fromApiAmount(raw.total_pl_usd),
    return_percent: fromApiNullableAmount(raw.return_percent),
    bought_usd: fromApiAmount(raw.bought_usd),
    sold_usd: fromApiAmount(raw.sold_usd),
    allocation_percent: fromApiNullableAmount(raw.allocation_percent),
    target_allocation_percent: fromApiNullableAmount(raw.target_allocation_percent),
    tolerance_percent: fromApiNullableAmount(raw.tolerance_percent),
    allocation_deviation_percent: fromApiNullableAmount(raw.allocation_deviation_percent),
    target_value_usd: fromApiNullableAmount(raw.target_value_usd),
    allocation_deviation_usd: fromApiNullableAmount(raw.allocation_deviation_usd),
    rebalance_action: raw.rebalance_action ?? null,
    rebalance_amount_usd: fromApiNullableAmount(raw.rebalance_amount_usd),
    is_within_tolerance: raw.is_within_tolerance ?? null,
  }
}

function mapTargetAllocation(raw: any): InvestmentTargetAllocation {
  return {
    id: raw.id,
    portfolio: raw.portfolio ?? "",
    portfolio_name: raw.portfolio_name ?? undefined,
    instrument: raw.instrument ?? "",
    instrument_ticker: raw.instrument_ticker ?? undefined,
    instrument_name: raw.instrument_name ?? undefined,
    target_percent: fromApiAmount(raw.target_percent),
    tolerance_percent: fromApiAmount(raw.tolerance_percent),
  }
}

function mapOverview(raw: any): InvestmentOverview {
  return {
    portfolio: raw.portfolio ? mapPortfolio(raw.portfolio) : null,
    cost_basis_usd: fromApiAmount(raw.cost_basis_usd),
    current_value_usd: fromApiAmount(raw.current_value_usd),
    realized_pl_usd: fromApiAmount(raw.realized_pl_usd),
    unrealized_pl_usd: fromApiAmount(raw.unrealized_pl_usd),
    total_pl_usd: fromApiAmount(raw.total_pl_usd),
    return_percent: fromApiNullableAmount(raw.return_percent),
    valuation_complete: raw.valuation_complete !== false,
    bought_usd: fromApiAmount(raw.bought_usd),
    sold_usd: fromApiAmount(raw.sold_usd),
    largest_asset: raw.largest_asset ? mapPosition(raw.largest_asset) : null,
    latest_price_at: fromApiDateTime(raw.latest_price_at) ?? null,
    positions: Array.isArray(raw.positions) ? raw.positions.map(mapPosition) : [],
  }
}

function mapPerformancePoint(raw: any): InvestmentPerformancePoint {
  return {
    label: raw.label ?? "",
    date: raw.date ?? "",
    period_start: raw.period_start ?? null,
    period_end: raw.period_end ?? "",
    cost_basis_usd: fromApiAmount(raw.cost_basis_usd),
    current_value_usd: fromApiAmount(raw.current_value_usd),
    realized_pl_usd: fromApiAmount(raw.realized_pl_usd),
    unrealized_pl_usd: fromApiAmount(raw.unrealized_pl_usd),
    total_pl_usd: fromApiAmount(raw.total_pl_usd),
    bought_usd: fromApiAmount(raw.bought_usd),
    sold_usd: fromApiAmount(raw.sold_usd),
    valuation_complete: raw.valuation_complete !== false,
    display_currency: raw.display_currency ?? "USD",
    fx_rate_to_display: fromApiNullableAmount(raw.fx_rate_to_display),
    fx_rate_at: fromApiDateTime(raw.fx_rate_at) ?? null,
    display_valuation_complete: raw.display_valuation_complete !== false,
    cost_basis_display: fromApiNullableAmount(raw.cost_basis_display),
    current_value_display: fromApiNullableAmount(raw.current_value_display),
    realized_pl_display: fromApiNullableAmount(raw.realized_pl_display),
    unrealized_pl_display: fromApiNullableAmount(raw.unrealized_pl_display),
    total_pl_display: fromApiNullableAmount(raw.total_pl_display),
    bought_display: fromApiNullableAmount(raw.bought_display),
    sold_display: fromApiNullableAmount(raw.sold_display),
  }
}

function mapPerformance(raw: any): InvestmentPerformance {
  return {
    portfolio_id: raw.portfolio_id ?? "",
    date_from: raw.date_from ?? "",
    date_to: raw.date_to ?? "",
    group_by: raw.group_by === "day" ? "day" : "month",
    display_currency: raw.display_currency ?? "USD",
    opening: mapPerformancePoint(raw.opening ?? {}),
    points: Array.isArray(raw.points) ? raw.points.map(mapPerformancePoint) : [],
  }
}

function mapRebalanceStatus(raw: any): InvestmentRebalanceStatus {
  return {
    portfolio_id: raw.portfolio_id ?? "",
    current_value_usd: fromApiAmount(raw.current_value_usd),
    positions: Array.isArray(raw.positions) ? raw.positions.map(mapPosition) : [],
    disclaimer: raw.disclaimer ?? "",
  }
}

function toOperationPayload(payload: Partial<InvestmentOperationPayload>) {
  return {
    ...payload,
    date: toApiDateTime(payload.date),
    account_to: payload.account_to || null,
    quantity: payload.quantity === undefined ? undefined : payload.quantity.toString(),
    price_usd: payload.price_usd === undefined ? undefined : payload.price_usd.toString(),
    amount_usd: toApiAmount(payload.amount_usd),
    fee_usd: toApiAmount(payload.fee_usd),
  }
}

function toPricePayload(payload: Partial<InstrumentPriceSnapshotPayload>) {
  return {
    ...payload,
    captured_at: toApiDateTime(payload.captured_at),
    price: payload.price === undefined ? undefined : payload.price.toString(),
    fx_rate_to_usd: payload.fx_rate_to_usd === undefined ? undefined : payload.fx_rate_to_usd.toString(),
    price_usd: toApiAmount(payload.price_usd),
  }
}

function toTargetAllocationPayload(payload: InvestmentTargetAllocationPayload | Partial<InvestmentTargetAllocationPayload>) {
  return {
    ...payload,
    target_percent: payload.target_percent === undefined ? undefined : payload.target_percent.toString(),
    tolerance_percent: payload.tolerance_percent === undefined ? undefined : payload.tolerance_percent.toString(),
  }
}

export const InvestmentService = {
  async getOverview() {
    const response = await api.get("/investment/portfolio-overview/")
    return mapOverview(response.data)
  },

  async getPortfolioPerformance(portfolioId: string, params?: { date_from?: string; date_to?: string; group_by?: "day" | "month"; display_currency?: string }) {
    const response = await api.get(`/investment/portfolios/${portfolioId}/performance/`, { params })
    return mapPerformance(response.data)
  },

  async getPortfolioRebalance(portfolioId: string) {
    const response = await api.get(`/investment/portfolios/${portfolioId}/rebalance/`)
    return mapRebalanceStatus(response.data)
  },

  async getInstruments() {
    const response = await api.get("/investment/instruments/")
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapInstrument) : []
  },

  async getPortfolios() {
    const response = await api.get("/investment/portfolios/")
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapPortfolio) : []
  },

  async getAccounts() {
    const response = await api.get("/investment/accounts/")
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapAccount) : []
  },

  async getTargetAllocations(params?: { portfolio?: string; instrument?: string }) {
    const response = await api.get("/investment/target-allocations/", { params })
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapTargetAllocation) : []
  },

  async getOperations(params?: {
    date_from?: string
    date_to?: string
    instrument?: string
    account?: string
    operation_type?: InvestmentOperationType
  }) {
    const response = await api.get("/investment/operations/", { params })
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapOperation) : []
  },

  async getPrices(params?: { instrument?: string }) {
    const response = await api.get("/investment/prices/", { params })
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapPriceSnapshot) : []
  },

  async lookupPrice(params: { instrument: string; date: string }) {
    const response = await api.get("/investment/prices/lookup/", { params })
    return mapPriceLookup(response.data)
  },

  async getFxRates(params?: { base_currency?: string; quote_currency?: string }) {
    const response = await api.get("/investment/fx-rates/", { params })
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapFxRateSnapshot) : []
  },

  async refreshFxRates() {
    const response = await api.post("/investment/fx-rates/refresh/")
    return response.data
  },

  async backfillFxRates(params?: { date_from?: string; date_to?: string }) {
    const response = await api.post("/investment/fx-rates/backfill/", null, { params })
    return response.data
  },

  async createPortfolio(payload: InvestmentPortfolioPayload) {
    const response = await api.post("/investment/portfolios/", payload)
    return mapPortfolio(response.data)
  },

  async updatePortfolio(id: string, payload: Partial<InvestmentPortfolioPayload>) {
    const response = await api.patch(`/investment/portfolios/${id}/`, payload)
    return mapPortfolio(response.data)
  },

  async deletePortfolio(id: string) {
    await api.delete(`/investment/portfolios/${id}/`)
  },

  async createInstrument(payload: InstrumentPayload) {
    const response = await api.post("/investment/instruments/", payload)
    return mapInstrument(response.data)
  },

  async updateInstrument(id: string, payload: Partial<InstrumentPayload>) {
    const response = await api.patch(`/investment/instruments/${id}/`, payload)
    return mapInstrument(response.data)
  },

  async deleteInstrument(id: string) {
    await api.delete(`/investment/instruments/${id}/`)
  },

  async createPrice(payload: Partial<InstrumentPriceSnapshotPayload>) {
    const response = await api.post("/investment/prices/", toPricePayload(payload))
    return mapPriceSnapshot(response.data)
  },

  async refreshPrices() {
    const response = await api.post("/investment/prices/refresh/")
    return response.data
  },

  async backfillPrices(params?: { date_from?: string; date_to?: string }) {
    const response = await api.post("/investment/prices/backfill/", null, { params })
    return response.data
  },

  async createAccount(payload: InvestmentAccountPayload) {
    const response = await api.post("/investment/accounts/", payload)
    return mapAccount(response.data)
  },

  async updateAccount(id: string, payload: Partial<InvestmentAccountPayload>) {
    const response = await api.patch(`/investment/accounts/${id}/`, payload)
    return mapAccount(response.data)
  },

  async deleteAccount(id: string) {
    await api.delete(`/investment/accounts/${id}/`)
  },

  async createTargetAllocation(payload: InvestmentTargetAllocationPayload) {
    const response = await api.post("/investment/target-allocations/", toTargetAllocationPayload(payload))
    return mapTargetAllocation(response.data)
  },

  async updateTargetAllocation(id: string, payload: Partial<InvestmentTargetAllocationPayload>) {
    const response = await api.patch(`/investment/target-allocations/${id}/`, toTargetAllocationPayload(payload))
    return mapTargetAllocation(response.data)
  },

  async deleteTargetAllocation(id: string) {
    await api.delete(`/investment/target-allocations/${id}/`)
  },

  async createOperation(payload: Partial<InvestmentOperationPayload>) {
    const response = await api.post("/investment/operations/", toOperationPayload(payload))
    return mapOperation(response.data)
  },

  async updateOperation(id: string, payload: Partial<InvestmentOperationPayload>) {
    const response = await api.patch(`/investment/operations/${id}/`, toOperationPayload(payload))
    return mapOperation(response.data)
  },

  async deleteOperation(id: string) {
    await api.delete(`/investment/operations/${id}/`)
  },
}
