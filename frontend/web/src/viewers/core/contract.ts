import type { ComponentType, Ref } from 'react'
import type { SourceLocation } from '../../lib/api'

export type Highlight = { location: SourceLocation; lowConfidence?: boolean }

/** Imperative handle every viewer adapter implements. Chat/citation code depends only on this. */
export type ViewerHandle = {
  navigateTo(location: SourceLocation, regionIndex?: number): void
  highlight(highlights: Highlight[]): void
  clearHighlights(): void
  search(query: string, previous?: boolean): void
  zoom(action: 'in' | 'out' | 'fit-width' | 'fit-page'): void
}

export type ViewerState = { status: 'loading' | 'ready' | 'error'; message?: string; page?: number; pages?: number; scale?: number }

export type ViewerProps = {
  src: string
  ref: Ref<ViewerHandle>
  onState: (s: ViewerState) => void
}

export type ViewerAdapter = ComponentType<ViewerProps>
