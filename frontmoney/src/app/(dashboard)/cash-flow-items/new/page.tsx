"use client"

import { Suspense } from "react"
import { useSearchParams } from "next/navigation"

import CashFlowItemForm from "@/components/shared/cash-flow-item-form"
import { FullPageLoader } from "@/components/shared/full-page-loader"

function Inner() {
  const searchParams = useSearchParams()
  const parentId = searchParams.get("parent") || undefined

  return <CashFlowItemForm parentId={parentId} />
}

export default function NewCashFlowItemPage() {
  return (
    <Suspense fallback={<FullPageLoader label="Готовим форму статьи..." />}>
      <Inner />
    </Suspense>
  )
}
