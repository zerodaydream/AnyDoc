import { create } from 'zustand'
import type { Citation } from '../lib/api'

export type ActiveCitation = { key: string; n: number; citation: Citation; seq: number }
type Theme = 'dark' | 'light'

const read = (k: string) => {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}
const write = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v)
  } catch {
    /* private mode: preference applies for this visit only */
  }
}

// The open conversation lives in the URL hash, so reload and back/forward keep it.
const sessionFromHash = () => (location.hash.match(/^#\/c\/([0-9a-f-]{36})$/)?.[1] ?? null)

type UiState = {
  theme: Theme
  sessionId: string | null
  sidebarOpen: boolean
  active: ActiveCitation | null
  mobileTab: 'chat' | 'document'
  model: string | null // null = server default; validated against /api/models before use
  thinking: string | null // a level, 'off', or null = server default
  setModel: (m: string) => void
  setThinking: (t: string) => void
  toggleTheme: () => void
  openSession: (id: string | null) => void
  toggleSidebar: (open?: boolean) => void
  activate: (key: string, n: number, citation: Citation) => void
  setMobileTab: (t: 'chat' | 'document') => void
}

let seq = 0

export const useUi = create<UiState>((set, get) => ({
  theme: read('anydoc.theme') === 'light' ? 'light' : 'dark',
  sessionId: sessionFromHash(),
  sidebarOpen: read('anydoc.sidebar') !== 'closed',
  active: null,
  mobileTab: 'chat',
  model: read('anydoc.model'),
  thinking: read('anydoc.thinking'),
  setModel: (model) => {
    write('anydoc.model', model)
    set({ model })
  },
  setThinking: (thinking) => {
    write('anydoc.thinking', thinking)
    set({ thinking })
  },
  toggleTheme: () => {
    const theme: Theme = get().theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = theme
    write('anydoc.theme', theme)
    set({ theme })
  },
  openSession: (sessionId) => {
    if (sessionId !== get().sessionId) history.pushState(null, '', sessionId ? `#/c/${sessionId}` : '#/')
    set({ sessionId, active: null, mobileTab: 'chat' })
  },
  toggleSidebar: (open) => {
    const sidebarOpen = open ?? !get().sidebarOpen
    write('anydoc.sidebar', sidebarOpen ? 'open' : 'closed')
    set({ sidebarOpen })
  },
  // seq makes re-clicking the same citation re-scroll the viewer.
  activate: (key, n, citation) => set({ active: { key, n, citation, seq: ++seq }, mobileTab: 'document' }),
  setMobileTab: (mobileTab) => set({ mobileTab }),
}))

window.addEventListener('popstate', () => useUi.setState({ sessionId: sessionFromHash(), active: null }))
