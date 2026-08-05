import { describe, expect, it } from "vitest"

import {
  calculateInvestmentPortfolioShare,
  getInvestmentChartDateKey,
  getSortedInvestmentChartDateKeys,
  splitInvestmentChartSeriesOnDateGaps,
} from "@/lib/investment-report-charts"

describe("investment report chart helpers", () => {
  it("sorts a shared time domain when instruments start on different dates", () => {
    const dateKeys = getSortedInvestmentChartDateKeys([
      { data: [{ x: "2026-07-16" }, { x: "2026-08-05" }] },
      { data: [{ x: "2026-01-05" }, { x: "2026-07-15" }] },
    ])

    expect(dateKeys).toEqual([
      "2026-01-05",
      "2026-07-15",
      "2026-07-16",
      "2026-08-05",
    ])
  })

  it("uses canonical chart dates for daily and monthly points", () => {
    expect(getInvestmentChartDateKey("2026-07-16T05:00:00Z", "day")).toBe("2026-07-16")
    expect(getInvestmentChartDateKey("2026-07-31", "month")).toBe("2026-07-01")
  })

  it("does not turn an unknown portfolio total into a zero-percent allocation", () => {
    expect(calculateInvestmentPortfolioShare(854_890.78, undefined)).toBeNull()
    expect(calculateInvestmentPortfolioShare(854_890.78, 0)).toBeNull()
    expect(calculateInvestmentPortfolioShare(50, 200)).toBe(25)
  })

  it("breaks a daily series across a missing valuation date", () => {
    expect(splitInvestmentChartSeriesOnDateGaps([
      { x: "2026-07-03" },
      { x: "2026-07-01" },
    ], "day")).toEqual([
      [{ x: "2026-07-01" }],
      [{ x: "2026-07-03" }],
    ])
  })
})
