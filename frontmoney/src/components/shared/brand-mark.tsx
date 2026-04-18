import { Landmark } from "lucide-react"

import { cn } from "@/lib/utils"

interface BrandMarkProps {
  compact?: boolean
  className?: string
}

export function BrandMark({ compact = false, className }: BrandMarkProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-cyan-300 text-primary-foreground shadow-[0_20px_35px_-18px_hsl(var(--primary)/0.9)]">
        <Landmark className="h-5 w-5" />
      </div>
      {!compact ? (
        <div className="space-y-0.5">
          <div className="text-sm font-semibold uppercase tracking-[0.24em] text-primary">FrontMoney</div>
          <div className="text-xs text-muted-foreground">Личный центр управления деньгами</div>
        </div>
      ) : null}
    </div>
  )
}
