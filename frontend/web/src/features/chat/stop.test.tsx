import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentOut, MessageOut, SessionOut } from '../../lib/api'
import { ChatPanel } from './ChatPanel'

const session: SessionOut = {
  id: 's1',
  title: null,
  document_id: 'd1',
  document_title: 'notes',
  document_status: 'ready',
  created_at: '2026-11-26T00:00:00Z',
  updated_at: '2026-11-26T00:00:00Z',
}
const doc = { id: 'd1', title: 'notes', status: 'ready', extent: '4 lines', format: 'markdown' } as DocumentOut
const msg = (id: string, role: 'user' | 'assistant', content: string, status: string): MessageOut => ({
  id,
  role,
  content,
  status,
  segments: [],
  reasoning: null,
  model: null,
  thinking_level: null,
  thinking_ms: null,
  created_at: '2026-11-26T00:00:00Z',
})
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })

Element.prototype.scrollIntoView = vi.fn() // jsdom has no layout
afterEach(() => vi.unstubAllGlobals())

describe('stopping an answer', () => {
  it('ends cleanly: one question bubble, a stopped note, and the composer is ready again', async () => {
    let history: MessageOut[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/messages') && init?.method === 'POST') {
          // Server saves the question, sends meta, starts streaming text, then hangs until the reader stops.
          history = [msg('u1', 'user', 'What is the grid?', 'complete')]
          const enc = new TextEncoder()
          const stream = new ReadableStream<Uint8Array>({
            start(c) {
              c.enqueue(enc.encode('event: meta\ndata: {"message_id":"a1","user_message_id":"u1","route":"full_context","blocks":3}\n\n'))
              c.enqueue(enc.encode('event: text_delta\ndata: {"segment":0,"text":"Unverified half"}\n\n'))
              init.signal?.addEventListener('abort', () => {
                history = [...history, msg('a1', 'assistant', '', 'stopped')]
                c.error(new DOMException('The operation was aborted.', 'AbortError'))
              })
            },
          })
          return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
        }
        if (url.endsWith('/messages')) return json(history)
        if (url.includes('/outline')) return json([])
        if (url.endsWith('/api/models')) return json({ models: [], default_model: 'm', thinking_levels: [], default_thinking: 'off', max_question_chars: 4000 })
        return json([])
      }),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ChatPanel session={session} doc={doc} />
      </QueryClientProvider>,
    )
    const box = await screen.findByRole('textbox', { name: 'Ask about this document' })
    await user.type(box, 'What is the grid?{Enter}')
    await waitFor(() => expect(screen.getByRole('article')).toHaveTextContent('Unverified half'))

    await user.click(screen.getByRole('button', { name: 'Stop answering' }))
    await screen.findByText('Response stopped.')
    await waitFor(() => expect(screen.getAllByText('What is the grid?')).toHaveLength(1))
    expect(screen.getByRole('article')).not.toHaveTextContent('Unverified half')
    expect(screen.queryByText(/Reading the whole document/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
    expect(box).toHaveValue('')
  })
})
