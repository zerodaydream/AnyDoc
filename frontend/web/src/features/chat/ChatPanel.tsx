import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type DocumentOut } from '../../lib/api'
import { postSse } from '../../lib/sse'
import { useUi } from '../../stores/ui'
import { applyEvent, numbered, startAnswer, type LiveAnswer } from './answerReducer'
import { AssistantMessage } from './AssistantMessage'

export function ChatPanel({ doc }: { doc: DocumentOut }) {
  const qc = useQueryClient()
  const history = useQuery({ queryKey: ['messages', doc.id], queryFn: () => api.messages(doc.id), enabled: doc.status === 'ready' })
  const [live, setLive] = useState<LiveAnswer | null>(null)
  const [draft, setDraft] = useState('')
  const abort = useRef<AbortController | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const activate = useUi((s) => s.activate)

  const ready = doc.status === 'ready'
  const busy = live?.status === 'streaming'

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' }) // newer Chromium returns a Promise: never return it as cleanup
  }, [history.data, live])
  useEffect(() => () => abort.current?.abort(), [doc.id])

  async function ask(question: string) {
    const q = question.trim()
    if (!q || busy || !ready) return
    setDraft('')
    setLive(startAnswer(q))
    abort.current = new AbortController()
    try {
      await postSse(`/api/documents/${doc.id}/messages`, { question: q }, (e) => setLive((a) => (a ? applyEvent(a, e) : a)), abort.current.signal)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setLive((a) => a && { ...a, status: 'error', error: 'Connection lost. Try again.' })
    }
    await qc.invalidateQueries({ queryKey: ['messages', doc.id] })
    setLive((a) => (a && a.status !== 'streaming' && a.status !== 'error' ? null : a))
  }

  // Keyboard: "/" focuses the composer, "[" / "]" step through the latest answer's citations.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, [contenteditable]')) return
      if (e.key === '/') {
        e.preventDefault()
        input.current?.focus()
        return
      }
      if (e.key !== '[' && e.key !== ']') return
      const last = [...(history.data ?? [])].reverse().find((m) => m.role === 'assistant' && m.segments.some((s) => s.citations.length))
      if (!last) return
      const cites = numbered(last.segments).flatMap((s) => s.numbered)
      const cur = useUi.getState().active
      const idx = cur?.key.startsWith(`${last.id}:`) ? cur.n - 1 : -1
      const next = cites[(idx + (e.key === ']' ? 1 : -1) + cites.length) % cites.length]
      if (next) activate(`${last.id}:${next.n}`, next.n, next.c)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [history.data, activate])

  const messages = history.data ?? []
  // Once history holds the streamed answer (same id), stop rendering the live copy.
  const showLive = live && !(live.id && messages.some((m) => m.id === live.id))

  return (
    <section className="flex h-full min-w-0 flex-col bg-bg" aria-label="Chat">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[68ch] flex-col gap-6 px-5 py-6">
          {ready && messages.length === 0 && !live && (
            <div className="pt-[18vh] text-muted">
              <p className="font-serif text-[24px] leading-8 text-fg">Ask anything about {doc.title}.</p>
              <p className="mt-2">Every answer links to the exact place in the document it came from.</p>
            </div>
          )}
          {messages.map((m) =>
            m.role === 'user' ? (
              <p key={m.id} className="self-start rounded-lg bg-surface px-3 py-2 text-fg">
                {m.content}
              </p>
            ) : (
              <AssistantMessage key={m.id} id={m.id} segments={m.segments} status={m.status} />
            ),
          )}
          {showLive && live && (
            <p className="self-start rounded-lg bg-surface px-3 py-2 text-fg">{live.question}</p>
          )}
          {showLive && live && (
            <AssistantMessage
              id={live.id ?? 'live'}
              segments={live.segments}
              status={live.status}
              closest={live.closest}
              error={live.error}
            />
          )}
          <div ref={end} />
        </div>
      </div>
      <form
        className="mx-auto w-full max-w-[68ch] px-4 pb-4"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(draft)
        }}
      >
        <div className="flex items-end gap-2 rounded-xl border border-line bg-surface p-2 focus-within:border-accent">
          <textarea
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void ask(draft)
              }
            }}
            rows={1}
            maxLength={4000}
            disabled={!ready}
            placeholder={ready ? 'Ask about this document' : 'Available once the document is ready'}
            aria-label="Ask about this document"
            className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] text-fg outline-none [field-sizing:content] placeholder:text-muted disabled:cursor-not-allowed"
          />
          {busy ? (
            <button type="button" onClick={() => abort.current?.abort()} aria-label="Stop" className="grid size-9 place-items-center rounded-lg bg-line text-fg">
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!ready || !draft.trim()}
              aria-label="Send"
              className="grid size-9 place-items-center rounded-lg bg-accent text-on-accent hover:bg-accent-strong disabled:opacity-40"
            >
              <ArrowUp size={18} />
            </button>
          )}
        </div>
      </form>
    </section>
  )
}
