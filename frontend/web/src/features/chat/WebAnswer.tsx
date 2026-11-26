import { Globe } from 'lucide-react'
import type { WebResult } from '../../lib/api'

/**
 * Web lookup shown under a document answer. Kept visibly apart: it is not from the document and never uses the
 * document's citation pills. Only text the search grounding attributed to a source arrives here.
 */
export function WebAnswer({ web, searching }: { web?: WebResult | null; searching?: string | null }) {
  if (!web && !searching) return null
  return (
    <section aria-label="From the web" className="mt-4 rounded-xl border border-line px-4 py-3 font-sans">
      <header className="flex items-center gap-2 text-[13px] text-muted">
        <Globe size={14} className="text-accent" aria-hidden />
        <span className="font-medium text-fg">From the web</span>
        <span>· not from your document</span>
      </header>

      {!web ? (
        <p className="mt-2 flex items-center gap-2.5 text-[14px] text-muted" aria-live="polite">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent/60 motion-reduce:animate-none" />
            <span className="relative inline-flex size-2 rounded-full bg-accent" />
          </span>
          Searching the web for “{searching}”…
        </p>
      ) : web.status === 'answered' ? (
        <>
          <p className="mt-2 font-serif text-[16px] leading-[27px] text-fg">
            {web.segments.map((s, i) => (
              <span key={i}>
                {s.text}
                {s.sources.map((n) => (
                  <a
                    key={n}
                    href={web.sources[n]?.uri}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                    title={web.sources[n]?.title}
                    className="ml-0.5 align-super font-sans text-[10px] font-semibold text-accent hover:underline"
                  >
                    {n + 1}
                  </a>
                ))}{' '}
              </span>
            ))}
          </p>
          <ol className="mt-2 space-y-0.5 text-[12px] text-muted">
            {web.sources.map((src, n) =>
              web.segments.some((s) => s.sources.includes(n)) ? (
                <li key={n} className="flex gap-1.5">
                  <span className="tabular-nums">{n + 1}.</span>
                  <a href={src.uri} target="_blank" rel="noopener noreferrer nofollow" className="truncate hover:text-fg hover:underline">
                    {src.title}
                    {src.domain && src.domain !== src.title ? ` · ${src.domain}` : ''}
                  </a>
                </li>
              ) : null,
            )}
          </ol>
          {web.entry_html && <SearchChip html={web.entry_html} />}
        </>
      ) : (
        <p className="mt-2 text-[14px] text-muted">
          {web.status === 'not_found'
            ? 'Couldn’t find a reliable answer on the web.'
            : (web.note ?? 'Web search is unavailable right now.')}
        </p>
      )}
    </section>
  )
}

/**
 * Google's search-suggestion chip, which must accompany grounded results. It is third-party HTML, so it runs in a
 * sandboxed frame: no scripts, no access to the app; its links open in a new tab.
 */
function SearchChip({ html }: { html: string }) {
  return (
    <iframe
      title="Google Search suggestions"
      sandbox="allow-popups allow-popups-to-escape-sandbox"
      srcDoc={`<!doctype html><base target="_blank"><body style="margin:0">${html}</body>`}
      className="mt-2 h-[52px] w-full border-0"
    />
  )
}
