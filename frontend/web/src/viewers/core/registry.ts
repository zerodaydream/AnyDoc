import { lazy } from 'react'
import type { ViewerAdapter } from './contract'

const TextViewer = lazy(() => import('../text/TextViewer'))

// Keyed by the backend's validated `format`, never the file extension. New format = one line here.
export const adapters: Partial<Record<string, ViewerAdapter>> = {
  pdf: lazy(() => import('../pdf/PdfViewer')),
  text: TextViewer,
  markdown: TextViewer,
  docx: lazy(() => import('../docx/DocxViewer')),
  csv: lazy(() => import('../csv/CsvViewer')),
}
