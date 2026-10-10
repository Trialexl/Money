import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { McpConnectionCard } from "./mcp-connection-card"

describe("McpConnectionCard", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it("shows the connection endpoint and setup paths", () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "/api/v1")
    render(<McpConnectionCard />)

    expect(screen.getByText("Подключение через MCP")).toBeInTheDocument()
    expect(screen.getByText(`${window.location.origin}/mcp`)).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Интерфейс" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "CLI" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "config.toml" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Официальная документация Codex/ })).toHaveAttribute(
      "href",
      "https://developers.openai.com/codex/mcp/"
    )
  })
})
