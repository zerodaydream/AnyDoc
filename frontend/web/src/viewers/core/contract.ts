import type { ComponentType, Ref } from 'react'
import type { SourceLocation } from '../../lib/api'

export type Highlight = { location: SourceLocation; lowConfidence?: boolean; label?: string }

/** Imperative handle every viewer adapter implements. Chat/citation code depends only on this. */
export type ViewerHandle = {
  navigateTo(location: SourceLocation, regionIndex?: number): void
  highlight(highlights: Highlight[]): void
  clearHighlights(): void
  search(query: string, previous?: boolean): void
  zoom(action: 'in' | 'out' | 'fit-width' | 'fit-page'): void
  goToPage(page: number): void // no-op for formats without pages (they never report `pages`)
  setMode?(mode: string): void // for viewers that report `modes`
}

/** Display modes a viewer offers (e.g. Markdown "Preview" / "Markdown"); the toolbar shows them as a toggle. */
export type ViewerMode = { id: string; label: string }

export type ViewerState = {
  status: 'loading' | 'ready' | 'error'
  message?: string
  page?: number
  pages?: number
  scale?: number
  modes?: ViewerMode[]
  mode?: string
}

export type ViewerProps = {
  src: string
  format: string // the backend's validated format; one adapter may serve several (text + markdown)
  ref: Ref<ViewerHandle>
  onState: (s: ViewerState) => void
}

export type ViewerAdapter = ComponentType<ViewerProps>
