import { useQuery } from '@tanstack/react-query'
import { Moon, PanelRightClose, PanelRightOpen, Plus, Sun } from 'lucide-react'
import { useEffect, useSyncExternalStore } from 'react'
import { Group, Panel, Separator, useDefaultLayout, usePanelRef } from 'react-resizable-panels'
import { ChatPanel } from '../features/chat/ChatPanel'
import { UploadZone } from '../features/uploads/UploadZone'
import { ProcessingState } from '../features/workspace/ProcessingState'
import { api, TERMINAL, type DocumentOut } from '../lib/api'
import { useUi } from '../stores/ui'
import { DocumentViewer } from '../viewers/core/DocumentViewer'

const wide = window.matchMedia('(min-width: 768px)')
const useWide = () => useSyncExternalStore((cb) => (wide.addEventListener('change', cb), () => wide.removeEventListener('change', cb)), () => wide.matches)
const iconBtn = 'grid size-9 place-items-center rounded-lg text-muted hover:bg-surface hover:text-fg'

export function App() {
  const { documentId, uploading, theme, toggleTheme, openDocument, setUploading, mobileTab, setMobileTab } = useUi()
  const isWide = useWide()
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments })
  const doc = useQuery({
    queryKey: ['document', documentId],
    queryFn: () => api.getDocument(documentId!),
    enabled: !!documentId,
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 1000),
  })

  useEffect(() => {
    if (!documentId && docs.data?.length) openDocument(docs.data[0].id)
  }, [documentId, docs.data, openDocument])

  const current = doc.data
  const showUpload = uploading || (docs.isSuccess && docs.data.length === 0)

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-bg px-3">
        <span className="mr-2 font-serif text-[20px] tracking-tight text-fg">AnyDoc</span>
        {!!docs.data?.length && (
          <select
            value={showUpload ? '' : (documentId ?? '')}
            onChange={(e) => openDocument(e.target.value)}
            aria-label="Open document"
            className="h-8 max-w-[40vw] truncate rounded-md border border-line bg-surface px-2 text-fg"
          >
            {showUpload && <option value="">New document</option>}
            {docs.data.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}
              </option>
            ))}
          </select>
        )}
        <button onClick={() => setUploading(true)} className={`${iconBtn} ml-1`} aria-label="Open a new document" title="Open a new document">
          <Plus size={18} />
        </button>
        <div className="ml-auto flex items-center gap-1">
          <button onClick={toggleTheme} className={iconBtn} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
            {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>
      <main className="min-h-0 flex-1">{showUpload ? <UploadZone /> : current ? <Workspace doc={current} wide={isWide} mobileTab={mobileTab} setMobileTab={setMobileTab} /> : null}</main>
    </div>
  )
}

function Workspace({ doc, wide, mobileTab, setMobileTab }: { doc: DocumentOut; wide: boolean; mobileTab: 'chat' | 'document'; setMobileTab: (t: 'chat' | 'document') => void }) {
  const chat = doc.status === 'ready' ? <ChatPanel doc={doc} /> : <ProcessingState doc={doc} />
  const viewer = <DocumentViewer key={doc.id} doc={doc} />

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
              className={`h-10 flex-1 capitalize ${mobileTab === t ? 'border-b-2 border-accent text-fg' : 'text-muted'}`}
            >
              {t}
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

function SplitView({ chat, viewer }: { chat: React.ReactNode; viewer: React.ReactNode }) {
  const layout = useDefaultLayout({ id: 'anydoc.workspace', storage: safeStorage })
  const viewerPanel = usePanelRef()
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
      <Panel id="chat" defaultSize="40" minSize={320}>
        {chat}
      </Panel>
      <Separator className="group relative w-px bg-line outline-none data-[separator=hover]:bg-accent data-[separator=active]:bg-accent focus-visible:bg-accent">
        <span className="absolute inset-y-0 -left-1 -right-1" aria-hidden />
        <button
          onClick={toggle}
          className="absolute left-1/2 top-2 z-10 grid size-7 -translate-x-1/2 place-items-center rounded-md border border-line bg-bg text-muted opacity-0 hover:text-fg group-hover:opacity-100 focus-visible:opacity-100"
          aria-label="Toggle document panel (Ctrl+\)"
        >
          {viewerPanel.current?.isCollapsed() ? <PanelRightOpen size={14} /> : <PanelRightClose size={14} />}
        </button>
      </Separator>
      <Panel id="viewer" defaultSize="60" minSize={320} collapsible collapsedSize={0} panelRef={viewerPanel}>
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
