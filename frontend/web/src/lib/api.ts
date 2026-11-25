// Types mirror backend/api/*.py. Locations come from the backend IR only.

export type Rect = [number, number, number, number] // PDF user space, origin bottom-left
export type PdfLocation = {
  kind: 'pdf'
  regions: { page: number; rects: Rect[] }[]
  char_start?: number | null
  char_end?: number | null
}
export type SourceLocation = PdfLocation

export type Citation = {
  block_id: string
  quote: string
  page: number | null
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
  version: number
  status: DocStatus
  progress: number
  stage_detail: string | null
  error: { code: string; message: string } | null
  file_url: string
  created_at: string
}

export type Segment = { text: string; citations: Citation[]; retracted?: string }
export type AnswerStatus = 'answered' | 'partial' | 'insufficient_evidence' | 'conflicting_evidence' | 'error'
export type Closest = { block_id: string; page: number | null; quote: string; location: SourceLocation }

export type MessageOut = {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: string
  segments: Segment[]
  created_at: string
}

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

export const api = {
  listDocuments: () => fetch('/api/documents').then(json<DocumentOut[]>),
  getDocument: (id: string) => fetch(`/api/documents/${id}`).then(json<DocumentOut>),
  messages: (id: string) => fetch(`/api/documents/${id}/messages`).then(json<MessageOut[]>),
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
