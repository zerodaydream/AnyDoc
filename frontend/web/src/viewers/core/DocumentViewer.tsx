import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, ListTree, Maximize2, Minus, Plus, Search } from 'lucide-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import { api, type DocumentOut } from '../../lib/api'
import { useUi } from '../../stores/ui'
import type { ViewerHandle, ViewerState } from './contract'
import { adapters } from './registry'

const btn = 'inline-flex h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-muted hover:bg-surface hover:text-fg disabled:opacity-40'

export function DocumentViewer({ doc }: { doc: DocumentOut }) {
  const Adapter = doc.format ? adapters[doc.format] : undefined
  const handle = useRef<ViewerHandle>(null)
  const [state, setState] = useState<ViewerState>({ status: 'loading' })
  const [query, setQuery] = useState('')
  const [pageDraft, setPageDraft] = useState<string | null>(null)
  const [outlineOpen, setOutlineOpen] = useState(false)
  const active = useUi((s) => s.active)
  const [step, setStep] = useState({ seq: -1, idx: 0 })
  const region = step.seq === active?.seq ? step.idx : 0
  const outline = useQuery({
    queryKey: ['outline', doc.id],
    queryFn: () => api.outline(doc.id),
    enabled: doc.status === 'ready',
    staleTime: Infinity,
  })

  useEffect(() => {
    if (!active || state.status !== 'ready') return
    const low = active.citation.flags.includes('low_confidence')
    handle.current?.highlight([{ location: active.citation.location, lowConfidence: low, label: String(active.n) }])
    handle.current?.navigateTo(active.citation.location, 0)
  }, [active, state.status])

  useEffect(() => {
    if (!outlineOpen) return
    const close = (e: KeyboardEvent | MouseEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !(e.target as HTMLElement).closest('[data-outline]')) setOutlineOpen(false)
    }
    window.addEventListener('keydown', close)
    window.addEventListener('mousedown', close)
    return () => {
      window.removeEventListener('keydown', close)
      window.removeEventListener('mousedown', close)
    }
  }, [outlineOpen])

  const regions = active?.citation.location.regions.length ?? 0
  const stepRegion = (d: number) => {
    if (!active) return
    const next = (region + d + regions) % regions
    setStep({ seq: active.seq, idx: next })
    handle.current?.navigateTo(active.citation.location, next)
  }

  if (!Adapter) return <p className="p-8 text-muted">This file type can’t be displayed yet.</p>

  return (
    <section className="flex h-full min-w-0 flex-col bg-sunken" aria-label="Document viewer">
      <div className="flex h-14 shrink-0 items-center gap-1 border-b border-line bg-bg px-2">
        <div className="relative" data-outline>
          <button
            className={`${btn} gap-1.5 px-2`}
            onClick={() => setOutlineOpen((o) => !o)}
            disabled={!outline.data?.length}
            aria-expanded={outlineOpen}
            aria-haspopup="menu"
            title="Sections"
          >
            <ListTree size={16} />
            <span className="hidden text-[13px] lg:inline">Sections</span>
          </button>
          {outlineOpen && (
            <ul role="menu" className="absolute left-0 top-10 z-20 max-h-[60vh] w-72 overflow-y-auto rounded-xl border border-line bg-bg p-1">
              {outline.data?.map((o) => (
                <li key={o.block_id} role="none">
                  <button
                    role="menuitem"
                    onClick={() => {
                      handle.current?.navigateTo(o.location)
                      setOutlineOpen(false)
                    }}
                    className="flex w-full items-baseline gap-3 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg hover:bg-surface"
                  >
                    <span className="min-w-0 flex-1 truncate">{o.text}</span>
                    <span className="shrink-0 tabular-nums text-muted">{o.ref.replace(/^(page|line)s? /, '')}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {state.pages ? (
          <form
            className="flex items-center gap-1 pl-1 text-[13px] text-muted"
            onSubmit={(e) => {
              e.preventDefault()
              if (pageDraft) handle.current?.goToPage(Number(pageDraft))
              setPageDraft(null)
            }}
          >
            <input
              value={pageDraft ?? String(state.page ?? 1)}
              onChange={(e) => setPageDraft(e.target.value.replace(/\D/g, ''))}
              onBlur={() => setPageDraft(null)}
              inputMode="numeric"
              aria-label="Page number"
              className="h-7 w-10 rounded-md border border-line bg-surface text-center tabular-nums text-fg outline-none focus:border-accent"
            />
            <span className="tabular-nums">of {state.pages}</span>
          </form>
        ) : null}

        {regions > 1 && (
          <div className="ml-2 flex items-center rounded-md border border-line text-[13px]" aria-label="Evidence locations">
            <button className={btn} onClick={() => stepRegion(-1)} aria-label="Previous evidence location">
              <ChevronLeft size={15} />
            </button>
            <span className="tabular-nums text-fg">
              {region + 1} of {regions}
            </span>
            <button className={btn} onClick={() => stepRegion(1)} aria-label="Next evidence location">
              <ChevronRight size={15} />
            </button>
          </div>
        )}

        <div className="ml-auto flex items-center gap-0.5">
          <form
            className="mr-1 hidden h-8 items-center rounded-lg border border-line bg-surface pl-2 focus-within:border-accent/70 sm:flex"
            role="search"
            onSubmit={(e) => {
              e.preventDefault()
              if (query) handle.current?.search(query)
            }}
          >
            <Search size={14} className="text-muted" aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && e.shiftKey && query) {
                  e.preventDefault()
                  handle.current?.search(query, true)
                }
              }}
              placeholder="Find"
              aria-label="Find in document"
              className="h-full w-28 bg-transparent px-2 text-[13px] text-fg outline-none placeholder:text-muted lg:w-40"
            />
            {query && (
              <>
                <button type="button" className={btn} onClick={() => handle.current?.search(query, true)} aria-label="Previous match">
                  <ChevronUp size={14} />
                </button>
                <button type="submit" className={btn} aria-label="Next match">
                  <ChevronDown size={14} />
                </button>
              </>
            )}
          </form>
          <button className={btn} onClick={() => handle.current?.zoom('out')} aria-label="Zoom out">
            <Minus size={15} />
          </button>
          <span className="w-11 text-center text-[13px] tabular-nums text-muted">{state.scale ? `${Math.round(state.scale * 100)}%` : ''}</span>
          <button className={btn} onClick={() => handle.current?.zoom('in')} aria-label="Zoom in">
            <Plus size={15} />
          </button>
          <button className={btn} onClick={() => handle.current?.zoom('fit-width')} aria-label="Fit to width" title="Fit to width">
            <Maximize2 size={14} />
          </button>
          {state.modes && (
            <div role="radiogroup" aria-label="View" className="ml-2 flex h-8 items-center gap-0.5 rounded-lg p-0.5 text-[13px]">
              {state.modes.map((m) => (
                <button
                  key={m.id}
                  role="radio"
                  aria-checked={state.mode === m.id}
                  onClick={() => handle.current?.setMode?.(m.id)}
                  className={`h-7 rounded-md px-2.5 transition-colors ${
                    state.mode === m.id ? 'bg-surface font-medium text-fg' : 'text-muted hover:text-fg'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {state.status === 'error' && (
          <p role="alert" className="absolute inset-x-0 top-8 z-10 mx-auto max-w-md text-center text-danger">
            {state.message}
          </p>
        )}
        <Suspense fallback={null}>
          <Adapter src={doc.file_url} format={doc.format ?? ''} ref={handle} onState={setState} />
        </Suspense>
      </div>
    </section>
  )
}
