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
  price?: number
  price_currency: string
  amount?: number
  amount_currency: string
  amount_rub: number
  fx_rate_to_rub: number
  fee_amount: number
  fee_currency: string
  fee_rub: number
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
  fx_rate_to_rub: number
  price_rub: number
  source: string
}

export interface InvestmentPosition {
  instrument_id: string
  instrument_ticker: string
  instrument_name: string
  quantity: number
  cost_basis_rub: number
  average_buy_price_rub: number
  latest_price_rub?: number | null
  latest_price_at?: string | null
  current_value_rub?: number | null
  realized_pl_rub: number
  unrealized_pl_rub?: number | null
  total_pl_rub: number
  return_percent?: number | null
  bought_rub: number
  sold_rub: number
  allocation_percent?: number | null
  target_allocation_percent?: number | null
  allocation_deviation_percent?: number | null
}

export interface InvestmentOverview {
  portfolio: InvestmentPortfolio | null
  cost_basis_rub: number
  current_value_rub: number
  realized_pl_rub: number
  unrealized_pl_rub: number
  total_pl_rub: number
  return_percent?: number | null
  valuation_complete: boolean
  bought_rub: number
  sold_rub: number
  largest_asset?: InvestmentPosition | null
  latest_price_at?: string | null
  positions: InvestmentPosition[]
}

export interface InvestmentPerformancePoint {
  label: string
  date: string
  period_start?: string | null
  period_end: string
  cost_basis_rub: number
  current_value_rub: number
  realized_pl_rub: number
  unrealized_pl_rub: number
  total_pl_rub: number
  bought_rub: number
  sold_rub: number
  valuation_complete: boolean
}

export interface InvestmentPerformance {
  portfolio_id: string
  date_from: string
  date_to: string
  group_by: "day" | "month"
  opening: InvestmentPerformancePoint
  points: InvestmentPerformancePoint[]
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
    base_currency: raw.base_currency ?? "RUB",
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
    currency: raw.currency ?? "RUB",
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
    price: raw.price === null || raw.price === undefined ? undefined : fromApiAmount(raw.price),
    price_currency: raw.price_currency ?? "RUB",
    amount: raw.amount === null || raw.amount === undefined ? undefined : fromApiAmount(raw.amount),
    amount_currency: raw.amount_currency ?? "RUB",
    amount_rub: fromApiAmount(raw.amount_rub),
    fx_rate_to_rub: fromApiAmount(raw.fx_rate_to_rub),
    fee_amount: fromApiAmount(raw.fee_amount),
    fee_currency: raw.fee_currency ?? "RUB",
    fee_rub: fromApiAmount(raw.fee_rub),
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
    fx_rate_to_rub: fromApiAmount(raw.fx_rate_to_rub),
    price_rub: fromApiAmount(raw.price_rub),
    source: raw.source ?? "manual",
  }
}

function mapPosition(raw: any): InvestmentPosition {
  return {
    instrument_id: raw.instrument_id,
    instrument_ticker: raw.instrument_ticker ?? "",
    instrument_name: raw.instrument_name ?? "",
    quantity: fromApiAmount(raw.quantity),
    cost_basis_rub: fromApiAmount(raw.cost_basis_rub),
    average_buy_price_rub: fromApiAmount(raw.average_buy_price_rub),
    latest_price_rub: fromApiNullableAmount(raw.latest_price_rub),
    latest_price_at: fromApiDateTime(raw.latest_price_at) ?? null,
    current_value_rub: fromApiNullableAmount(raw.current_value_rub),
    realized_pl_rub: fromApiAmount(raw.realized_pl_rub),
    unrealized_pl_rub: fromApiNullableAmount(raw.unrealized_pl_rub),
    total_pl_rub: fromApiAmount(raw.total_pl_rub),
    return_percent: fromApiNullableAmount(raw.return_percent),
    bought_rub: fromApiAmount(raw.bought_rub),
    sold_rub: fromApiAmount(raw.sold_rub),
    allocation_percent: fromApiNullableAmount(raw.allocation_percent),
    target_allocation_percent: fromApiNullableAmount(raw.target_allocation_percent),
    allocation_deviation_percent: fromApiNullableAmount(raw.allocation_deviation_percent),
  }
}

function mapOverview(raw: any): InvestmentOverview {
  return {
    portfolio: raw.portfolio ? mapPortfolio(raw.portfolio) : null,
    cost_basis_rub: fromApiAmount(raw.cost_basis_rub),
    current_value_rub: fromApiAmount(raw.current_value_rub),
    realized_pl_rub: fromApiAmount(raw.realized_pl_rub),
    unrealized_pl_rub: fromApiAmount(raw.unrealized_pl_rub),
    total_pl_rub: fromApiAmount(raw.total_pl_rub),
    return_percent: fromApiNullableAmount(raw.return_percent),
    valuation_complete: raw.valuation_complete !== false,
    bought_rub: fromApiAmount(raw.bought_rub),
    sold_rub: fromApiAmount(raw.sold_rub),
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
    cost_basis_rub: fromApiAmount(raw.cost_basis_rub),
    current_value_rub: fromApiAmount(raw.current_value_rub),
    realized_pl_rub: fromApiAmount(raw.realized_pl_rub),
    unrealized_pl_rub: fromApiAmount(raw.unrealized_pl_rub),
    total_pl_rub: fromApiAmount(raw.total_pl_rub),
    bought_rub: fromApiAmount(raw.bought_rub),
    sold_rub: fromApiAmount(raw.sold_rub),
    valuation_complete: raw.valuation_complete !== false,
  }
}

function mapPerformance(raw: any): InvestmentPerformance {
  return {
    portfolio_id: raw.portfolio_id ?? "",
    date_from: raw.date_from ?? "",
    date_to: raw.date_to ?? "",
    group_by: raw.group_by === "day" ? "day" : "month",
    opening: mapPerformancePoint(raw.opening ?? {}),
    points: Array.isArray(raw.points) ? raw.points.map(mapPerformancePoint) : [],
  }
}

function toOperationPayload(payload: Partial<InvestmentOperationPayload>) {
  return {
    ...payload,
    date: toApiDateTime(payload.date),
    account_to: payload.account_to || null,
    quantity: payload.quantity === undefined ? undefined : payload.quantity.toString(),
    price: payload.price === undefined ? undefined : payload.price.toString(),
    amount: payload.amount === undefined ? undefined : payload.amount.toString(),
    amount_rub: toApiAmount(payload.amount_rub),
    fee_amount: payload.fee_amount === undefined ? undefined : payload.fee_amount.toString(),
    fee_rub: toApiAmount(payload.fee_rub),
    fx_rate_to_rub: payload.fx_rate_to_rub === undefined ? undefined : payload.fx_rate_to_rub.toString(),
  }
}

function toPricePayload(payload: Partial<InstrumentPriceSnapshotPayload>) {
  return {
    ...payload,
    captured_at: toApiDateTime(payload.captured_at),
    price: payload.price === undefined ? undefined : payload.price.toString(),
    fx_rate_to_rub: payload.fx_rate_to_rub === undefined ? undefined : payload.fx_rate_to_rub.toString(),
    price_rub: toApiAmount(payload.price_rub),
  }
}

export const InvestmentService = {
  async getOverview() {
    const response = await api.get("/investment/portfolio-overview/")
    return mapOverview(response.data)
  },

  async getPortfolioPerformance(portfolioId: string, params?: { date_from?: string; date_to?: string; group_by?: "day" | "month" }) {
    const response = await api.get(`/investment/portfolios/${portfolioId}/performance/`, { params })
    return mapPerformance(response.data)
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
