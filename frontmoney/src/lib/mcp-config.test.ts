import { describe, expect, it } from "vitest"

import { buildCodexMcpCommand, buildCodexMcpConfig, buildMcpServerUrl } from "./mcp-config"

describe("MCP connection configuration", () => {
  it("builds a same-origin MCP URL from the production API path", () => {
    expect(buildMcpServerUrl("/api/v1", "https://money.example.test")).toBe(
      "https://money.example.test/mcp"
    )
  })

  it("preserves a separate API host and path prefix", () => {
    expect(buildMcpServerUrl("https://api.example.test/frontmoney/api/v1/", "https://app.example.test")).toBe(
      "https://api.example.test/frontmoney/mcp"
    )
  })

  it("creates safe Codex examples for a remote OAuth server", () => {
    const url = "https://money.example.test/mcp"
    expect(buildCodexMcpCommand(url)).toBe(`codex mcp add frontmoney --url ${url}`)
    expect(buildCodexMcpConfig(url)).toContain('default_tools_approval_mode = "writes"')
  })
})
