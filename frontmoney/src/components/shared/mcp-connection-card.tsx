"use client"

import { useEffect, useMemo, useState } from "react"
import { Cable, Check, Copy, ExternalLink, KeyRound, Monitor, Terminal } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { buildCodexMcpCommand, buildCodexMcpConfig, buildMcpServerUrl } from "@/lib/mcp-config"

type CopyTarget = "url" | "command" | "config"

function CopyButton({ value, target, copied, onCopy }: {
  value: string
  target: CopyTarget
  copied: CopyTarget | null
  onCopy: (value: string, target: CopyTarget) => void
}) {
  const isCopied = copied === target
  return (
    <Button
      type="button"
      size="sm"
      variant="outline"
      onClick={() => onCopy(value, target)}
      aria-label={isCopied ? "Скопировано" : "Скопировать"}
    >
      {isCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
      {isCopied ? "Скопировано" : "Копировать"}
    </Button>
  )
}

function CodeBlock({ value, target, copied, onCopy }: {
  value: string
  target: CopyTarget
  copied: CopyTarget | null
  onCopy: (value: string, target: CopyTarget) => void
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-[18px] border border-border/70 bg-slate-950 p-3 text-slate-50 sm:flex-row sm:items-center">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-pre text-xs leading-5 sm:text-sm">{value}</code>
      <CopyButton value={value} target={target} copied={copied} onCopy={onCopy} />
    </div>
  )
}

export function McpConnectionCard() {
  const [mcpUrl, setMcpUrl] = useState(() => buildMcpServerUrl())
  const [copied, setCopied] = useState<CopyTarget | null>(null)

  useEffect(() => {
    setMcpUrl(buildMcpServerUrl())
  }, [])

  const command = useMemo(() => buildCodexMcpCommand(mcpUrl), [mcpUrl])
  const config = useMemo(() => buildCodexMcpConfig(mcpUrl), [mcpUrl])

  const copy = async (value: string, target: CopyTarget) => {
    await navigator.clipboard.writeText(value)
    setCopied(target)
    window.setTimeout(() => setCopied((current) => current === target ? null : current), 1800)
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Cable className="h-5 w-5" />
          </div>
          <div className="space-y-1">
            <CardTitle>Подключение через MCP</CardTitle>
            <CardDescription>
              Дай Codex или другому MCP-клиенту доступ к кошелькам, операциям, отчетам и инвестициям FrontMoney.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <div className="text-sm font-medium">Адрес MCP-сервера</div>
          <CodeBlock value={mcpUrl} target="url" copied={copied} onCopy={copy} />
          <p className="text-xs leading-5 text-muted-foreground">
            Транспорт: Streamable HTTP. Авторизация: OAuth — API-токен вручную вводить не нужно.
          </p>
        </div>

        <Tabs defaultValue="interface" className="space-y-3">
          <TabsList className="grid h-auto w-full grid-cols-3 rounded-2xl">
            <TabsTrigger value="interface" className="rounded-xl">Интерфейс</TabsTrigger>
            <TabsTrigger value="cli" className="rounded-xl">CLI</TabsTrigger>
            <TabsTrigger value="config" className="rounded-xl">config.toml</TabsTrigger>
          </TabsList>

          <TabsContent value="interface" className="space-y-3 rounded-[18px] border border-border/70 bg-background/70 p-4">
            <div className="flex items-center gap-2 font-medium"><Monitor className="h-4 w-4 text-primary" />Codex Desktop или IDE</div>
            <ol className="ml-5 list-decimal space-y-2 text-sm leading-5 text-muted-foreground">
              <li>Открой Settings → MCP servers → Add server.</li>
              <li>Укажи имя <span className="font-medium text-foreground">frontmoney</span>, тип <span className="font-medium text-foreground">Streamable HTTP</span> и адрес выше.</li>
              <li>Сохрани, перезапусти клиент и нажми Authenticate.</li>
              <li>В открывшемся FrontMoney войди в аккаунт и подтверди запрошенные права.</li>
            </ol>
          </TabsContent>

          <TabsContent value="cli" className="space-y-3 rounded-[18px] border border-border/70 bg-background/70 p-4">
            <div className="flex items-center gap-2 font-medium"><Terminal className="h-4 w-4 text-primary" />Codex CLI</div>
            <CodeBlock value={command} target="command" copied={copied} onCopy={copy} />
            <p className="text-sm leading-5 text-muted-foreground">
              После добавления выполни <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">codex mcp login frontmoney</code> и подтверди вход в браузере.
            </p>
          </TabsContent>

          <TabsContent value="config" className="space-y-3 rounded-[18px] border border-border/70 bg-background/70 p-4">
            <div className="flex items-center gap-2 font-medium"><Terminal className="h-4 w-4 text-primary" />~/.codex/config.toml</div>
            <CodeBlock value={config} target="config" copied={copied} onCopy={copy} />
            <p className="text-sm leading-5 text-muted-foreground">
              Режим <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">writes</code> запрашивает подтверждение перед изменяющими инструментами.
            </p>
          </TabsContent>
        </Tabs>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="flex items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 p-3 text-sm leading-5 text-muted-foreground">
            <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>Права выдаются твоему аккаунту через OAuth и могут включать чтение и изменение финансовых данных.</span>
          </div>
          <a
            href="https://developers.openai.com/codex/mcp/"
            target="_blank"
            rel="noreferrer"
            className="flex items-start gap-3 rounded-[18px] border border-border/70 bg-background/70 p-3 text-sm leading-5 text-muted-foreground hover:border-primary/30 hover:text-foreground"
          >
            <ExternalLink className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span>Официальная документация Codex по подключению MCP-серверов.</span>
          </a>
        </div>
      </CardContent>
    </Card>
  )
}
