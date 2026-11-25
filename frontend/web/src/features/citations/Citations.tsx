import type { Citation } from '../../lib/api'
import { useUi } from '../../stores/ui'

const isLow = (c: Citation) => c.flags.includes('low_confidence')

export function CitationMark({ id, n, citation }: { id: string; n: number; citation: Citation }) {
  const activate = useUi((s) => s.activate)
  const active = useUi((s) => s.active?.key === `${id}:${n}`)
  return (
    <button
      type="button"
      onClick={() => activate(`${id}:${n}`, n, citation)}
      aria-label={`Citation ${n}, page ${citation.page ?? '?'}`}
      aria-pressed={active}
      className={`mx-0.5 -translate-y-1.5 align-baseline font-serif text-[12px] leading-none tabular-nums ${
        isLow(citation) ? 'text-warn underline decoration-dotted' : 'text-accent'
      } ${active ? 'rounded-sm bg-accent text-on-accent px-0.5' : 'hover:text-accent-strong'}`}
    >
      {n}
    </button>
  )
}

export function EvidenceRow({ id, n, citation }: { id: string; n: number; citation: Citation }) {
  const activate = useUi((s) => s.activate)
  const active = useUi((s) => s.active?.key === `${id}:${n}`)
  const low = isLow(citation)
  return (
    <button
      type="button"
      onClick={() => activate(`${id}:${n}`, n, citation)}
      title={low ? 'Low-confidence text recognition: check the original.' : undefined}
      className={`group flex w-full items-baseline gap-2 rounded-md px-2 py-1 text-left hover:bg-surface ${active ? 'bg-surface' : ''}`}
    >
      <span className={`font-serif tabular-nums ${low ? 'text-warn' : 'text-accent'}`}>{n}</span>
      <span className="shrink-0 text-muted">p. {citation.page ?? '?'}</span>
      <span className="line-clamp-1 min-w-0 text-muted group-hover:text-fg">“{citation.quote}”</span>
    </button>
  )
}
