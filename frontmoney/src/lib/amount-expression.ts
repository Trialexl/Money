export function parseAmountExpression(input: string | number | null | undefined): number | null {
  if (typeof input === "number") {
    return Number.isFinite(input) ? Math.round(input * 100) / 100 : null
  }

  const source = String(input ?? "")
    .replace(/\s+/g, "")
    .replace(/,/g, ".")

  if (!source || !/^[0-9+\-*/().]+$/.test(source)) {
    return null
  }

  let index = 0

  const peek = () => source[index]
  const consume = () => source[index++]

  const parseNumber = () => {
    const start = index
    while (/[0-9.]/.test(peek() ?? "")) {
      consume()
    }

    const token = source.slice(start, index)
    if (!token || token.split(".").length > 2) {
      throw new Error("Invalid number")
    }

    const value = Number(token)
    if (!Number.isFinite(value)) {
      throw new Error("Invalid number")
    }
    return value
  }

  const parseFactor = (): number => {
    const char = peek()

    if (char === "+") {
      consume()
      return parseFactor()
    }

    if (char === "-") {
      consume()
      return -parseFactor()
    }

    if (char === "(") {
      consume()
      const value = parseExpression()
      if (peek() !== ")") {
        throw new Error("Missing closing parenthesis")
      }
      consume()
      return value
    }

    return parseNumber()
  }

  const parseTerm = (): number => {
    let value = parseFactor()

    while (peek() === "*" || peek() === "/") {
      const operator = consume()
      const right = parseFactor()
      if (operator === "*") {
        value *= right
      } else {
        if (right === 0) {
          throw new Error("Division by zero")
        }
        value /= right
      }
    }

    return value
  }

  function parseExpression(): number {
    let value = parseTerm()

    while (peek() === "+" || peek() === "-") {
      const operator = consume()
      const right = parseTerm()
      value = operator === "+" ? value + right : value - right
    }

    return value
  }

  try {
    const value = parseExpression()
    if (index !== source.length || !Number.isFinite(value)) {
      return null
    }
    return Math.round(value * 100) / 100
  } catch {
    return null
  }
}

export function formatAmountExpressionValue(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return ""
  }

  return String(Math.round(value * 100) / 100)
}

export function normalizeAmountExpressionInput(input: string): string {
  const parsed = parseAmountExpression(input)
  return parsed === null ? input : formatAmountExpressionValue(parsed)
}
