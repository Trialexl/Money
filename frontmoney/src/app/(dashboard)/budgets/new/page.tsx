"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { PiggyBank } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import BudgetForm from "@/components/shared/budget-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { BudgetService } from "@/services/financial-operations-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.budgets.duplicate,
    queryFn: BudgetService.getBudget,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат бюджета..." />
  }

  if (duplicateId && (duplicateQuery.isError || !duplicateQuery.data)) {
    return (
      <EmptyState
        icon={PiggyBank}
        title="Не удалось загрузить бюджет для дублирования"
        description="Исходный бюджет не загрузился. Можно вернуться в каталог или создать новый бюджет вручную."
        action={
          <Button asChild>
            <Link href="/budgets">К бюджетам</Link>
          </Button>
        }
      />
    )
  }

  return <BudgetForm budget={duplicateQuery.data || undefined} />
}

export default function NewBudgetPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму бюджета..." />}>
      <Inner />
    </Suspense>
  )
}
