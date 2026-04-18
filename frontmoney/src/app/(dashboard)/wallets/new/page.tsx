"use client"

import Link from "next/link"
import { Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { Wallet2 } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import WalletForm from "@/components/shared/wallet-form"
import { useEntityDuplicateQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { WalletService } from "@/services/wallet-service"

function Inner() {
  const searchParams = useSearchParams()
  const duplicateId = searchParams.get("duplicate")

  const duplicateQuery = useEntityDuplicateQuery({
    id: duplicateId,
    queryKeyFactory: queryKeys.wallets.duplicate,
    queryFn: WalletService.getWallet,
  })

  if (duplicateId && (duplicateQuery.isLoading || duplicateQuery.isFetching)) {
    return <FullPageLoader label="Подготавливаем дубликат кошелька..." />
  }

  if (duplicateId && (duplicateQuery.isError || !duplicateQuery.data)) {
    return (
      <EmptyState
        icon={Wallet2}
        title="Не удалось загрузить кошелек для дублирования"
        description="Исходный кошелек не загрузился. Можно вернуться к списку или создать новый вручную."
        action={
          <Button asChild>
            <Link href="/wallets">К кошелькам</Link>
          </Button>
        }
      />
    )
  }

  return <WalletForm wallet={duplicateQuery.data || undefined} />
}

export default function NewWalletPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму кошелька..." />}>
      <Inner />
    </Suspense>
  )
}
