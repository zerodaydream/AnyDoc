import { CircleAlert, ChevronDown, Lightbulb, Square } from 'lucide-react'
import { useState } from 'react'
import { LogoMark, type MarkState } from '../../components/Logo'
import type { AnswerStatus, Citation, Closest, Segment, WebResult } from '../../lib/api'
import { CitationMark, SourceQuote } from '../citations/Citations'
import { numbered, type LiveAnswer } from './answerReducer'
import { ThinkingBlock } from './ThinkingBlock'
import { WaitingLine } from './WaitingLine'
import { WebAnswer } from './WebAnswer'

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
  web?: WebResult | null
  webSearching?: string | null
  thinkingStartedAt?: number | null
  thinkingMs?: number | null
  live?: boolean // the answer to a question just asked: the mark draws itself in
}

const toCitation = (c: Closest): Citation => ({ ...c, match: 'exact', score: 0, flags: [] })

/** What to say when the document has no answer: plainly, and what happens next (web search, nearby passages). */
function abstainText(webSearching: string | null | undefined, web: WebResult | null | undefined): string {
  const missed = 'I couldn’t find an answer to this in your document'
  if (webSearching && !web) return `${missed}, so I’m checking the web as well.`
  if (web) return `${missed}, so I checked the web as well.`
  return `${missed}. Asking it in other words may help.`
}
const SHOWN = 3

export function AssistantMessage({ id, segments, status, closest = [], error, reasoning, suggestion, web, webSearching, thinkingStartedAt, thinkingMs, live = false }: Props) {
  const [expanded, setExpanded] = useState(false)
  const streaming = status === 'streaming'
  const segs = numbered(segments)
  const sources = segs.flatMap((s) => (s.retracted ? [] : s.numbered))
  const hasText = segs.some((s) => s.text && !s.retracted)
  const webStarted = !!(webSearching || web)
  // The server only searches the web after the document answer is final, so an empty answer then is an abstention.
  const abstained = status === 'insufficient_evidence' || (webStarted && !hasText)
  const waiting = streaming && !segs.some((s) => s.text) && !webStarted
  const thinkingLive = streaming && !!reasoning && thinkingMs == null
  const answering = segs.some((s) => s.text) && !webSearching
  const mark: MarkState = !streaming ? 'idle' : answering ? 'streaming' : 'thinking'

  return (
    <div className="flex gap-3.5">
      {/* Claude-style: the AnyDoc mark sits beside the answer and moves while it works. */}
      <LogoMark size={32} state={mark} enter={live} className="-mt-0.5" />
      <article className="min-w-0 flex-1 font-serif text-[17px] leading-[29px] text-fg" aria-busy={streaming}>
        {reasoning && <ThinkingBlock text={reasoning} live={thinkingLive} startedAt={thinkingStartedAt} ms={thinkingMs} />}
        {waiting && !reasoning && <WaitingLine />}

        {abstained && !hasText ? (
          <p>{abstainText(webSearching, web)}</p>
        ) : (
          !waiting &&
          (hasText || !error) && (
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
          // Sits on the mark's first line when nothing else was said, so the reply reads as a reply.
          <p role="alert" className={`flex gap-2 font-sans text-[15px] leading-6 text-fg/90 ${hasText ? 'mt-2' : 'pt-[3px]'}`}>
            <CircleAlert size={16} className="mt-1 shrink-0 text-danger" aria-hidden />
            <span>{error}</span>
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

        <WebAnswer web={web} searching={webSearching} />

        {abstained && closest.length > 0 && (
          <div className="mt-3 font-sans">
            <p className="mb-1 text-[13px] text-muted">Closest passages I checked:</p>
            {closest.map((c, i) => (
              <SourceQuote key={c.block_id} id={`${id}:closest`} n={i + 1} citation={toCitation(c)} />
            ))}
          </div>
        )}
      </article>
    </div>
  )
}
