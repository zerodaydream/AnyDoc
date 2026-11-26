import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, FileText, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type DocumentOut, type MessageOut, type SessionOut } from '../../lib/api'
import { postSse } from '../../lib/sse'
import { useUi } from '../../stores/ui'
import { applyEvent, numbered, startAnswer, stopAnswer, type LiveAnswer } from './answerReducer'
import { AssistantMessage } from './AssistantMessage'
import { ModelControls } from './ModelControls'
import { useModelChoice } from './modelChoice'
import { starterQuestions } from './starters'

export function ChatPanel({ session, doc }: { session: SessionOut; doc: DocumentOut }) {
  const qc = useQueryClient()
  const ready = doc.status === 'ready'
  const history = useQuery({ queryKey: ['messages', session.id], queryFn: () => api.messages(session.id), enabled: ready })
  const outline = useQuery({ queryKey: ['outline', doc.id], queryFn: () => api.outline(doc.id), enabled: ready, staleTime: Infinity })
  const [live, setLive] = useState<LiveAnswer | null>(null)
  const [draft, setDraft] = useState('')
  const abort = useRef<AbortController | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const activate = useUi((s) => s.activate)
  const busy = live?.status === 'streaming'
  const choice = useModelChoice()

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' }) // newer Chromium returns a Promise: never return it as cleanup
  }, [history.data, live])
  useEffect(() => () => abort.current?.abort(), [session.id])

  async function ask(question: string) {
    const q = question.trim()
    if (!q || busy || !ready) return
    setDraft('')
    setLive(startAnswer(q))
    abort.current = new AbortController()
    try {
      const body = { question: q, model: choice.current?.id, thinking: choice.level }
      await postSse(`/api/sessions/${session.id}/messages`, body, (e) => setLive((a) => (a ? applyEvent(a, e) : a)), abort.current.signal)
    } catch (err) {
      if ((err as Error).name === 'AbortError') setLive((a) => a && stopAnswer(a))
      else setLive((a) => a && { ...a, status: 'error', error: 'Connection lost. Try again.' })
    }
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['messages', session.id] }),
      qc.invalidateQueries({ queryKey: ['sessions'] }), // title + recency
    ])
    // Hand over to history once the server has the answer; otherwise keep the local one (error, or a stop that
    // happened before the server started answering).
    const saved = qc.getQueryData<MessageOut[]>(['messages', session.id]) ?? []
    setLive((a) => (!a || saved.some((m) => m.id === a.id) ? null : a.status === 'error' || a.status === 'stopped' ? a : null))
  }

  // Keyboard: "/" focuses the composer, "[" / "]" step through the latest answer's citations.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea, [contenteditable]')) return
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
  const showLive = live && !(live.id && messages.some((m) => m.id === live.id))
  // The question is saved as soon as it's asked: never show it twice once history has it.
  const lastMsg = messages.at(-1)
  const questionSaved =
    !!live &&
    (messages.some((m) => m.id === live.userMessageId) || (lastMsg?.role === 'user' && lastMsg.content === live.question))
  const empty = ready && history.isSuccess && messages.length === 0 && !live
  const starters = starterQuestions(outline.data ?? [])

  return (
    <section className="flex h-full min-w-0 flex-col bg-bg" aria-label="Conversation">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-[70ch] flex-col gap-7 px-6 pb-8 pt-6">
          {empty && (
            <div className="pt-[12vh]">
              <span className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-[13px] text-muted">
                <FileText size={14} className="text-accent" />
                {doc.title}
                {doc.extent && `, ${doc.extent}`}
              </span>
              <p className="mt-5 font-serif text-[28px] leading-[36px] tracking-[-0.01em] text-fg">What would you like to know?</p>
              <p className="mt-2 text-muted">Answers quote the document and link to the exact passage.</p>
              {starters.length > 0 && (
                <div className="mt-8">
                  <p className="text-[13px] text-muted">Or start with a section</p>
                  <ul className="mt-2 divide-y divide-line border-y border-line">
                    {starters.map((s) => (
                      <li key={s.label}>
                        <button
                          onClick={() => void ask(s.question)}
                          aria-label={s.question}
                          className="group flex w-full items-baseline gap-3 px-1 py-2.5 text-left hover:bg-surface/50"
                        >
                          <span className="min-w-0 flex-1 truncate font-serif text-[16px] text-fg group-hover:text-accent">{s.label}</span>
                          <span className="shrink-0 text-[12px] tabular-nums text-muted">{s.ref}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
          {messages.map((m) =>
            m.role === 'user' ? (
              <UserBubble key={m.id} text={m.content} />
            ) : (
              <AssistantMessage key={m.id} id={m.id} segments={m.segments} status={m.status} reasoning={m.reasoning} thinkingMs={m.thinking_ms} />
            ),
          )}
          {showLive && live && !questionSaved && <UserBubble text={live.question} />}
          {showLive && live && (
            <AssistantMessage
              id={live.id ?? 'live'}
              segments={live.segments}
              status={live.status}
              closest={live.closest}
              error={live.error}
              route={live.route}
              blocks={live.blocks}
              reasoning={live.reasoning}
              thinkingStartedAt={live.thinkingStartedAt}
              thinkingMs={live.thinkingMs}
            />
          )}
          <div ref={end} />
        </div>
      </div>
      <form
        className="mx-auto w-full max-w-[70ch] px-4 pb-4"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(draft)
        }}
      >
        <div className="rounded-2xl border border-line bg-surface px-3 pb-2.5 pt-3 transition-colors">
          <textarea
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                void ask(draft)
              }
            }}
            rows={1}
            maxLength={choice.maxChars}
            disabled={!ready}
            placeholder={ready ? 'Ask about this document' : 'Available once the document is ready'}
            aria-label="Ask about this document"
            className="block max-h-48 min-h-7 w-full resize-none bg-transparent px-1 text-[15px] leading-6 text-fg outline-none [field-sizing:content] placeholder:text-muted disabled:cursor-not-allowed"
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5 truncate pl-1 text-[12px] text-muted">
              <FileText size={13} className="shrink-0" />
              <span className="truncate">{doc.title}</span>
            </span>
            <span className="ml-auto flex shrink-0 items-center gap-1">
              <ModelControls />
              <span
                className={`px-1 text-[12px] tabular-nums ${draft.length > choice.maxChars * 0.9 ? 'text-warn' : 'text-muted/80'}`}
                aria-label={`${draft.length} of ${choice.maxChars} characters`}
                title="Characters used of the question limit"
              >
                {draft.length.toLocaleString()} / {choice.maxChars.toLocaleString()}
              </span>
            </span>
            {busy ? (
              <button type="button" onClick={() => abort.current?.abort()} aria-label="Stop answering" className="grid size-8 shrink-0 place-items-center rounded-lg bg-line text-fg hover:bg-muted/30">
                <Square size={12} fill="currentColor" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!ready || !draft.trim()}
                aria-label="Send"
                className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent text-on-accent hover:bg-accent-strong disabled:bg-line disabled:text-muted"
              >
                <ArrowUp size={17} strokeWidth={2.25} />
              </button>
            )}
          </div>
        </div>
      </form>
    </section>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface px-4 py-2.5 text-[15px] leading-6 text-fg">{text}</p>
    </div>
  )
}
