import { useQuery } from '@tanstack/react-query'
import { Menu, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Group, Panel, Separator, useDefaultLayout, usePanelRef } from 'react-resizable-panels'
import { ChatPanel } from '../features/chat/ChatPanel'
import { Home } from '../features/home/Home'
import { Sidebar } from '../features/sessions/Sidebar'
import { Wordmark } from '../components/Logo'
import { ProcessingState } from '../features/workspace/ProcessingState'
import { api, TERMINAL, type SessionOut } from '../lib/api'
import { useUi } from '../stores/ui'
import { DocumentViewer } from '../viewers/core/DocumentViewer'

const wideQuery = window.matchMedia('(min-width: 900px)')
const useWide = () =>
  useSyncExternalStore(
    (cb) => {
      wideQuery.addEventListener('change', cb)
      return () => wideQuery.removeEventListener('change', cb)
    },
    () => wideQuery.matches,
  )
const iconBtn = 'grid size-8 place-items-center rounded-md text-muted hover:bg-surface hover:text-fg'

export function App() {
  const wide = useWide()
  const { sessionId, sidebarOpen, toggleSidebar } = useUi()
  const [drawer, setDrawer] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        if (wide) toggleSidebar()
        else setDrawer((d) => !d)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [wide, toggleSidebar])

  const main = sessionId ? <SessionView key={sessionId} sessionId={sessionId} wide={wide} /> : <Home />

  if (!wide) {
    return (
      <div className="flex h-full flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-2">
          <button className={iconBtn} onClick={() => setDrawer(true)} aria-label="Show conversations">
            <Menu size={18} />
          </button>
          <Wordmark />
        </header>
        <main className="min-h-0 flex-1">{main}</main>
        {drawer && (
          <div className="fixed inset-0 z-40 flex" role="dialog" aria-modal="true" aria-label="Conversations">
            <div className="w-[84vw] max-w-[300px] border-r border-line shadow-2xl">
              <Sidebar onNavigate={() => setDrawer(false)} />
            </div>
            <button className="flex-1 bg-black/50" onClick={() => setDrawer(false)} aria-label="Close conversations" />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full">
      <aside
        className={`shrink-0 overflow-hidden border-line transition-[width] duration-200 ease-out motion-reduce:transition-none ${
          sidebarOpen ? 'w-[264px] border-r' : 'w-0'
        }`}
        aria-hidden={!sidebarOpen}
        inert={!sidebarOpen}
      >
        <div className="h-full w-[264px]">
          <Sidebar />
        </div>
      </aside>
      <main className="relative min-w-0 flex-1">
        {!sidebarOpen && (
          <button
            className={`${iconBtn} absolute left-2 top-3 z-10 bg-bg`}
            onClick={() => toggleSidebar(true)}
            aria-label="Show sidebar"
            title="Show sidebar (Ctrl+B)"
          >
            <PanelLeftOpen size={17} />
          </button>
        )}
        {main}
      </main>
    </div>
  )
}

function SessionView({ sessionId, wide }: { sessionId: string; wide: boolean }) {
  const { openSession, mobileTab, setMobileTab, sidebarOpen } = useUi()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const session = sessions.data?.find((s) => s.id === sessionId)
  const doc = useQuery({
    queryKey: ['document', session?.document_id],
    queryFn: () => api.getDocument(session!.document_id),
    enabled: !!session,
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 1000),
  })

  useEffect(() => {
    if (sessions.isSuccess && !session) openSession(null) // deleted or foreign link
  }, [sessions.isSuccess, session, openSession])

  if (!session || !doc.data) return null
  const chat = (
    <div className="flex h-full flex-col">
      {wide && <ChatHeader session={session} indent={!sidebarOpen} />}
      <div className="min-h-0 flex-1">
        {doc.data.status === 'ready' ? <ChatPanel session={session} doc={doc.data} /> : <ProcessingState doc={doc.data} />}
      </div>
    </div>
  )
  const viewer = <DocumentViewer key={doc.data.id} doc={doc.data} />

  if (!wide) {
    return (
      <div className="flex h-full flex-col">
        <div role="tablist" className="flex shrink-0 border-b border-line">
          {(['chat', 'document'] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={mobileTab === t}
              onClick={() => setMobileTab(t)}
              className={`h-10 flex-1 ${mobileTab === t ? 'border-b-2 border-accent text-fg' : 'text-muted'}`}
            >
              {t === 'chat' ? 'Conversation' : 'Document'}
            </button>
          ))}
        </div>
        {/* Both stay mounted so the PDF keeps its place when switching tabs. */}
        <div className={`min-h-0 flex-1 ${mobileTab === 'chat' ? '' : 'hidden'}`}>{chat}</div>
        <div className={`min-h-0 flex-1 ${mobileTab === 'document' ? '' : 'hidden'}`}>{viewer}</div>
      </div>
    )
  }
  return <SplitView chat={chat} viewer={viewer} />
}

function ChatHeader({ session, indent }: { session: SessionOut; indent: boolean }) {
  return (
    <div className={`flex h-14 shrink-0 items-center border-b border-line pr-4 ${indent ? 'pl-12' : 'pl-5'}`}>
      <h1 className="truncate text-[14px] font-medium text-fg">{session.title ?? 'New conversation'}</h1>
    </div>
  )
}

function SplitView({ chat, viewer }: { chat: ReactNode; viewer: ReactNode }) {
  const layout = useDefaultLayout({ id: 'anydoc.workspace', storage: safeStorage })
  const viewerPanel = usePanelRef()
  const [collapsed, setCollapsed] = useState(false)
  const toggle = () => {
    const p = viewerPanel.current
    if (!p) return
    if (p.isCollapsed()) p.expand()
    else p.collapse()
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '\\') {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <Group orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="h-full">
      <Panel id="chat" defaultSize="42" minSize={360}>
        {chat}
      </Panel>
      <Separator className="group relative w-px bg-line outline-none focus-visible:bg-accent data-[separator=active]:bg-accent data-[separator=hover]:bg-accent/60">
        <span className="absolute inset-y-0 -left-1.5 -right-1.5" aria-hidden />
        <button
          onClick={toggle}
          className="absolute left-1/2 top-3.5 z-10 grid size-7 -translate-x-1/2 place-items-center rounded-md border border-line bg-bg text-muted opacity-0 hover:text-fg focus-visible:opacity-100 group-hover:opacity-100"
          aria-label={collapsed ? 'Show document (Ctrl+\\)' : 'Hide document (Ctrl+\\)'}
        >
          {collapsed ? <PanelRightOpen size={14} /> : <PanelRightClose size={14} />}
        </button>
      </Separator>
      <Panel
        id="viewer"
        defaultSize="58"
        minSize={360}
        collapsible
        collapsedSize={0}
        panelRef={viewerPanel}
        onResize={() => setCollapsed(viewerPanel.current?.isCollapsed() ?? false)}
      >
        {viewer}
      </Panel>
    </Group>
  )
}

const safeStorage = {
  getItem: (k: string) => {
    try {
      return localStorage.getItem(k)
    } catch {
      return null
    }
  },
  setItem: (k: string, v: string) => {
    try {
      localStorage.setItem(k, v)
    } catch {
      /* layout persistence is a convenience */
    }
  },
}
