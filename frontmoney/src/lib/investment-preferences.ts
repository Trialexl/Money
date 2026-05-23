export type InvestmentDisplayCurrency = "USD" | "EUR" | "RUB"

const DISPLAY_CURRENCY_KEY = "investment.displayCurrency"
const SELECTED_PORTFOLIO_KEY = "investment.selectedPortfolioId"
const DISPLAY_CURRENCIES: InvestmentDisplayCurrency[] = ["USD", "EUR", "RUB"]

function getStorage() {
  return typeof window === "undefined" ? null : window.localStorage
}

export function readInvestmentDisplayCurrency(): InvestmentDisplayCurrency {
  const value = getStorage()?.getItem(DISPLAY_CURRENCY_KEY)
  return DISPLAY_CURRENCIES.includes(value as InvestmentDisplayCurrency) ? (value as InvestmentDisplayCurrency) : "USD"
}

export function writeInvestmentDisplayCurrency(currency: InvestmentDisplayCurrency) {
  getStorage()?.setItem(DISPLAY_CURRENCY_KEY, currency)
}

export function readSelectedInvestmentPortfolioId() {
  return getStorage()?.getItem(SELECTED_PORTFOLIO_KEY) ?? ""
}

export function writeSelectedInvestmentPortfolioId(portfolioId: string) {
  if (!portfolioId) {
    getStorage()?.removeItem(SELECTED_PORTFOLIO_KEY)
    return
  }
  getStorage()?.setItem(SELECTED_PORTFOLIO_KEY, portfolioId)
}
