import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleAlert, FileText, Upload } from 'lucide-react'
import { useRef } from 'react'
import { api, type DocumentOut } from '../../lib/api'
import { ago, stamp } from '../../lib/time'
import { useUi } from '../../stores/ui'
import { MAX_MB, useUpload } from './upload'

const when = (d: DocumentOut) => `Added ${stamp(d.created_at)}` + (d.ingested_at ? ` · Ready ${stamp(d.ingested_at)}` : '')

export function Home() {
  const qc = useQueryClient()
  const openSession = useUi((s) => s.openSession)
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments })
  const { take, busy: uploading, error: uploadError, extensions, kinds } = useUpload()
  const picker = useRef<HTMLInputElement>(null)

  const start = useMutation({
    mutationFn: api.createSession,
    onSuccess: async (s) => {
      await qc.invalidateQueries({ queryKey: ['sessions'] })
      openSession(s.id)
    },
  })
  const error = uploadError ?? start.error?.message
  const busy = uploading || start.isPending
  const recent = (docs.data ?? []).filter((d) => d.status === 'ready').slice(0, 50)

  return (
    // The page itself stays put; only the document list scrolls. On a very short window (below min-h) the page
    // scrolls instead, so nothing is ever cut off.
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex h-full min-h-[520px] max-w-[640px] flex-col px-6 pb-8 pt-[14vh]">
        <h1 className="font-serif text-[34px] leading-[42px] tracking-[-0.015em] text-fg">
          Ask your document. See where every answer comes from.
        </h1>
        <p className="mt-3 max-w-[52ch] text-[16px] leading-[26px] text-muted">
          Each answer is checked against the file and pinned to the exact line it quotes. If the document doesn’t say,
          AnyDoc tells you.
        </p>

        {/* Drops are handled app-wide by <FileDrop>: anywhere on screen works, not only this box. */}
        <div className="mt-9 flex items-center gap-4 rounded-2xl border border-dashed border-line bg-bg px-5 py-5">
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-surface text-accent">
            <Upload size={19} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-fg">{uploading ? 'Uploading…' : 'Drop a file anywhere'}</p>
            <p className="text-[13px] text-muted">
              {kinds}, up to {MAX_MB} MB
            </p>
          </div>
          <button
            type="button"
            onClick={() => picker.current?.click()}
            disabled={busy}
            className="h-9 shrink-0 rounded-lg bg-accent px-3.5 font-medium text-on-accent hover:bg-accent-strong disabled:opacity-60"
          >
            Choose file
          </button>
          <input
            ref={picker}
            type="file"
            accept={extensions.join(',')}
            hidden
            onChange={(e) => {
              take(e.target.files)
              e.target.value = '' // picking the same file again still uploads
            }}
          />
        </div>
        {error && (
          <p role="alert" className="mt-3 flex gap-2.5 rounded-xl border border-danger/30 bg-danger/8 px-4 py-3 text-[14px] leading-[22px] text-fg">
            <CircleAlert size={16} className="mt-[3px] shrink-0 text-danger" aria-hidden />
            <span>{error}</span>
          </p>
        )}

        {recent.length > 0 && (
          <section className="mt-12 flex min-h-0 flex-1 flex-col">
            <h2 className="text-[13px] font-medium text-muted">Click to converse with your old document uploads</h2>
            <ul
              aria-label="Your documents"
              className="mt-2 min-h-0 divide-y divide-line overflow-y-auto overscroll-contain border-y border-line [scrollbar-gutter:stable] [scrollbar-width:thin]"
            >
              {recent.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => start.mutate(d.id)}
                    disabled={busy}
                    title={when(d)}
                    className="group flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-surface/50"
                  >
                    <FileText size={17} className="shrink-0 text-muted group-hover:text-accent" />
                    <span className="min-w-0 flex-1 truncate text-fg">{d.title}</span>
                    <span className="shrink-0 text-[13px] tabular-nums text-muted">
                      {d.extent}
                      <span aria-hidden> · </span>
                      <time dateTime={d.created_at} aria-label={when(d)}>
                        {ago(d.created_at)}
                      </time>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
