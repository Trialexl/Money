import Link from "next/link"

import type { AiAssistantEntityLink, AiAssistantResponse } from "@/services/ai-service"

const WORD_CHARACTER = /[0-9A-Za-zА-Яа-яЁё_]/

function decodeHtmlEntities(value: string) {
  const named: Record<string, string> = {
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    nbsp: " ",
  }
  return value.replace(/&(?:#(\d+)|#x([\da-f]+)|(\w+));/gi, (match, decimal, hex, name) => {
    if (decimal) return String.fromCodePoint(Number(decimal))
    if (hex) return String.fromCodePoint(Number.parseInt(hex, 16))
    return named[String(name).toLowerCase()] ?? match
  })
}

function plainTelegramHtml(value: string) {
  return decodeHtmlEntities(
    value
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/?(?:b|strong|i|em|u|s|code)(?:\s[^>]*)?>/gi, "")
      .replace(/<a\s[^>]*href=["']([^"']+)["'][^>]*>(.*?)<\/a>/gi, "$2 ($1)")
  )
}

function entityHref(entity: AiAssistantEntityLink) {
  if (entity.kind === "wallet") {
    return `/wallets/${entity.id}`
  }
  return `/cash-flow-items/${entity.id}/edit`
}

function isWordCharacter(value: string | undefined) {
  return Boolean(value && WORD_CHARACTER.test(value))
}

function hasEntityBoundaries(value: string, index: number, label: string) {
  const before = index > 0 ? value[index - 1] : undefined
  const afterIndex = index + label.length
  const after = afterIndex < value.length ? value[afterIndex] : undefined

  if (isWordCharacter(label[0]) && isWordCharacter(before)) {
    return false
  }
  if (isWordCharacter(label.at(-1)) && isWordCharacter(after)) {
    return false
  }
  return true
}

function findEntityIndex(value: string, entity: AiAssistantEntityLink, start: number) {
  let searchFrom = start
  while (searchFrom < value.length) {
    const index = value.indexOf(entity.label, searchFrom)
    if (index === -1) return -1
    if (hasEntityBoundaries(value, index, entity.label)) return index
    searchFrom = index + entity.label.length
  }
  return -1
}

function EntityLinkedText({
  value,
  entities,
}: {
  value: string
  entities: AiAssistantEntityLink[]
}) {
  const candidates = entities
    .filter((entity) => entity.id && entity.label)
    .sort((left, right) => right.label.length - left.label.length)
  const nodes: React.ReactNode[] = []
  let cursor = 0
  let key = 0

  while (cursor < value.length) {
    let nextEntity: AiAssistantEntityLink | null = null
    let nextIndex = -1

    for (const entity of candidates) {
      const index = findEntityIndex(value, entity, cursor)
      if (
        index !== -1 &&
        (nextIndex === -1 || index < nextIndex || (index === nextIndex && entity.label.length > (nextEntity?.label.length ?? 0)))
      ) {
        nextEntity = entity
        nextIndex = index
      }
    }

    if (!nextEntity || nextIndex === -1) {
      nodes.push(value.slice(cursor))
      break
    }

    if (nextIndex > cursor) {
      nodes.push(value.slice(cursor, nextIndex))
    }
    nodes.push(
      <Link
        key={`${nextEntity.kind}-${nextEntity.id}-${key}`}
        href={entityHref(nextEntity)}
        className="font-medium text-primary underline underline-offset-2 hover:text-primary/80"
      >
        {nextEntity.label}
      </Link>
    )
    key += 1
    cursor = nextIndex + nextEntity.label.length
  }

  return <>{nodes}</>
}

export function AssistantReply({ response }: { response: AiAssistantResponse }) {
  const entityLinks = response.entity_links ?? []

  if (response.reply_parse_mode !== "HTML") {
    return (
      <div className="whitespace-pre-wrap break-words">
        <EntityLinkedText value={response.reply_text} entities={entityLinks} />
      </div>
    )
  }

  const parts = response.reply_text.split(/(<pre>[\s\S]*?<\/pre>)/gi)
  return (
    <div className="space-y-3">
      {parts.map((part, index) => {
        const preMatch = part.match(/^<pre>([\s\S]*?)<\/pre>$/i)
        if (preMatch) {
          return (
            <pre key={index} className="max-w-full overflow-x-auto rounded-md bg-muted/70 p-3 text-xs leading-5">
              <EntityLinkedText value={decodeHtmlEntities(preMatch[1])} entities={entityLinks} />
            </pre>
          )
        }
        const text = plainTelegramHtml(part).trim()
        return text ? (
          <div key={index} className="whitespace-pre-wrap break-words">
            <EntityLinkedText value={text} entities={entityLinks} />
          </div>
        ) : null
      })}
    </div>
  )
}
