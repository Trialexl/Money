"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { ArrowUpRight } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import ExpenditureForm from "@/components/shared/expenditure-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { ExpenditureService } from "@/services/financial-operations-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.expenditures.duplicate,
    queryFn: ExpenditureService.getExpenditure,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат расхода..." />
  }

  if (duplicateId && (duplicateQuery.isError || !duplicateQuery.data)) {
    return (
      <EmptyState
        icon={ArrowUpRight}
        title="Не удалось загрузить расход для дублирования"
        description="Исходная операция не загрузилась. Можно вернуться к каталогу или создать новый расход вручную."
        action={
          <Button asChild>
            <Link href="/expenditures">К расходам</Link>
          </Button>
        }
      />
    )
  }

  return <ExpenditureForm expenditure={duplicateQuery.data || undefined} />
}

export default function NewExpenditurePage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму расхода..." />}>
      <Inner />
    </Suspense>
  )
}
