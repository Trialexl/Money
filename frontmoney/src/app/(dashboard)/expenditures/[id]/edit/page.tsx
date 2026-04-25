"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { ArrowUpRight } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import ExpenditureForm from "@/components/shared/expenditure-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { ExpenditureService } from "@/services/financial-operations-service"

export default function EditExpenditurePage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const expenditureQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.expenditures.detail,
    queryFn: ExpenditureService.getExpenditure,
  })

  if (expenditureQuery.isLoading) {
    return <FullPageLoader label="Загружаем расход..." />
  }

  if (expenditureQuery.isError || !expenditureQuery.data) {
    return (
      <EmptyState
        icon={ArrowUpRight}
        title="Не удалось открыть расход"
        description="Операция не найдена или backend не вернул ее данные."
        action={
          <Button asChild>
            <Link href="/expenditures">К списку расходов</Link>
          </Button>
        }
      />
    )
  }

  return <ExpenditureForm expenditure={expenditureQuery.data} isEdit />
}
