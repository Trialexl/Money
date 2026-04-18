"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { CalendarRange } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import AutoPaymentForm from "@/components/shared/auto-payment-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { AutoPaymentService } from "@/services/financial-operations-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.autoPayments.duplicate,
    queryFn: AutoPaymentService.getAutoPayment,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат автоплатежа..." />
  }

  if (duplicateId && (duplicateQuery.isError || !duplicateQuery.data)) {
    return (
      <EmptyState
        icon={CalendarRange}
        title="Не удалось загрузить автоплатеж для дублирования"
        description="Исходное правило не загрузилось. Можно вернуться в каталог или создать новое правило вручную."
        action={
          <Button asChild>
            <Link href="/auto-payments">К автоплатежам</Link>
          </Button>
        }
      />
    )
  }

  return <AutoPaymentForm autoPayment={duplicateQuery.data || undefined} />
}

export default function NewAutoPaymentPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму автоплатежа..." />}>
      <Inner />
    </Suspense>
  )
}
