const DEFAULT_API_URL = "http://localhost:8000/api/v1"

function trimApiPath(pathname: string): string {
  const withoutApi = pathname.replace(/\/api\/v1\/?$/, "")
  return withoutApi === "/" ? "" : withoutApi.replace(/\/$/, "")
}

export function buildMcpServerUrl(
  apiUrl = process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL,
  browserOrigin = typeof window === "undefined" ? undefined : window.location.origin
): string {
  try {
    const base = browserOrigin || DEFAULT_API_URL
    const resolved = new URL(apiUrl, base)
    return `${resolved.origin}${trimApiPath(resolved.pathname)}/mcp`
  } catch {
    return browserOrigin ? `${browserOrigin}/mcp` : "http://localhost:8000/mcp"
  }
}

export function buildCodexMcpCommand(mcpUrl: string): string {
  return `codex mcp add frontmoney --url ${mcpUrl}`
}

export function buildCodexMcpConfig(mcpUrl: string): string {
  return [
    "[mcp_servers.frontmoney]",
    `url = "${mcpUrl}"`,
    'default_tools_approval_mode = "writes"',
  ].join("\n")
}
