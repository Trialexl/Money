"use client"

import Link from "next/link"
import { useState } from "react"
import { ChevronDown, ChevronRight, PencilLine, Plus, Trash2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { CashFlowItemHierarchy } from "@/services/cash-flow-item-service"
import { cn } from "@/lib/utils"

interface TreeItemProps {
  item: CashFlowItemHierarchy
  level: number
  onDelete: (id: string, name: string | null) => Promise<void>
}

export function TreeItem({ item, level, onDelete }: TreeItemProps) {
  const [isExpanded, setIsExpanded] = useState(true)
  const hasChildren = Boolean(item.children?.length)

  return (
    <div className={cn(level > 0 ? "ml-6 border-l border-border/60 pl-4" : "")}>
      <div className="rounded-[24px] border border-border/60 bg-background/70 p-4">
        <div className="flex items-start gap-3">
          <button
            type="button"
            onClick={() => hasChildren && setIsExpanded((value) => !value)}
            className={cn(
              "mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border/70 bg-card/90 text-muted-foreground transition",
              hasChildren ? "hover:border-primary/30 hover:text-foreground" : "cursor-default opacity-60"
            )}
            aria-label={hasChildren ? "Показать или скрыть вложенные статьи" : "Конечная статья"}
          >
            {hasChildren ? (isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />) : <div className="h-2 w-2 rounded-full bg-primary/50" />}
          </button>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-sm font-semibold tracking-[-0.02em]">{item.name || "Без названия"}</div>
              {item.code ? <Badge variant="outline">{item.code}</Badge> : null}
              {item.include_in_budget ? <Badge variant="success">В бюджете</Badge> : null}
            </div>
            <div className="mt-2 text-xs leading-5 text-muted-foreground">
              {level === 0 ? "Корневая статья" : `Уровень ${level + 1}`}
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap gap-1">
            <Button asChild variant="ghost" size="icon" aria-label="Добавить дочернюю статью" title="Добавить дочернюю статью">
              <Link href={`/cash-flow-items/new?parent=${item.id}`}>
                <Plus className="h-4 w-4" />
              </Link>
            </Button>
            <Button asChild variant="ghost" size="icon" aria-label="Редактировать" title="Редактировать">
              <Link href={`/cash-flow-items/${item.id}/edit`}>
                <PencilLine className="h-4 w-4" />
              </Link>
            </Button>
            <Button variant="ghost" size="icon" onClick={() => onDelete(item.id, item.name)} aria-label="Удалить" title="Удалить">
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </div>
      </div>

      {hasChildren && isExpanded ? (
        <div className="mt-3 space-y-3">
          {item.children!.map((child) => (
            <TreeItem key={child.id} item={child} level={level + 1} onDelete={onDelete} />
          ))}
        </div>
      ) : null}
    </div>
  )
}
