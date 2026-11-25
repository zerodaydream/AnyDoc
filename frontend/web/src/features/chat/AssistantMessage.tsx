import type { AnswerStatus, Citation, Closest, Segment } from '../../lib/api'
import { CitationMark, EvidenceRow } from '../citations/Citations'
import { numbered } from './answerReducer'

type Props = {
  id: string
  segments: Segment[]
  status: AnswerStatus | 'streaming' | string
  closest?: Closest[]
  error?: string | null
}

const toCitation = (c: Closest): Citation => ({ ...c, match: 'exact', score: 0, flags: [] })

export function AssistantMessage({ id, segments, status, closest = [], error }: Props) {
  const streaming = status === 'streaming'
  const segs = numbered(segments)
  const all = segs.flatMap((s) => (s.retracted ? [] : s.numbered))
  const abstained = status === 'insufficient_evidence'

  return (
    <article className="font-serif text-[17px] leading-7 text-fg" aria-busy={streaming}>
      {abstained && !segs.some((s) => s.text && !s.retracted) ? (
        <p>The document doesn’t say.</p>
      ) : (
        <p className={streaming ? 'ad-caret' : undefined}>
          {segs.map((s, i) =>
            s.retracted ? (
              <span key={i} className="text-muted line-through decoration-1" title="Removed: couldn't verify against the document.">
                {s.text}{' '}
              </span>
            ) : (
              <span key={i}>
                {s.text}
                {s.numbered.map(({ n, c }) => (
                  <CitationMark key={n} id={id} n={n} citation={c} />
                ))}{' '}
              </span>
            ),
          )}
        </p>
      )}
      {segs.some((s) => s.retracted) && !streaming && (
        <p className="mt-1 font-sans text-[13px] text-muted">Struck-through text was removed: it couldn’t be verified against the document.</p>
      )}
      {error && (
        <p role="alert" className="mt-2 font-sans text-[14px] text-danger">
          {error}
        </p>
      )}
      {all.length > 0 && (
        <div className="mt-2 font-sans text-[13px]">
          {all.map(({ n, c }) => (
            <EvidenceRow key={n} id={id} n={n} citation={c} />
          ))}
        </div>
      )}
      {abstained && closest.length > 0 && (
        <div className="mt-2 font-sans text-[13px]">
          <p className="px-2 pb-1 text-muted">Closest passages checked:</p>
          {closest.map((c, i) => (
            <EvidenceRow key={c.block_id} id={`${id}:closest`} n={i + 1} citation={toCitation(c)} />
          ))}
        </div>
      )}
    </article>
  )
}
