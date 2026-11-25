import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Maximize2, Minus, Plus, Search } from 'lucide-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import type { DocumentOut } from '../../lib/api'
import { useUi } from '../../stores/ui'
import type { ViewerHandle, ViewerState } from './contract'
import { adapters } from './registry'

const btn =
  'inline-flex h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-muted hover:bg-surface hover:text-fg disabled:opacity-40'

export function DocumentViewer({ doc }: { doc: DocumentOut }) {
  const Adapter = doc.format ? adapters[doc.format] : undefined
  const handle = useRef<ViewerHandle>(null)
  const [state, setState] = useState<ViewerState>({ status: 'loading' })
  const [query, setQuery] = useState('')
  const active = useUi((s) => s.active)
  const [step, setStep] = useState({ seq: -1, idx: 0 })
  const region = step.seq === active?.seq ? step.idx : 0

  useEffect(() => {
    if (!active || state.status !== 'ready') return
    const low = active.citation.flags.includes('low_confidence')
    handle.current?.highlight([{ location: active.citation.location, lowConfidence: low }])
    handle.current?.navigateTo(active.citation.location, 0)
  }, [active, state.status])

  const regions = active?.citation.location.regions.length ?? 0
  const stepRegion = (d: number) => {
    if (!active) return
    const next = (region + d + regions) % regions
    setStep({ seq: active.seq, idx: next })
    handle.current?.navigateTo(active.citation.location, next)
  }

  if (!Adapter) {
    return <p className="p-8 text-muted">This file type can't be displayed yet.</p>
  }

  return (
    <section className="flex h-full min-w-0 flex-col bg-sunken" aria-label="Document viewer">
      <div className="flex h-12 shrink-0 items-center gap-1 border-b border-line bg-bg px-2">
        <span className="px-2 tabular-nums text-muted" aria-live="polite">
          {state.pages ? `Page ${state.page} of ${state.pages}` : ' '}
        </span>
        {regions > 1 && (
          <div className="ml-1 flex items-center gap-0.5 rounded-md border border-line px-1" aria-label="Evidence regions">
            <button className={btn} onClick={() => stepRegion(-1)} aria-label="Previous evidence region">
              <ChevronLeft size={16} />
            </button>
            <span className="tabular-nums text-fg">
              {region + 1} of {regions}
            </span>
            <button className={btn} onClick={() => stepRegion(1)} aria-label="Next evidence region">
              <ChevronRight size={16} />
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-0.5">
          <form
            className="hidden items-center rounded-md border border-line bg-surface px-2 sm:flex"
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
              placeholder="Find in document"
              aria-label="Find in document"
              className="h-8 w-40 bg-transparent px-2 text-fg outline-none placeholder:text-muted"
            />
            <button type="button" className={btn} onClick={() => query && handle.current?.search(query, true)} aria-label="Previous match">
              <ChevronUp size={14} />
            </button>
            <button type="submit" className={btn} aria-label="Next match">
              <ChevronDown size={14} />
            </button>
          </form>
          <button className={btn} onClick={() => handle.current?.zoom('out')} aria-label="Zoom out">
            <Minus size={16} />
          </button>
          <span className="w-12 text-center tabular-nums text-muted">{state.scale ? `${Math.round(state.scale * 100)}%` : ''}</span>
          <button className={btn} onClick={() => handle.current?.zoom('in')} aria-label="Zoom in">
            <Plus size={16} />
          </button>
          <button className={btn} onClick={() => handle.current?.zoom('fit-width')} aria-label="Fit to width">
            <Maximize2 size={15} />
          </button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {state.status === 'error' && (
          <p role="alert" className="absolute inset-x-0 top-8 z-10 mx-auto max-w-md text-center text-danger">
            {state.message}
          </p>
        )}
        <Suspense fallback={null}>
          <Adapter src={doc.file_url} ref={handle} onState={setState} />
        </Suspense>
      </div>
    </section>
  )
}
