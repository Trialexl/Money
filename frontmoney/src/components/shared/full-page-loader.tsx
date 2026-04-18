import { Loader2 } from "lucide-react"

import { BrandMark } from "@/components/shared/brand-mark"

interface FullPageLoaderProps {
  label?: string
}

export function FullPageLoader({ label = "Собираем рабочее пространство..." }: FullPageLoaderProps) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-[32px] border border-border/70 bg-card/90 p-8 text-center shadow-soft backdrop-blur-sm">
        <BrandMark className="justify-center" />
        <div className="mt-8 flex items-center justify-center gap-3 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span>{label}</span>
        </div>
      </div>
    </div>
  )
}
