import { lazy } from 'react'
import type { ViewerAdapter } from './contract'

// Keyed by the backend's validated `format`, never the file extension. New format = one line here.
export const adapters: Partial<Record<string, ViewerAdapter>> = {
  pdf: lazy(() => import('../pdf/PdfViewer')),
}
