"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Save } from "lucide-react"

import { useCashFlowParentOptionsQuery } from "@/hooks/use-reference-data"
import { PageHeader } from "@/components/shared/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { CashFlowItem, CashFlowItemService } from "@/services/cash-flow-item-service"

interface CashFlowItemFormProps {
  item?: CashFlowItem
  parentId?: string
  isEdit?: boolean
}

export default function CashFlowItemForm({ item, parentId, isEdit = false }: CashFlowItemFormProps) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [name, setName] = useState(item?.name || "")
  const [includeInBudget, setIncludeInBudget] = useState<boolean>(item?.include_in_budget ?? false)
  const [parent, setParent] = useState(item?.parent || parentId || "")

  useEffect(() => {
    setName(item?.name || "")
    setIncludeInBudget(item?.include_in_budget ?? false)
    setParent(item?.parent || parentId || "")
  }, [item, parentId])

  const parentOptionsQuery = useCashFlowParentOptionsQuery(item?.id)
  const sortedParentOptions = parentOptionsQuery.data || []

  const itemMutation = useMutation({
    mutationFn: async () => {
      const payload: Partial<CashFlowItem> = {
        name: name.trim(),
        include_in_budget: includeInBudget,
        parent: parent || undefined,
      }

      if (isEdit && item) {
        return CashFlowItemService.updateCashFlowItem(item.id, payload)
      }

      return CashFlowItemService.createCashFlowItem(payload)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["cash-flow-items"] })
      router.push("/cash-flow-items")
    },
  })

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await itemMutation.mutateAsync()
  }

  const selectedParentName = sortedParentOptions.find((entry) => entry.id === parent)?.name
  const errorMessage = itemMutation.error
    ? (itemMutation.error as any)?.response?.data?.detail || "Не удалось сохранить статью. Проверь поля и попробуй снова."
    : null

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Cash flow categories"
        title={isEdit ? "Редактирование статьи" : "Новая статья"}
        description={
          isEdit
            ? "Отредактируй место статьи в дереве и бюджетное поведение."
            : "Добавь новую статью движения средств и сразу встрои ее в иерархию."
        }
        actions={
          <Button asChild variant="outline">
            <Link href="/cash-flow-items">К справочнику</Link>
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Параметры статьи</CardTitle>
            <CardDescription>Название и позиция в дереве важнее всего. Бюджетный флаг задает значение по умолчанию для связанных сценариев.</CardDescription>
          </CardHeader>
          <CardContent>
            {errorMessage ? (
              <div className="mb-6 rounded-[24px] border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm leading-6 text-destructive">
                {errorMessage}
              </div>
            ) : null}

            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="cashflow-name">Название статьи</Label>
                <Input
                  id="cashflow-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Например, Продукты"
                  maxLength={25}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="cashflow-parent">Родительская статья</Label>
                {parentOptionsQuery.isLoading ? (
                  <div className="rounded-[20px] border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
                    Загружаем доступные узлы...
                  </div>
                ) : (
                  <Select value={parent || "root"} onValueChange={(value) => setParent(value === "root" ? "" : value)}>
                    <SelectTrigger id="cashflow-parent">
                      <SelectValue placeholder="Выбери родительскую статью" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="root">Нет, это корневая статья</SelectItem>
                      {sortedParentOptions.map((entry) => (
                        <SelectItem key={entry.id} value={entry.id}>
                          {entry.name || "Без названия"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>

              <div className="flex items-start gap-3 rounded-[24px] border border-border/70 bg-background/70 px-4 py-4">
                <Checkbox
                  id="cashflow-budget"
                  checked={includeInBudget}
                  onCheckedChange={(value) => setIncludeInBudget(Boolean(value))}
                  className="mt-1"
                />
                <div className="space-y-1">
                  <Label htmlFor="cashflow-budget" className="cursor-pointer">
                    Включать в бюджет по умолчанию
                  </Label>
                  <p className="text-sm leading-6 text-muted-foreground">
                    Удобно для расходных категорий, которые обычно попадают в план-факт анализ.
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={itemMutation.isPending || !name.trim()}>
                  <Save className="h-4 w-4" />
                  {itemMutation.isPending ? "Сохраняем..." : isEdit ? "Сохранить изменения" : "Создать статью"}
                </Button>
                <Button asChild variant="outline">
                  <Link href="/cash-flow-items">Отмена</Link>
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Предпросмотр</CardTitle>
            <CardDescription>Так статья будет выглядеть в каталоге и дереве.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-[24px] border border-border/70 bg-background/70 p-5">
              <div className="text-lg font-semibold tracking-[-0.03em]">{name.trim() || "Новая статья"}</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="outline">{item?.code ? `Код: ${item.code}` : "Код назначим автоматически"}</Badge>
                {includeInBudget ? <Badge variant="success">Budget</Badge> : <Badge variant="secondary">No budget default</Badge>}
              </div>
              <div className="mt-4 text-sm leading-6 text-muted-foreground">
                {parent ? `Дочерняя статья: ${selectedParentName || "выбранный родитель"}` : "Корневая статья верхнего уровня"}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
