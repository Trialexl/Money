"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { ArrowDownRight } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import ReceiptForm from "@/components/shared/receipt-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { ReceiptService } from "@/services/financial-operations-service"

export default function EditReceiptPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const receiptQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.receipts.detail,
    queryFn: ReceiptService.getReceipt,
  })

  if (receiptQuery.isLoading || receiptQuery.isFetching) {
    return <FullPageLoader label="Загружаем приход..." />
  }

  if (receiptQuery.isError || !receiptQuery.data) {
    return (
      <EmptyState
        icon={ArrowDownRight}
        title="Не удалось открыть приход"
        description="Операция не найдена или backend не вернул ее данные."
        action={
          <Button asChild>
            <Link href="/receipts">К списку приходов</Link>
          </Button>
        }
      />
    )
  }

  return <ReceiptForm receipt={receiptQuery.data} isEdit />
}
