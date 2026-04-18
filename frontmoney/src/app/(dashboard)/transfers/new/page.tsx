"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { ArrowRightLeft } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import TransferForm from "@/components/shared/transfer-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { TransferService } from "@/services/financial-operations-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.transfers.duplicate,
    queryFn: TransferService.getTransfer,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат перевода..." />
  }

  if (duplicateId && (duplicateQuery.isError || !duplicateQuery.data)) {
    return (
      <EmptyState
        icon={ArrowRightLeft}
        title="Не удалось загрузить перевод для дублирования"
        description="Исходный перевод не загрузился. Можно вернуться в каталог или создать новый перевод вручную."
        action={
          <Button asChild>
            <Link href="/transfers">К переводам</Link>
          </Button>
        }
      />
    )
  }

  return <TransferForm transfer={duplicateQuery.data || undefined} />
}

export default function NewTransferPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму перевода..." />}>
      <Inner />
    </Suspense>
  )
}
