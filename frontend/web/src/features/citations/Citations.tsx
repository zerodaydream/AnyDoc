import { whereLabel, type Citation } from '../../lib/api'
import { useUi } from '../../stores/ui'

const isLow = (c: Citation) => c.flags.includes('low_confidence')

/** Numbered clay pill in the answer text; the same numeral is pinned in the page margin when active. */
export function CitationMark({ id, n, citation }: { id: string; n: number; citation: Citation }) {
  const activate = useUi((s) => s.activate)
  const active = useUi((s) => s.active?.key === `${id}:${n}`)
  const low = isLow(citation)
  return (
    <button
      type="button"
      onClick={() => activate(`${id}:${n}`, n, citation)}
      aria-label={`Citation ${n}, ${whereLabel(citation)}`}
      aria-pressed={active}
      title={low ? 'Low-confidence text: check the original' : whereLabel(citation, true)}
      className={`mx-[3px] inline-flex h-[18px] min-w-[18px] -translate-y-[2px] items-center justify-center rounded-[5px] px-1 align-middle font-sans text-[11px] font-semibold leading-none tabular-nums transition-colors ${
        active
          ? low
            ? 'bg-warn text-on-accent'
            : 'bg-accent text-on-accent'
          : low
            ? 'bg-warn/15 text-warn ring-1 ring-warn/40 hover:bg-warn/25'
            : 'bg-accent/15 text-accent hover:bg-accent/25'
      }`}
    >
      {n}
    </button>
  )
}

/** A verified quote as it appears in the document: clay rule, serif text, where it is. */
export function SourceQuote({ id, n, citation }: { id: string; n: number; citation: Citation }) {
  const activate = useUi((s) => s.activate)
  const active = useUi((s) => s.active?.key === `${id}:${n}`)
  const low = isLow(citation)
  return (
    <button
      type="button"
      onClick={() => activate(`${id}:${n}`, n, citation)}
      className={`group flex w-full gap-3 rounded-lg py-2 pl-2 pr-3 text-left transition-colors ${
        active ? 'bg-surface' : 'hover:bg-surface/60'
      }`}
    >
      <span
        className={`mt-[3px] inline-flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-[5px] font-sans text-[11px] font-semibold tabular-nums ${
          active ? 'bg-accent text-on-accent' : low ? 'bg-warn/15 text-warn' : 'bg-accent/15 text-accent'
        }`}
      >
        {n}
      </span>
      <span className={`min-w-0 flex-1 border-l-2 pl-3 ${low ? 'border-warn/60' : 'border-accent/50'}`}>
        <span className="line-clamp-2 font-serif text-[15px] italic leading-[23px] text-fg/90">{citation.quote}</span>
        <span className="mt-0.5 block font-sans text-[12px] text-muted">
          {whereLabel(citation, true)}
          {citation.location.regions.length > 1 && `, ${citation.location.regions.length} places`}
          {citation.match === 'fuzzy' && ', close match'}
          {low && ', low-confidence text'}
        </span>
      </span>
    </button>
  )
}
