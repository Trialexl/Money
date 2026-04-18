"use client"

import Link from "next/link"
import { useDeferredValue, useMemo, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { GitBranch, ListTree, PencilLine, PieChart, Plus, Search, Trash2 } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { PageHeader } from "@/components/shared/page-header"
import { StatCard } from "@/components/shared/stat-card"
import { TreeItem } from "@/components/shared/tree-item"
import { useCashFlowTreeQuery } from "@/hooks/use-reference-data"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { CashFlowItemHierarchy, CashFlowItemService } from "@/services/cash-flow-item-service"

function filterHierarchy(nodes: CashFlowItemHierarchy[], search: string, budgetOnly: boolean): CashFlowItemHierarchy[] {
  return nodes.flatMap((node) => {
    const filteredChildren = Array.isArray(node.children) ? filterHierarchy(node.children, search, budgetOnly) : []
    const matchesSearch = !search
      ? true
      : `${node.name ?? ""} ${node.code ?? ""}`.toLowerCase().includes(search.toLowerCase())
    const matchesBudget = budgetOnly ? node.include_in_budget === true : true

    if ((matchesSearch && matchesBudget) || filteredChildren.length > 0) {
      return [{ ...node, children: filteredChildren }]
    }

    return []
  })
}

export default function CashFlowItemsPage() {
  const queryClient = useQueryClient()
  const [searchTerm, setSearchTerm] = useState("")
  const [budgetOnly, setBudgetOnly] = useState(false)
  const deferredSearch = useDeferredValue(searchTerm)

  const itemsQuery = useCashFlowTreeQuery()

  const deleteMutation = useMutation({
    mutationFn: (id: string) => CashFlowItemService.deleteCashFlowItem(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cash-flow-items"] }),
  })

  const items = itemsQuery.data?.items ?? []
  const hierarchy = itemsQuery.data?.hierarchy ?? []
  const parentNameMap = Object.fromEntries(items.map((item) => [item.id, item.name ?? "—"]))
  const filteredHierarchy = useMemo(
    () => filterHierarchy(hierarchy, deferredSearch.trim(), budgetOnly),
    [hierarchy, deferredSearch, budgetOnly]
  )
  const filteredItems = items
    .filter((item) => {
      if (budgetOnly && item.include_in_budget !== true) {
        return false
      }
      if (!deferredSearch.trim()) {
        return true
      }
      return `${item.name ?? ""} ${item.code ?? ""}`.toLowerCase().includes(deferredSearch.toLowerCase())
    })
    .sort((left, right) => (left.name ?? "").localeCompare(right.name ?? "", "ru"))

  const rootItemsCount = items.filter((item) => !item.parent).length
  const budgetDefaultCount = items.filter((item) => item.include_in_budget === true).length

  if (itemsQuery.isLoading) {
    return <FullPageLoader label="Загружаем структуру категорий..." />
  }

  if (itemsQuery.isError || !itemsQuery.data) {
    return (
      <EmptyState
        icon={PieChart}
        title="Не удалось загрузить статьи движения"
        description="Справочник категорий и их иерархия сейчас недоступны. Проверь backend API и повтори загрузку."
        action={<Button onClick={() => itemsQuery.refetch()}>Повторить</Button>}
      />
    )
  }

  const handleDelete = async (id: string, name: string | null) => {
    if (!window.confirm(`Удалить статью "${name || "без названия"}"?`)) {
      return
    }

    await deleteMutation.mutateAsync(id)
  }

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Reference data"
        title="Статьи движения средств"
        description="Категории теперь снова выглядят как живая иерархия: видно, где корень, что уходит в бюджет и как быстро добавить дочернюю ветку."
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Всего статей" value={String(items.length)} hint="Все элементы справочника" icon={PieChart} variant="compact" />
        <StatCard label="Корневые узлы" value={String(rootItemsCount)} hint="Верхний уровень иерархии" icon={GitBranch} variant="compact" />
        <StatCard label="По умолчанию в бюджете" value={String(budgetDefaultCount)} hint="Категории с бюджетным флагом" icon={ListTree} variant="compact" />
      </div>

      <Card>
        <CardContent className="grid gap-5 p-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div className="space-y-2">
            <Label htmlFor="cashflow-search">Поиск по категориям</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="cashflow-search"
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="Название или код категории"
                className="pl-11"
              />
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-[24px] border border-border/70 bg-background/70 px-4 py-3">
            <Switch id="budget-only" checked={budgetOnly} onCheckedChange={setBudgetOnly} />
            <Label htmlFor="budget-only" className="cursor-pointer">
              Только статьи для бюджета
            </Label>
          </div>
        </CardContent>
      </Card>

      {items.length === 0 ? (
        <EmptyState
          icon={PieChart}
          title="Справочник категорий пока пуст"
          description="Создай первую статью, чтобы затем разложить доходы и расходы по внятной структуре."
          action={
            <Button asChild>
              <Link href="/cash-flow-items/new">Создать статью</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <Card>
            <CardHeader>
              <CardTitle>Иерархия</CardTitle>
              <CardDescription>Главный вид для работы с деревом категорий и быстрым добавлением дочерних веток.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {filteredHierarchy.length > 0 ? (
                filteredHierarchy.map((item) => (
                  <TreeItem key={item.id} item={item} level={0} onDelete={handleDelete} />
                ))
              ) : (
                <div className="rounded-[22px] border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
                  По текущему поиску и фильтру иерархия ничего не показывает.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Каталог</CardTitle>
              <CardDescription>Плоский индекс для быстрого просмотра родителя, кода и бюджетного режима.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {filteredItems.length > 0 ? (
                filteredItems.map((item) => (
                  <div key={item.id} className="rounded-[22px] border border-border/60 bg-background/70 px-4 py-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="text-sm font-semibold tracking-[-0.02em]">{item.name || "Без названия"}</div>
                          {item.code ? <Badge variant="outline">{item.code}</Badge> : null}
                          {item.include_in_budget ? <Badge variant="success">Budget</Badge> : null}
                        </div>
                        <div className="mt-2 text-xs leading-5 text-muted-foreground">
                          {item.parent ? `Родитель: ${parentNameMap[item.parent] || "—"}` : "Корневая статья"}
                        </div>
                      </div>
                      <div className="flex gap-1">
                        <Button asChild variant="ghost" size="icon" aria-label="Редактировать" title="Редактировать">
                          <Link href={`/cash-flow-items/${item.id}/edit`}>
                            <PencilLine className="h-4 w-4" />
                          </Link>
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDelete(item.id, item.name)} aria-label="Удалить" title="Удалить">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-[22px] border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
                  Ничего не найдено.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
