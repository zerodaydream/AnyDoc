import type { AnswerStatus, Citation, Closest, Segment } from '../../lib/api'
import type { SseEvent } from '../../lib/sse'

export type LiveAnswer = {
  id: string | null
  userMessageId: string | null
  question: string
  segments: Segment[]
  status: AnswerStatus | 'streaming'
  closest: Closest[]
  error: string | null
  route: 'full_context' | 'hybrid' | null
  blocks: number
  reasoning: string
  suggestion: string | null
  thinkingStartedAt: number | null
  thinkingMs: number | null
}

export const startAnswer = (question: string): LiveAnswer => ({
  id: null,
  userMessageId: null,
  question,
  segments: [],
  status: 'streaming',
  closest: [],
  error: null,
  route: null,
  blocks: 0,
  reasoning: '',
  suggestion: null,
  thinkingStartedAt: null,
  thinkingMs: null,
})

const seg = (segs: Segment[], i: number): Segment[] => {
  const next = segs.slice()
  while (next.length <= i) next.push({ text: '', citations: [] })
  next[i] = { ...next[i] }
  return next
}

const now = () => Date.now()

/** Pure reducer over the answer SSE protocol (backend/answering/engine.py). */
export function applyEvent(a: LiveAnswer, e: SseEvent): LiveAnswer {
  const d = e.data as Record<string, unknown>
  switch (e.event) {
    case 'meta':
      return {
        ...a,
        id: d.message_id as string,
        userMessageId: (d.user_message_id as string) ?? null,
        route: d.route as LiveAnswer['route'],
        blocks: d.blocks as number,
        // Thinking time runs from the request, not the first summary chunk (often delivered all at once).
        thinkingStartedAt: d.thinking ? now() : null,
      }
    case 'reset':
      return { ...a, segments: [], status: 'streaming', reasoning: '', suggestion: null, thinkingStartedAt: a.thinkingStartedAt && now(), thinkingMs: null }
    case 'thinking_delta':
      return { ...a, reasoning: a.reasoning + (d.text as string), thinkingStartedAt: a.thinkingStartedAt ?? now() }
    case 'text_delta': {
      // First answer text ends the thinking phase.
      if (a.reasoning && a.thinkingStartedAt !== null && a.thinkingMs === null) a = { ...a, thinkingMs: now() - a.thinkingStartedAt }
      const segments = seg(a.segments, d.segment as number)
      segments[d.segment as number].text += d.text as string
      return { ...a, segments }
    }
    case 'citation': {
      const segments = seg(a.segments, d.segment as number)
      const s = segments[d.segment as number]
      s.citations = [...s.citations, d.citation as Citation]
      return { ...a, segments }
    }
    case 'segment_retracted': {
      const segments = seg(a.segments, d.segment as number)
      segments[d.segment as number].retracted = d.reason as string
      return { ...a, segments }
    }
    case 'suggestion':
      return { ...a, suggestion: d.text as string }
    case 'done':
      return { ...a, status: d.status as AnswerStatus, closest: (d.closest as Closest[]) ?? [] }
    case 'error':
      return { ...a, status: 'error', error: (d.message as string) ?? 'Something went wrong.' }
    default:
      return a
  }
}

/** The reader pressed Stop: keep only verified segments (as the server records it), end the stream. */
export function stopAnswer(a: LiveAnswer): LiveAnswer {
  return { ...a, status: 'stopped', suggestion: null, segments: a.segments.filter((s) => s.citations.length && !s.retracted) }
}

/** Citation numbers run across a message's segments: 1, 2, 3... */
export function numbered(segments: Segment[]) {
  let n = 0
  return segments.map((s) => ({ ...s, numbered: s.citations.map((c) => ({ n: ++n, c })) }))
}
