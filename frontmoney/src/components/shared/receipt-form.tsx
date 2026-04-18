"use client"

import FinancialOperationForm from "@/components/shared/financial-operation-form"
import { Receipt } from "@/services/financial-operations-service"

interface ReceiptFormProps {
  receipt?: Receipt
  isEdit?: boolean
}

export default function ReceiptForm({ receipt, isEdit = false }: ReceiptFormProps) {
  return <FinancialOperationForm mode="receipt" operation={receipt} isEdit={isEdit} />
}
