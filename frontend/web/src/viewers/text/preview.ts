/**
 * Markdown preview. markdown-it is the JS original of the backend's markdown-it-py, so block line maps agree:
 * every rendered block carries `data-ls`/`data-le` (1-based source lines) and citations find their block by line.
 *
 * Uploaded Markdown is untrusted: raw HTML is escaped (html: false), images are never fetched (shown as their alt
 * text, so no tracking pixels), and only http(s)/mailto links stay links (new tab, no referrer).
 */
import MarkdownIt from 'markdown-it'
import type { Token } from 'markdown-it'
import { frontMatterEnd } from './text'

const md = new MarkdownIt('default', { html: false, linkify: false, typographer: false })
const esc = md.utils.escapeHtml

md.core.ruler.push('anydoc_lines_links', (state) => {
  for (const t of state.tokens) {
    if (t.map && t.block && t.nesting >= 0 && t.type !== 'inline') {
      t.attrSet('data-ls', String(t.map[0] + 1))
      t.attrSet('data-le', String(t.map[1]))
    }
    const external: boolean[] = []
    for (const c of t.children ?? []) {
      if (c.type === 'link_open') {
        const ok = /^(https?:|mailto:)/i.test(String(c.attrGet('href') ?? ''))
        external.push(ok)
        if (ok) {
          c.attrSet('target', '_blank')
          c.attrSet('rel', 'noopener noreferrer nofollow')
        } else c.type = 'anydoc_link_open'
      } else if (c.type === 'link_close' && !external.pop()) c.type = 'anydoc_link_close'
    }
  }
})

md.renderer.rules.anydoc_link_open = (tokens: Token[], i: number) =>
  `<span class="ad-md-link" title="${esc(String(tokens[i].attrGet('href') ?? ''))}">`
md.renderer.rules.anydoc_link_close = () => '</span>'
md.renderer.rules.image = (tokens, i, opts, env, self) => {
  const alt = self.renderInlineAsText(tokens[i].children ?? [], opts, env)
  return `<span class="ad-md-img" title="Images aren’t loaded">${esc(alt || 'image')}</span>`
}

export function renderMarkdown(text: string): string {
  const lines = text.split('\n')
  const fm = frontMatterEnd(lines)
  // Blank the front matter (keeps line numbers aligned with the backend) and show it folded instead.
  const body = md.render('\n'.repeat(fm) + lines.slice(fm).join('\n'))
  if (!fm) return body
  const yaml = esc(lines.slice(1, fm - 1).join('\n'))
  return (
    `<details class="ad-md-fm" data-ls="1" data-le="${fm}"><summary>Front matter · ${fm} lines</summary>` +
    `<pre><code>${yaml}</code></pre></details>${body}`
  )
}

/** Innermost rendered blocks whose source lines overlap [from, to]. */
export function blocksForLines(root: HTMLElement, from: number, to: number): HTMLElement[] {
  const hits = [...root.querySelectorAll<HTMLElement>('[data-ls]')].filter(
    (el) => Number(el.dataset.ls) <= to && Number(el.dataset.le) >= from,
  )
  return hits.filter((el) => !hits.some((o) => o !== el && el.contains(o)))
}

/**
 * Elements that get the block wash. A fenced code block's line map sits on its inline `<code>`; washing that paints
 * one strip per line (a file tree looks striped), so the whole `<pre>` is washed as one block instead.
 */
export function washTargets(blocks: HTMLElement[]): HTMLElement[] {
  return [...new Set(blocks.map((b) => b.closest<HTMLElement>('pre') ?? b))]
}

/** First rendered block at or after `line` (blank lines have no block). */
export function blockAtLine(root: HTMLElement, line: number): HTMLElement | null {
  const exact = blocksForLines(root, line, line)
  if (exact.length) return exact[0]
  return [...root.querySelectorAll<HTMLElement>('[data-ls]')].find((el) => Number(el.dataset.ls) >= line) ?? null
}

const WORD = /[\p{L}\p{N}]+/gu

/**
 * DOM range covering `quote` inside `els`, matched word by word so Markdown markers in the source quote
 * (`**`, backticks, `- `) don't matter. Null when the words aren't contiguous in the rendered text.
 */
export function rangeForQuote(els: HTMLElement[], quote: string): Range | null {
  const want = quote.match(WORD) ?? []
  if (!want.length) return null
  const words: { node: Text; start: number; end: number; w: string }[] = []
  for (const el of els) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
      for (const m of n.data.matchAll(WORD)) words.push({ node: n, start: m.index, end: m.index + m[0].length, w: m[0] })
    }
  }
  for (let i = 0; i + want.length <= words.length; i++) {
    if (want.every((w, k) => words[i + k].w === w)) {
      const r = document.createRange()
      r.setStart(words[i].node, words[i].start)
      const last = words[i + want.length - 1]
      r.setEnd(last.node, last.end)
      return r
    }
  }
  return null
}

/** Case-insensitive matches of `query` in the rendered text, as DOM ranges. */
export function findRanges(root: HTMLElement, query: string, cap = 2000): Range[] {
  const q = query.toLowerCase()
  if (!q) return []
  const out: Range[] = []
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  for (let n = walker.nextNode() as Text | null; n && out.length < cap; n = walker.nextNode() as Text | null) {
    const hay = n.data.toLowerCase()
    if (hay.length !== n.data.length) continue
    for (let i = hay.indexOf(q); i !== -1; i = hay.indexOf(q, i + q.length)) {
      const r = document.createRange()
      r.setStart(n, i)
      r.setEnd(n, i + q.length)
      out.push(r)
    }
  }
  return out
}

type HighlightRegistry = { set(name: string, h: unknown): void; delete(name: string): void }
type HighlightCtor = new (...ranges: Range[]) => unknown

/** CSS Custom Highlight API (Chromium, Safari 17.2+, Firefox 140+). No-op elsewhere: block washes still show. */
export function paintRanges(name: string, ranges: Range[]): void {
  const registry = (globalThis.CSS as unknown as { highlights?: HighlightRegistry } | undefined)?.highlights
  const Ctor = (globalThis as unknown as { Highlight?: HighlightCtor }).Highlight
  if (!registry || !Ctor) return
  if (ranges.length) registry.set(name, new Ctor(...ranges))
  else registry.delete(name)
}
