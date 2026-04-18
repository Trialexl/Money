"use client"

import React, { useState } from 'react'
import { Button } from "@/components/ui/button"
import { 
  DownloadIcon,
  FileTextIcon,
  FileTypeIcon,
  Loader2,
} from "lucide-react"
import { exportToCSV, exportToPDF, ExportDataRow, ExportColumn, exportChartToPDF } from "@/lib/export-utils"

interface ExportReportButtonsProps {
  data: ExportDataRow[]
  columns: ExportColumn[]
  filename: string
  title: string
  chartRef?: React.RefObject<HTMLDivElement>
}

export default function ExportReportButtons({ 
  data, 
  columns, 
  filename, 
  title,
  chartRef
}: ExportReportButtonsProps) {
  const [pendingAction, setPendingAction] = useState<"csv" | "pdf" | "chart" | null>(null)
  const isDisabled = data.length === 0 || pendingAction !== null

  const runExport = async (action: "csv" | "pdf" | "chart", handler: () => Promise<void>) => {
    setPendingAction(action)
    try {
      await handler()
    } finally {
      setPendingAction(null)
    }
  }

  const handleExportCSV = async () => {
    await runExport("csv", () => exportToCSV(data, columns, filename))
  }

  const handleExportPDF = async () => {
    await runExport("pdf", () => exportToPDF(data, columns, filename, title))
  }

  const handleExportChartPDF = async () => {
    if (chartRef && chartRef.current) {
      await runExport("chart", () => exportChartToPDF(chartRef, `${filename}-chart`, title))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-[24px] border border-border/70 bg-background/70 p-2">
      <span className="px-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Экспорт</span>
      <Button
        variant="outline"
        size="sm"
        onClick={handleExportCSV}
        disabled={isDisabled}
      >
        {pendingAction === "csv" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileTextIcon className="h-3.5 w-3.5" />}
        CSV
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={handleExportPDF}
        disabled={isDisabled}
      >
        {pendingAction === "pdf" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileTypeIcon className="h-3.5 w-3.5" />}
        PDF
      </Button>
      {chartRef ? (
        <Button
          variant="outline"
          size="sm"
          onClick={handleExportChartPDF}
          disabled={isDisabled || !chartRef.current}
        >
          {pendingAction === "chart" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <DownloadIcon className="h-3.5 w-3.5" />}
          График PDF
        </Button>
      ) : null}
    </div>
  )
}
