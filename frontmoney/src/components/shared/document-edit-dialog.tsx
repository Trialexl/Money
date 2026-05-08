"use client"

import * as Dialog from "@radix-ui/react-dialog"
import { useQuery } from "@tanstack/react-query"
import { X } from "lucide-react"

import AutoPaymentForm from "@/components/shared/auto-payment-form"
import BudgetForm from "@/components/shared/budget-form"
import FinancialOperationForm from "@/components/shared/financial-operation-form"
import TransferForm from "@/components/shared/transfer-form"
import { FullPageLoader } from "@/components/shared/full-page-loader"
import { Button } from "@/components/ui/button"
import {
  AutoPaymentService,
  BudgetService,
  ExpenditureService,
  ReceiptService,
  TransferService,
} from "@/services/financial-operations-service"

export type EditableDocumentKind = "receipt" | "expenditure" | "transfer" | "budget" | "auto-payment"

interface DocumentEditDialogProps {
  document?: {
    kind: EditableDocumentKind
    id: string
  } | null
  onOpenChange: (open: boolean) => void
  onSaved?: (document: { kind: EditableDocumentKind; id: string }) => void
}

function getTitle(kind: EditableDocumentKind) {
  return (
    {
      receipt: "Редактирование прихода",
      expenditure: "Редактирование расхода",
      transfer: "Редактирование перевода",
      budget: "Редактирование бюджета",
      "auto-payment": "Редактирование автоплатежа",
    }[kind] ?? "Редактирование документа"
  )
}

async function loadDocument(kind: EditableDocumentKind, id: string) {
  if (kind === "receipt") {
    return ReceiptService.getReceipt(id)
  }
  if (kind === "expenditure") {
    return ExpenditureService.getExpenditure(id)
  }
  if (kind === "transfer") {
    return TransferService.getTransfer(id)
  }
  if (kind === "budget") {
    return BudgetService.getBudget(id)
  }
  return AutoPaymentService.getAutoPayment(id)
}

export function DocumentEditDialog({ document, onOpenChange, onSaved }: DocumentEditDialogProps) {
  const isOpen = Boolean(document)
  const documentQuery = useQuery({
    queryKey: ["document-edit-dialog", document?.kind, document?.id],
    enabled: Boolean(document?.kind && document?.id),
    queryFn: () => loadDocument(document!.kind, document!.id),
    staleTime: 30_000,
  })

  const close = () => onOpenChange(false)
  const handleSaved = (id?: string) => {
    if (document && id) {
      onSaved?.({ kind: document.kind, id })
    }
    close()
  }

  return (
    <Dialog.Root open={isOpen} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(calc(100vw-18px),980px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-[28px] border border-border/70 bg-background shadow-[0_35px_120px_-45px_rgba(15,23,42,0.85)]">
          <div className="flex items-start justify-between gap-4 border-b border-border/60 px-5 py-4 sm:px-6">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-xl font-semibold tracking-[-0.03em] text-foreground">
                {document ? getTitle(document.kind) : "Редактирование документа"}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-muted-foreground">
                Сохранение закроет окно и оставит тебя на текущей странице.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" className="shrink-0 rounded-2xl" aria-label="Закрыть">
                <X className="h-4 w-4" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="max-h-[calc(92vh-92px)] overflow-y-auto px-4 py-4 sm:px-6">
            {documentQuery.isLoading ? (
              <FullPageLoader label="Загружаем документ..." />
            ) : documentQuery.isError || !document || !documentQuery.data ? (
              <div className="space-y-3 rounded-[22px] border border-destructive/20 bg-destructive/10 p-5 text-sm text-destructive">
                Документ не удалось загрузить. Закрой окно и попробуй открыть его снова.
              </div>
            ) : document.kind === "receipt" ? (
              <FinancialOperationForm
                mode="receipt"
                operation={documentQuery.data as any}
                isEdit
                embedded
                onCancel={close}
                onSaved={(saved) => handleSaved(saved.id)}
              />
            ) : document.kind === "expenditure" ? (
              <FinancialOperationForm
                mode="expenditure"
                operation={documentQuery.data as any}
                isEdit
                embedded
                onCancel={close}
                onSaved={(saved) => handleSaved(saved.id)}
              />
            ) : document.kind === "transfer" ? (
              <TransferForm
                transfer={documentQuery.data as any}
                isEdit
                embedded
                onCancel={close}
                onSaved={(saved) => handleSaved(saved.id)}
              />
            ) : document.kind === "budget" ? (
              <BudgetForm
                budget={documentQuery.data as any}
                isEdit
                embedded
                onCancel={close}
                onSaved={(saved) => handleSaved(saved.id)}
              />
            ) : (
              <AutoPaymentForm
                autoPayment={documentQuery.data as any}
                isEdit
                embedded
                onCancel={close}
                onSaved={(saved) => handleSaved(saved.id)}
              />
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
