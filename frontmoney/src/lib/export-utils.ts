// Note: heavy browser-only libs are imported dynamically inside functions
// to avoid SSR/prerender issues
import { formatCurrency, formatDate } from './formatters'

// Типы экспортируемых данных
export type ExportDataRow = Record<string, any>
export type ExportColumn = {
  key: string
  header: string
  formatter?: (value: any) => string
}

/**
 * Экспорт данных в формат CSV
 * @param data Данные для экспорта
 * @param columns Описание колонок
 * @param filename Имя файла
 */
export const exportToCSV = async (data: ExportDataRow[], columns: ExportColumn[], filename: string) => {
  const [{ default: Papa }, { saveAs }] = await Promise.all([
    import('papaparse'),
    import('file-saver'),
  ])
  // Подготовка данных в формате для CSV
  const csvData = data.map(row => {
    const newRow: Record<string, string> = {}
    columns.forEach(column => {
      const value = row[column.key]
      newRow[column.header] = column.formatter ? column.formatter(value) : String(value ?? '')
    })
    return newRow
  })
  
  // Преобразование в CSV
  const csv = Papa.unparse(csvData)
  
  // Создание Blob
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  
  // Скачивание файла
  saveAs(blob, `${filename}.csv`)
}

/**
 * Экспорт данных в формат PDF
 * @param data Данные для экспорта
 * @param columns Описание колонок
 * @param filename Имя файла
 * @param title Заголовок отчета
 */
export const exportToPDF = async (
  data: ExportDataRow[],
  columns: ExportColumn[],
  filename: string,
  title: string
) => {
  const [{ default: jsPDF }, { default: autoTable }] = await Promise.all([
    import('jspdf'),
    import('jspdf-autotable'),
  ])
  // Создание PDF документа
  const doc = new jsPDF('p', 'mm', 'a4')
  
  // Добавление заголовка
  doc.setFontSize(18)
  doc.text(title, 14, 22)
  
  // Добавление даты создания
  doc.setFontSize(10)
  doc.text(`Дата создания: ${new Date().toLocaleDateString('ru-RU')}`, 14, 30)
  
  // Подготовка данных для таблицы
  const tableColumn = columns.map(col => col.header)
  const tableRows = data.map(row => {
    return columns.map(column => {
      const value = row[column.key]
      return column.formatter ? column.formatter(value) : String(value ?? '')
    })
  })
  
  // Генерация таблицы
  autoTable(doc as any, {
    startY: 35,
    head: [tableColumn],
    body: tableRows,
    styles: { fontSize: 8 },
    headStyles: { fillColor: [41, 128, 185] },
    margin: { top: 35 },
    theme: 'grid'
  })
  
  // Скачивание файла
  doc.save(`${filename}.pdf`)
}

/**
 * Экспорт диаграммы в PDF
 * @param chartRef Ref на элемент диаграммы
 * @param filename Имя файла
 * @param title Заголовок отчета
 */
export const exportChartToPDF = async (
  chartRef: React.RefObject<HTMLDivElement>,
  filename: string,
  title: string
) => {
  if (!chartRef.current) return
  const [{ default: jsPDF }, { default: html2canvas }] = await Promise.all([
    import('jspdf'),
    import('html2canvas'),
  ])

  // Создание скриншота диаграммы
  const canvas = await html2canvas(chartRef.current, {
    scale: 2,
    logging: false,
    useCORS: true,
    allowTaint: true
  })
  
  // Преобразование canvas в изображение
  const imgData = canvas.toDataURL('image/png')
  
  // Определение размеров страницы и пропорций
  const imgWidth = 210 - 20 // ширина A4 минус отступы
  const pageHeight = 297 // высота A4
  const imgHeight = (canvas.height * imgWidth) / canvas.width
  
  // Создание PDF
  const doc = new jsPDF('p', 'mm', 'a4')
  
  // Добавление заголовка
  doc.setFontSize(18)
  doc.text(title, 10, 20)
  
  // Добавление даты
  doc.setFontSize(10)
  doc.text(`Дата создания: ${new Date().toLocaleDateString('ru-RU')}`, 10, 28)
  
  // Добавление изображения
  doc.addImage(imgData, 'PNG', 10, 35, imgWidth, imgHeight)
  
  // Скачивание файла
  doc.save(`${filename}.pdf`)
}

/**
 * Форматтеры для экспорта
 */
export const exportFormatters = {
  currency: (value: number) => formatCurrency(value),
  date: (dateString: string) => formatDate(dateString),
  percent: (value: number) => `${value.toFixed(2)}%`,
  boolean: (value: boolean) => value ? 'Да' : 'Нет'
}
