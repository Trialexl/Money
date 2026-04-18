"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { ArrowDownRight } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import ReceiptForm from "@/components/shared/receipt-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { ReceiptService } from "@/services/financial-operations-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.receipts.duplicate,
    queryFn: ReceiptService.getReceipt,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат прихода..." />
  }

  if (duplicateId && (duplicateQuery.isError || !duplicateQuery.data)) {
    return (
      <EmptyState
        icon={ArrowDownRight}
        title="Не удалось загрузить приход для дублирования"
        description="Исходная операция не загрузилась. Можно вернуться к каталогу или создать новый приход вручную."
        action={
          <Button asChild>
            <Link href="/receipts">К приходам</Link>
          </Button>
        }
      />
    )
  }

  return <ReceiptForm receipt={duplicateQuery.data || undefined} />
}

export default function NewReceiptPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму прихода..." />}>
      <Inner />
    </Suspense>
  )
}
