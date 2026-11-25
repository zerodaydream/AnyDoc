export type SseEvent = { event: string; data: unknown }

/** Incremental SSE parser: feed text chunks, get complete events. Handles frames split across chunks. */
export function createSseParser() {
  let buf = ''
  return (chunk: string): SseEvent[] => {
    buf += chunk.replace(/\r\n/g, '\n')
    const out: SseEvent[] = []
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i)
      buf = buf.slice(i + 2)
      let event = 'message'
      const data: string[] = []
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
      }
      if (data.length) out.push({ event, data: JSON.parse(data.join('\n')) })
    }
    return out
  }
}

/** POST and stream server-sent events (EventSource can't POST). */
export async function postSse(url: string, body: unknown, onEvent: (e: SseEvent) => void, signal?: AbortSignal) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => null)
    onEvent({ event: 'error', data: err?.error ?? { code: `http_${res.status}`, message: 'Request failed.' } })
    return
  }
  const parse = createSseParser()
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    for (const e of parse(value)) onEvent(e)
  }
}
