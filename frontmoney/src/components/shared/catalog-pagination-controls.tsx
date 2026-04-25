"use client"

import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

interface CatalogPaginationControlsProps {
  page: number
  pageCount: number
  pageSize: number
  totalCount: number
  currentCount: number
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}

const PAGE_SIZE_OPTIONS = [20, 50, 100] as const

export function CatalogPaginationControls({
  page,
  pageCount,
  pageSize,
  totalCount,
  currentCount,
  onPageChange,
  onPageSizeChange,
}: CatalogPaginationControlsProps) {
  const canGoBack = page > 1
  const canGoForward = page < pageCount

  return (
    <div className="flex flex-col gap-3 border-t border-border/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
      <div className="space-y-1 text-xs text-muted-foreground">
        <div className="uppercase tracking-[0.16em]">Пагинация</div>
        <div>
          Показано {currentCount} из {totalCount} · страница {page} из {pageCount}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="uppercase tracking-[0.16em]">На странице</span>
          <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
            <SelectTrigger className="h-9 w-[92px] rounded-xl bg-background/70 px-3">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button variant="outline" size="sm" onClick={() => onPageChange(page - 1)} disabled={!canGoBack}>
          Назад
        </Button>
        <Button variant="outline" size="sm" onClick={() => onPageChange(page + 1)} disabled={!canGoForward}>
          Вперед
        </Button>
      </div>
    </div>
  )
}
