import { ReactNode } from "react"

import { cn } from "@/lib/utils"

interface PageHeaderProps {
  eyebrow?: string
  title: string
  description?: string
  actions?: ReactNode
  className?: string
  compact?: boolean
}

export function PageHeader({ eyebrow, title, description, actions, className, compact = false }: PageHeaderProps) {
  return (
    <div
      className={cn(
        compact ? "mb-3 flex flex-col gap-2 md:flex-row md:items-end md:justify-between" : "mb-4 flex flex-col gap-2.5 md:flex-row md:items-end md:justify-between",
        className
      )}
    >
      <div className="max-w-3xl">
        {eyebrow ? (
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">{eyebrow}</div>
        ) : null}
        <h1 className={cn(compact ? "text-[1.55rem] sm:text-[1.9rem]" : "text-[1.8rem] sm:text-[2.2rem]", "font-semibold tracking-[-0.04em] text-foreground")}>
          {title}
        </h1>
        {description ? <p className={cn(compact ? "mt-1 text-[12px] leading-4.5" : "mt-1.5 text-[13px] leading-5", "max-w-2xl text-muted-foreground")}>{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
    </div>
  )
}
