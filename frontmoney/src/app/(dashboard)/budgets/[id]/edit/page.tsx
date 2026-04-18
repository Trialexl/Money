"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { PiggyBank } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import BudgetForm from "@/components/shared/budget-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { BudgetService } from "@/services/financial-operations-service"

export default function EditBudgetPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const budgetQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.budgets.detail,
    queryFn: BudgetService.getBudget,
  })

  if (budgetQuery.isLoading || budgetQuery.isFetching) {
    return <FullPageLoader label="Загружаем бюджет..." />
  }

  if (budgetQuery.isError || !budgetQuery.data) {
    return (
      <EmptyState
        icon={PiggyBank}
        title="Не удалось открыть бюджет"
        description="Бюджет не найден или backend не вернул его данные."
        action={
          <Button asChild>
            <Link href="/budgets">К списку бюджетов</Link>
          </Button>
        }
      />
    )
  }

  return <BudgetForm budget={budgetQuery.data} isEdit />
}
