"use client"

import FinancialOperationForm from "@/components/shared/financial-operation-form"
import { Expenditure } from "@/services/financial-operations-service"

interface ExpenditureFormProps {
  expenditure?: Expenditure
  isEdit?: boolean
}

export default function ExpenditureForm({ expenditure, isEdit = false }: ExpenditureFormProps) {
  return <FinancialOperationForm mode="expenditure" operation={expenditure} isEdit={isEdit} />
}
