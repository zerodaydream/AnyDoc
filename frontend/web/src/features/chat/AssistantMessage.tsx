import { ChevronDown, Lightbulb, Square } from 'lucide-react'
import { useState } from 'react'
import type { AnswerStatus, Citation, Closest, Segment } from '../../lib/api'
import { CitationMark, SourceQuote } from '../citations/Citations'
import { numbered, type LiveAnswer } from './answerReducer'
import { ThinkingBlock } from './ThinkingBlock'

type Props = {
  id: string
  segments: Segment[]
  status: AnswerStatus | 'streaming' | string
  closest?: Closest[]
  error?: string | null
  route?: LiveAnswer['route']
  blocks?: number
  reasoning?: string | null
  suggestion?: string | null
  thinkingStartedAt?: number | null
  thinkingMs?: number | null
}

const toCitation = (c: Closest): Citation => ({ ...c, match: 'exact', score: 0, flags: [] })
const SHOWN = 3

export function AssistantMessage({ id, segments, status, closest = [], error, route, blocks = 0, reasoning, suggestion, thinkingStartedAt, thinkingMs }: Props) {
  const [expanded, setExpanded] = useState(false)
  const streaming = status === 'streaming'
  const segs = numbered(segments)
  const sources = segs.flatMap((s) => (s.retracted ? [] : s.numbered))
  const abstained = status === 'insufficient_evidence'
  const hasText = segs.some((s) => s.text && !s.retracted)
  const waiting = streaming && !segs.some((s) => s.text)
  const thinkingLive = streaming && !!reasoning && thinkingMs == null

  return (
    <article className="font-serif text-[17px] leading-[29px] text-fg" aria-busy={streaming}>
      {reasoning && <ThinkingBlock text={reasoning} live={thinkingLive} startedAt={thinkingStartedAt} ms={thinkingMs} />}
      {waiting && !reasoning && (
        <p className="flex items-center gap-2.5 font-sans text-[14px] text-muted" aria-live="polite">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent/60 motion-reduce:animate-none" />
            <span className="relative inline-flex size-2 rounded-full bg-accent" />
          </span>
          {route === 'hybrid'
            ? `Searching the document for the most relevant passages (${blocks} selected)…`
            : route === 'full_context'
              ? `Reading the whole document (${blocks} passages)…`
              : 'Opening the document…'}
        </p>
      )}

      {abstained && !hasText ? (
        <p>The document doesn’t say.</p>
      ) : (
        !waiting && (
          <p className={streaming ? 'ad-caret' : undefined}>
            {segs.map((s, i) =>
              s.retracted ? (
                <span key={i} className="text-muted line-through decoration-muted/60" title="Removed: couldn’t be verified against the document">
                  {s.text}{' '}
                </span>
              ) : (
                <span key={i}>
                  {/* Last word + its pills never wrap apart, so a pill can't look like it starts the next sentence. */}
                  {s.text.slice(0, s.text.trimEnd().lastIndexOf(' ') + 1)}
                  <span className="whitespace-nowrap">
                    {s.text.trimEnd().slice(s.text.trimEnd().lastIndexOf(' ') + 1)}
                    {s.numbered.map(({ n, c }) => (
                      <CitationMark key={n} id={id} n={n} citation={c} />
                    ))}
                  </span>{' '}
                </span>
              ),
            )}
          </p>
        )
      )}

      {segs.some((s) => s.retracted) && !streaming && (
        <p className="mt-2 font-sans text-[13px] text-muted">
          Struck-through text was removed because it couldn’t be verified against the document.
        </p>
      )}
      {status === 'stopped' && (
        <p className={`flex items-center gap-2 font-sans text-[13px] text-muted ${hasText ? 'mt-2' : ''}`}>
          <Square size={10} fill="currentColor" aria-hidden />
          {hasText ? 'Response stopped. Only verified sentences are kept.' : 'Response stopped.'}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 font-sans text-[14px] text-danger">
          {error}
        </p>
      )}

      {sources.length > 0 && !streaming && (
        <div className="mt-3 font-sans">
          {(expanded ? sources : sources.slice(0, SHOWN)).map(({ n, c }) => (
            <SourceQuote key={n} id={id} n={n} citation={c} />
          ))}
          {sources.length > SHOWN && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="ml-2 mt-1 flex items-center gap-1 text-[13px] text-muted hover:text-fg"
            >
              <ChevronDown size={14} className={expanded ? 'rotate-180' : ''} />
              {expanded ? 'Show fewer sources' : `Show all ${sources.length} sources`}
            </button>
          )}
        </div>
      )}

      {suggestion && hasText && !streaming && (
        <p className="mt-3 flex gap-2 font-sans text-[14px] leading-[22px] text-muted">
          <Lightbulb size={15} className="mt-[3px] shrink-0 text-accent" aria-hidden />
          <span>
            <span className="sr-only">Suggestion: </span>
            {suggestion}
          </span>
        </p>
      )}

      {abstained && closest.length > 0 && (
        <div className="mt-3 font-sans">
          <p className="mb-1 text-[13px] text-muted">Closest passages it checked:</p>
          {closest.map((c, i) => (
            <SourceQuote key={c.block_id} id={`${id}:closest`} n={i + 1} citation={toCitation(c)} />
          ))}
        </div>
      )}
    </article>
  )
}
