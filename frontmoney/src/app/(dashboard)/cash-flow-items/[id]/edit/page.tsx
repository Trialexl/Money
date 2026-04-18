"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { PieChart } from "lucide-react"

import CashFlowItemForm from "@/components/shared/cash-flow-item-form"
import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { CashFlowItemService } from "@/services/cash-flow-item-service"

export default function EditCashFlowItemPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const itemQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.cashFlowItems.detail,
    queryFn: CashFlowItemService.getCashFlowItem,
  })

  if (itemQuery.isLoading || itemQuery.isFetching) {
    return <FullPageLoader label="Загружаем статью..." />
  }

  if (itemQuery.isError || !itemQuery.data) {
    return (
      <EmptyState
        icon={PieChart}
        title="Не удалось открыть статью"
        description="Категория не найдена или backend не вернул ее данные."
        action={
          <Button asChild>
            <Link href="/cash-flow-items">К справочнику</Link>
          </Button>
        }
      />
    )
  }

  return <CashFlowItemForm item={itemQuery.data} isEdit />
}
