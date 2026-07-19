import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AssistantReply } from "@/components/shared/assistant-reply"
import type { AiAssistantResponse } from "@/services/ai-service"

function response(overrides: Partial<AiAssistantResponse>): AiAssistantResponse {
  return {
    status: "info",
    intent: "test",
    provider: "test",
    confidence: 1,
    reply_text: "",
    ...overrides,
  }
}

describe("AssistantReply", () => {
  it("links wallets and cash flow items to their pages", () => {
    render(
      <AssistantReply
        response={response({
          reply_text: "Кошелек Сбербанк, статья Продукты.",
          entity_links: [
            { kind: "wallet", id: "wallet-1", label: "Сбербанк" },
            { kind: "cash_flow_item", id: "item-1", label: "Продукты" },
          ],
        })}
      />
    )

    expect(screen.getByRole("link", { name: "Сбербанк" })).toHaveAttribute("href", "/wallets/wallet-1")
    expect(screen.getByRole("link", { name: "Продукты" })).toHaveAttribute(
      "href",
      "/cash-flow-items/item-1/edit"
    )
  })

  it("keeps entity links clickable inside Telegram report tables", () => {
    render(
      <AssistantReply
        response={response({
          reply_parse_mode: "HTML",
          reply_text: "Отчет<pre>Продукты  500 ₽</pre>",
          entity_links: [{ kind: "cash_flow_item", id: "item-1", label: "Продукты" }],
        })}
      />
    )

    expect(screen.getByRole("link", { name: "Продукты" })).toHaveAttribute(
      "href",
      "/cash-flow-items/item-1/edit"
    )
  })

  it("does not link an entity name inside a longer word", () => {
    render(
      <AssistantReply
        response={response({
          reply_text: "Альфабанк",
          entity_links: [{ kind: "wallet", id: "wallet-1", label: "Альфа" }],
        })}
      />
    )

    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })
})
