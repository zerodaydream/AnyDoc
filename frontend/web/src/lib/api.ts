// Types mirror backend/api/*.py. Locations come from the backend IR only.

export type Rect = [number, number, number, number] // PDF user space, origin bottom-left
export type PdfLocation = {
  kind: 'pdf'
  regions: { page: number; rects: Rect[] }[]
  char_start?: number | null
  char_end?: number | null
}
/** Code-point offsets into the decoded, newline-normalised text; lines 1-based inclusive. */
export type TextRegion = { char_start: number; char_end: number; line_start: number; line_end: number }
export type TextLocation = { kind: 'text'; regions: TextRegion[] }
export type SourceLocation = PdfLocation | TextLocation

/** Where a citation is, in words: the backend's `ref` ("lines 12–14"); older messages only have a page. */
export function whereLabel(c: { ref?: string | null; page?: number | null }, capital = false): string {
  const s = c.ref ?? (c.page != null ? `page ${c.page}` : '')
  return capital ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

export type Citation = {
  block_id: string
  quote: string
  page: number | null
  ref?: string // absent on messages stored before TXT/MD support
  location: SourceLocation
  match: 'exact' | 'normalized' | 'fuzzy'
  score: number
  flags: string[]
}

export type DocStatus =
  | 'pending' | 'uploading' | 'uploaded' | 'validating' | 'queued'
  | 'processing' | 'indexing' | 'ready' | 'failed' | 'cancelled'

export type DocumentOut = {
  id: string
  title: string
  filename: string
  format: string | null
  size_bytes: number
  page_count: number | null
  extent: string | null // "15 pages", "1,240 lines"
  version: number
  status: DocStatus
  progress: number
  stage_detail: string | null
  error: { code: string; message: string } | null
  file_url: string
  created_at: string
}

export type Segment = { text: string; citations: Citation[]; retracted?: string }
export type AnswerStatus = 'answered' | 'partial' | 'insufficient_evidence' | 'conflicting_evidence' | 'error' | 'stopped'
export type Closest = { block_id: string; page: number | null; ref?: string; quote: string; location: SourceLocation }

export type MessageOut = {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: string
  segments: Segment[]
  reasoning: string | null
  model: string | null
  thinking_level: string | null
  thinking_ms: number | null
  created_at: string
}

export type ModelInfo = {
  id: string
  name: string
  input_token_limit: number | null
  output_token_limit: number | null
  thinking: boolean
  available: boolean
  thinking_levels: string[] // levels this model accepts ([] when it doesn't think)
  default_thinking: string | null
}

export type ModelsOut = {
  models: ModelInfo[]
  default_model: string
  thinking_levels: string[]
  default_thinking: string
  max_question_chars: number
}

export type SessionOut = {
  id: string
  title: string | null
  document_id: string
  document_title: string
  document_status: DocStatus
  created_at: string
  updated_at: string
}

export type OutlineItem = { block_id: string; text: string; page: number | null; ref: string; location: SourceLocation }
export type FormatInfo = { name: string; label: string; extensions: string[] }

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(body?.error?.code ?? `http_${res.status}`, body?.error?.message ?? `Request failed (${res.status}).`)
  }
  return res.json() as Promise<T>
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export const api = {
  listDocuments: () => fetch('/api/documents').then(json<DocumentOut[]>),
  getDocument: (id: string) => fetch(`/api/documents/${id}`).then(json<DocumentOut>),
  models: () => fetch('/api/models').then(json<ModelsOut>),
  formats: () => fetch('/api/formats').then(json<FormatInfo[]>),
  outline: (id: string) => fetch(`/api/documents/${id}/outline`).then(json<OutlineItem[]>),
  sessions: () => fetch('/api/sessions').then(json<SessionOut[]>),
  createSession: (documentId: string) =>
    fetch('/api/sessions', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ document_id: documentId }) }).then(
      json<SessionOut>,
    ),
  renameSession: (id: string, title: string) =>
    fetch(`/api/sessions/${id}`, { method: 'PATCH', headers: JSON_HEADERS, body: JSON.stringify({ title }) }).then(json<SessionOut>),
  deleteSession: async (id: string) => {
    const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' })
    if (!res.ok && res.status !== 404) throw new ApiError(`http_${res.status}`, 'Could not delete the conversation.')
  },
  messages: (sessionId: string) => fetch(`/api/sessions/${sessionId}/messages`).then(json<MessageOut[]>),
  upload: (file: File) =>
    fetch(`/api/documents?filename=${encodeURIComponent(file.name)}`, {
      method: 'POST',
      body: file,
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
    }).then(json<DocumentOut>),
  cancel: (id: string) => fetch(`/api/documents/${id}/cancel`, { method: 'POST' }).then(json<DocumentOut>),
  retry: (id: string) => fetch(`/api/documents/${id}/retry`, { method: 'POST' }).then(json<DocumentOut>),
}

export const TERMINAL: DocStatus[] = ['ready', 'failed', 'cancelled']
