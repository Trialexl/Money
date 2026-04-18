import { LucideIcon } from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface StatCardProps {
  label: string
  value: string
  hint?: string
  icon: LucideIcon
  tone?: "neutral" | "positive" | "danger"
  variant?: "default" | "compact"
  className?: string
}

const toneClasses = {
  neutral: "text-foreground",
  positive: "text-emerald-600 dark:text-emerald-300",
  danger: "text-rose-600 dark:text-rose-300",
}

export function StatCard({ label, value, hint, icon: Icon, tone = "neutral", variant = "default", className }: StatCardProps) {
  return (
    <Card className={cn("self-start", variant === "compact" && "rounded-[18px] border-border/60 bg-card/80 shadow-none", className)}>
      <CardContent
        className={cn(
          variant === "compact"
            ? "px-3.5 pb-3 pt-4 md:flex md:h-[120px] md:flex-col md:justify-center md:px-5 md:pb-4 md:pt-5"
            : "px-5 pb-4 pt-5"
        )}
      >
        <div className="min-w-0 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[9px] font-semibold uppercase leading-none tracking-[0.14em] text-muted-foreground md:text-[10px] md:tracking-[0.16em]">
              {label}
            </p>
            <Icon className="h-3 w-3 shrink-0 text-muted-foreground/60 md:h-3.5 md:w-3.5" />
          </div>
          <p
            className={cn(
              variant === "compact" ? "text-[1.2rem] sm:text-[2rem]" : "text-xl sm:text-2xl",
              "font-semibold leading-none tracking-[-0.04em]",
              toneClasses[tone]
            )}
          >
            {value}
          </p>
          {hint ? (
            <p className={cn(variant === "compact" ? "text-[9px] leading-4 md:text-[11px]" : "text-xs leading-4", "text-muted-foreground")}>
              {hint}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}
