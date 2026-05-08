import { describe, expect, it } from "vitest"

import { parseAmountExpression } from "@/lib/amount-expression"

describe("parseAmountExpression", () => {
  it("parses basic arithmetic expressions", () => {
    expect(parseAmountExpression("6000-4000")).toBe(2000)
    expect(parseAmountExpression("1000 + 250,50")).toBe(1250.5)
    expect(parseAmountExpression("(100+50)*2")).toBe(300)
  })

  it("rejects unsafe or invalid expressions", () => {
    expect(parseAmountExpression("alert(1)")).toBeNull()
    expect(parseAmountExpression("100/0")).toBeNull()
    expect(parseAmountExpression("")).toBeNull()
  })
})
