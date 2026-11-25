import { ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { formatSeconds } from './modelChoice'

const GLYPHS = ['·', '✢', '✳', '✶', '✻', '✽', '✻', '✶', '✳', '✢']
const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** Claude Code-style thinking: a clay glyph that turns while the model reasons, then "Thought for 4.2s". */
export function ThinkingBlock({
  text,
  live,
  startedAt,
  ms,
}: {
  text: string
  live: boolean // still reasoning (no answer text yet)
  startedAt?: number | null
  ms?: number | null
}) {
  const [open, setOpen] = useState(false)
  const [tick, setTick] = useState(0)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!live) return
    const still = reduceMotion()
    const id = setInterval(() => {
      if (!still) setTick((t) => t + 1)
      setNow(Date.now())
    }, 120)
    return () => clearInterval(id)
  }, [live])

  const elapsed = live ? (startedAt ? now - startedAt : 0) : (ms ?? 0)
  const lastLine = text.trim().split('\n').filter(Boolean).at(-1) ?? ''

  return (
    <div className="mb-3 font-sans">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="group flex items-center gap-2 rounded-md py-0.5 pr-1.5 text-[13.5px] text-muted hover:text-fg"
      >
        <span aria-hidden className={`w-3.5 text-center text-[15px] leading-none ${live ? 'text-accent' : 'text-accent/70'}`}>
          {live ? GLYPHS[tick % GLYPHS.length] : '✻'}
        </span>
        <span className={live ? 'ad-shimmer' : undefined}>{live ? 'Thinking' : 'Thought'}</span>
        <span className="tabular-nums">{live ? formatSeconds(elapsed) : `for ${formatSeconds(elapsed)}`}</span>
        <ChevronRight size={14} className={`transition-transform duration-150 motion-reduce:transition-none ${open ? 'rotate-90' : ''}`} />
      </button>
      {live && !open && lastLine && (
        <p className="ml-[22px] mt-0.5 line-clamp-1 text-[13px] italic text-muted/80">{lastLine}</p>
      )}
      {open && (
        <div className="ml-[7px] mt-1.5 border-l border-line pl-4">
          <div className="max-h-80 space-y-2 overflow-y-auto pr-2 text-[13.5px] leading-[22px] text-muted">
            <Reasoning text={text} />
          </div>
          <p className="mt-2.5 text-[12px] leading-[18px] text-muted/70">
            The model’s reasoning summary. Only the answer below is checked against the document.
          </p>
        </div>
      )}
    </div>
  )
}

/** Gemini summaries use light markdown: "**Heading**" lines and inline **bold**. Render just that, as text. */
function Reasoning({ text }: { text: string }) {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p, i) => {
      const heading = p.match(/^\*\*(.+?)\*\*$/)
      if (heading) return <p key={i} className="font-medium text-fg/80">{heading[1]}</p>
      return (
        <p key={i} className="whitespace-pre-wrap">
          {p.split(/(\*\*[^*]+\*\*)/).map((part, j) =>
            part.startsWith('**') && part.endsWith('**') ? <strong key={j} className="font-medium text-fg/80">{part.slice(2, -2)}</strong> : part,
          )}
        </p>
      )
    })
}
