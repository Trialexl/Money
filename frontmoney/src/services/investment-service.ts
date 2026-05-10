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

export interface InvestmentPosition {
  instrument_id: string
  instrument_ticker: string
  instrument_name: string
  quantity: number
  cost_basis_rub: number
  average_buy_price_rub: number
  realized_pl_rub: number
  bought_rub: number
  sold_rub: number
}

export interface InvestmentOverview {
  portfolio: InvestmentPortfolio | null
  cost_basis_rub: number
  realized_pl_rub: number
  bought_rub: number
  sold_rub: number
  positions: InvestmentPosition[]
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

function mapPosition(raw: any): InvestmentPosition {
  return {
    instrument_id: raw.instrument_id,
    instrument_ticker: raw.instrument_ticker ?? "",
    instrument_name: raw.instrument_name ?? "",
    quantity: fromApiAmount(raw.quantity),
    cost_basis_rub: fromApiAmount(raw.cost_basis_rub),
    average_buy_price_rub: fromApiAmount(raw.average_buy_price_rub),
    realized_pl_rub: fromApiAmount(raw.realized_pl_rub),
    bought_rub: fromApiAmount(raw.bought_rub),
    sold_rub: fromApiAmount(raw.sold_rub),
  }
}

function mapOverview(raw: any): InvestmentOverview {
  return {
    portfolio: raw.portfolio ? mapPortfolio(raw.portfolio) : null,
    cost_basis_rub: fromApiAmount(raw.cost_basis_rub),
    realized_pl_rub: fromApiAmount(raw.realized_pl_rub),
    bought_rub: fromApiAmount(raw.bought_rub),
    sold_rub: fromApiAmount(raw.sold_rub),
    positions: Array.isArray(raw.positions) ? raw.positions.map(mapPosition) : [],
  }
}

export const InvestmentService = {
  async getOverview() {
    const response = await api.get("/investment/portfolio-overview/")
    return mapOverview(response.data)
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

  async getOperations() {
    const response = await api.get("/investment/operations/")
    const data = Array.isArray(response.data?.results) ? response.data.results : response.data
    return Array.isArray(data) ? data.map(mapOperation) : []
  },

  async createOperation(payload: Partial<InvestmentOperation>) {
    const response = await api.post("/investment/operations/", {
      ...payload,
      date: toApiDateTime(payload.date),
      quantity: payload.quantity?.toString(),
      price: payload.price === undefined ? undefined : payload.price.toString(),
      amount: payload.amount === undefined ? undefined : payload.amount.toString(),
      amount_rub: toApiAmount(payload.amount_rub),
      fee_amount: payload.fee_amount === undefined ? undefined : payload.fee_amount.toString(),
      fee_rub: toApiAmount(payload.fee_rub),
      fx_rate_to_rub: payload.fx_rate_to_rub === undefined ? undefined : payload.fx_rate_to_rub.toString(),
    })
    return mapOperation(response.data)
  },
}
