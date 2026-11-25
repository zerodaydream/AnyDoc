import { create } from 'zustand'
import type { Citation } from '../lib/api'

export type ActiveCitation = { key: string; n: number; citation: Citation; seq: number }
type Theme = 'dark' | 'light'

function readTheme(): Theme {
  try {
    return localStorage.getItem('anydoc.theme') === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

type UiState = {
  theme: Theme
  documentId: string | null
  uploading: boolean
  active: ActiveCitation | null
  mobileTab: 'chat' | 'document'
  toggleTheme: () => void
  openDocument: (id: string | null) => void
  setUploading: (v: boolean) => void
  activate: (key: string, n: number, citation: Citation) => void
  setMobileTab: (t: 'chat' | 'document') => void
}

let seq = 0

export const useUi = create<UiState>((set, get) => ({
  theme: readTheme(),
  documentId: null,
  uploading: false,
  active: null,
  mobileTab: 'chat',
  toggleTheme: () => {
    const theme: Theme = get().theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('anydoc.theme', theme)
    } catch {
      /* private mode: theme still applies for this session */
    }
    set({ theme })
  },
  openDocument: (documentId) => set({ documentId, active: null, uploading: false }),
  setUploading: (uploading) => set({ uploading }),
  // seq makes re-clicking the same citation re-scroll the viewer.
  activate: (key, n, citation) => set({ active: { key, n, citation, seq: ++seq }, mobileTab: 'document' }),
  setMobileTab: (mobileTab) => set({ mobileTab }),
}))
