"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { Wallet2 } from "lucide-react"

import { EmptyState } from "@/components/shared/empty-state"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import WalletForm from "@/components/shared/wallet-form"
import { useEntityDetailQuery } from "@/hooks/use-entity-query"
import { queryKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { WalletService } from "@/services/wallet-service"

export default function EditWalletPage() {
  const params = useParams()
  const idParam = Array.isArray((params as any)?.id) ? (params as any).id[0] : (params as any)?.id

  const walletQuery = useEntityDetailQuery({
    id: typeof idParam === "string" ? idParam : undefined,
    queryKeyFactory: queryKeys.wallets.detail,
    queryFn: WalletService.getWallet,
  })

  if (walletQuery.isLoading || walletQuery.isFetching) {
    return <FullPageLoader label="Загружаем кошелек..." />
  }

  if (walletQuery.isError || !walletQuery.data) {
    return (
      <EmptyState
        icon={Wallet2}
        title="Не удалось открыть кошелек"
        description="Кошелек не найден или backend не вернул его данные."
        action={
          <Button asChild>
            <Link href="/wallets">К списку кошельков</Link>
          </Button>
        }
      />
    )
  }

  return <WalletForm wallet={walletQuery.data} isEdit />
}
