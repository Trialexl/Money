export type InvestmentChartGroupBy = "day" | "month"

export type InvestmentChartDatePoint = {
  x: string
}

export function getInvestmentPeriodKey(value: string, groupBy: InvestmentChartGroupBy) {
  const dateKey = value.slice(0, 10)
  return groupBy === "month" ? dateKey.slice(0, 7) : dateKey
}

export function getInvestmentChartDateKey(value: string, groupBy: InvestmentChartGroupBy) {
  const periodKey = getInvestmentPeriodKey(value, groupBy)
  return groupBy === "month" ? `${periodKey}-01` : periodKey
}

export function parseInvestmentChartDate(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  if (!year || !month || !day) {
    return null
  }
  return new Date(year, month - 1, day)
}

export function getSortedInvestmentChartDateKeys(
  series: Array<{ data: InvestmentChartDatePoint[] }>,
) {
  return Array.from(new Set(series.flatMap((item) => item.data.map((point) => point.x))))
    .sort((left, right) => left.localeCompare(right))
}

export function splitInvestmentChartSeriesOnDateGaps<T extends InvestmentChartDatePoint>(
  points: T[],
  groupBy: InvestmentChartGroupBy,
) {
  const maxGapDays = groupBy === "month" ? 45 : 1
  const segments: T[][] = []
  let current: T[] = []

  const sortedPoints = [...points].sort((left, right) => left.x.localeCompare(right.x))
  sortedPoints.forEach((point) => {
    const previous = current[current.length - 1]
    const previousDate = previous ? parseInvestmentChartDate(previous.x) : null
    const currentDate = parseInvestmentChartDate(point.x)
    const gapDays = previousDate && currentDate
      ? Math.round((currentDate.getTime() - previousDate.getTime()) / 86_400_000)
      : 0

    if (previous && gapDays > maxGapDays) {
      segments.push(current)
      current = []
    }
    current.push(point)
  })

  if (current.length > 0) {
    segments.push(current)
  }

  return segments
}

export function calculateInvestmentPortfolioShare(
  instrumentValue: number,
  portfolioValue: number | null | undefined,
) {
  if (
    !Number.isFinite(instrumentValue) ||
    portfolioValue === null ||
    portfolioValue === undefined ||
    !Number.isFinite(portfolioValue) ||
    portfolioValue <= 0
  ) {
    return null
  }
  return (instrumentValue / portfolioValue) * 100
}
