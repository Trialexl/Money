"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { CalendarRange } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import AutoPaymentForm from "@/components/shared/auto-payment-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { AutoPaymentService } from "@/services/financial-operations-service"

export default function EditAutoPaymentPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const autoPaymentQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.autoPayments.detail,
    queryFn: AutoPaymentService.getAutoPayment,
  })

  if (autoPaymentQuery.isLoading || autoPaymentQuery.isFetching) {
    return <FullPageLoader label="Загружаем автоплатеж..." />
  }

  if (autoPaymentQuery.isError || !autoPaymentQuery.data) {
    return (
      <EmptyState
        icon={CalendarRange}
        title="Не удалось открыть автоплатеж"
        description="Правило не найдено или backend не вернул его данные."
        action={
          <Button asChild>
            <Link href="/auto-payments">К списку автоплатежей</Link>
          </Button>
        }
      />
    )
  }

  return <AutoPaymentForm autoPayment={autoPaymentQuery.data} isEdit />
}
