import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { McpConnectionCard } from "./mcp-connection-card"

describe("McpConnectionCard", () => {
  it("shows the connection endpoint and setup paths", () => {
    render(<McpConnectionCard />)

    expect(screen.getByText("Подключение через MCP")).toBeInTheDocument()
    expect(screen.getByText("http://localhost:8000/mcp")).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Интерфейс" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "CLI" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "config.toml" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Официальная документация Codex/ })).toHaveAttribute(
      "href",
      "https://developers.openai.com/codex/mcp/"
    )
  })
})
