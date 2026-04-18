"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { ArrowRightLeft } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import TransferForm from "@/components/shared/transfer-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { TransferService } from "@/services/financial-operations-service"

export default function EditTransferPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const transferQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.transfers.detail,
    queryFn: TransferService.getTransfer,
  })

  if (transferQuery.isLoading || transferQuery.isFetching) {
    return <FullPageLoader label="Загружаем перевод..." />
  }

  if (transferQuery.isError || !transferQuery.data) {
    return (
      <EmptyState
        icon={ArrowRightLeft}
        title="Не удалось открыть перевод"
        description="Операция не найдена или backend не вернул ее данные."
        action={
          <Button asChild>
            <Link href="/transfers">К списку переводов</Link>
          </Button>
        }
      />
    )
  }

  return <TransferForm transfer={transferQuery.data} isEdit />
}
