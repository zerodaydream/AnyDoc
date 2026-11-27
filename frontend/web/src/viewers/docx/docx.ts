/**
 * DOCX rendering with docx-preview, tied to the backend IR by paragraph order.
 *
 * The backend numbers every `w:p` the viewer renders, in document order (DocxRegion.para). docx-preview renders each
 * as one `<p>` inside the page `<article>`; with `breakPages: false` it never splits a paragraph. Text-box paragraphs
 * nest inside another `<p>` and headers/footers/notes live outside the article, so neither is counted.
 *
 * The rendered file is untrusted: links keep only http(s)/mailto targets, images only the blob/data URLs the
 * renderer made from the package itself (no remote fetches), and embedded objects (alt chunks) are not rendered.
 */
import type { Options } from 'docx-preview'

export const RENDER_OPTIONS: Partial<Options> = {
  className: 'docx',
  inWrapper: true,
  breakPages: false, // a page break would split a paragraph into two <p>s
  ignoreLastRenderedPageBreak: true,
  ignoreFonts: true, // embedded fonts are not loaded
  renderHeaders: true,
  renderFooters: true,
  renderFootnotes: true,
  renderEndnotes: true,
  renderComments: false,
  renderChanges: false, // deleted text hidden, insertions shown as plain text (as the backend reads it)
  renderAltChunks: false,
  useBase64URL: false,
  experimental: false,
}

/** Every rendered body paragraph, in the backend's order: anchors[i] is DocxRegion.para === i. */
export function paragraphAnchors(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('section.docx > article p')].filter(
    (p) => !p.parentElement?.closest('p'),
  )
}

const SAFE_LINK = /^(https?:|mailto:)/i
const SAFE_IMG = /^(blob:|data:image\/)/i

/** Strip anything that could navigate, run, or fetch from outside the package. */
export function sanitise(root: HTMLElement): void {
  for (const a of root.querySelectorAll('a')) {
    const href = a.getAttribute('href') ?? ''
    if (SAFE_LINK.test(href)) {
      a.target = '_blank'
      a.rel = 'noopener noreferrer nofollow'
    } else {
      if (href) a.title = href
      a.removeAttribute('href')
    }
  }
  for (const img of root.querySelectorAll('img')) {
    if (!SAFE_IMG.test(img.getAttribute('src') ?? '')) img.removeAttribute('src')
  }
  for (const img of root.querySelectorAll('image')) {
    for (const attr of ['href', 'xlink:href']) {
      const v = img.getAttribute(attr)
      if (v && !SAFE_IMG.test(v)) img.removeAttribute(attr)
    }
  }
  root.querySelectorAll('iframe, object, embed, script, link, meta, base, form').forEach((n) => n.remove())
  for (const el of root.querySelectorAll('*')) {
    for (const { name } of [...el.attributes]) if (/^on/i.test(name)) el.removeAttribute(name)
  }
}

/** Text nodes of a paragraph in reading order, skipping nested paragraphs (text boxes) and drawings. */
function* textUnits(p: HTMLElement): Generator<{ node: Text | null; text: string }> {
  const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => {
      if (n === p || n.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT
      const el = n as Element
      if (el.localName === 'p' || el.localName === 'svg' || el.localName === 'img') return NodeFilter.FILTER_REJECT
      return el.localName === 'br' || el.localName === 'wbr' ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
    },
  })
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) yield { node: n as Text, text: (n as Text).data }
    else yield { node: null, text: (n as Element).localName === 'br' ? '\n' : '-' } // <wbr>: non-breaking hyphen
  }
}

/** The paragraph's text as the backend reads it (tabs render as an em space). */
export function paragraphText(p: HTMLElement): string {
  return [...textUnits(p)].map((u) => u.text).join('').replaceAll('\u2003', '\t')
}

/**
 * DOM range for [start, end) of the paragraph's text as the backend counts it (code points). Null when the offsets
 * don't fit what was rendered; the paragraph wash still shows.
 */
export function rangeForOffsets(p: HTMLElement, start: number, end: number): Range | null {
  if (end <= start) return null
  let pos = 0 // in code points
  let from: [Text, number] | null = null
  for (const { node } of textUnits(p)) {
    if (!node) {
      pos += 1 // <br> / <wbr>: one char in the backend's text
      continue
    }
    const cps = [...node.data]
    const at = (cp: number) => cps.slice(0, cp).join('').length // code point -> UTF-16 offset in this node
    if (!from && start < pos + cps.length) from = [node, at(start - pos)]
    if (from && end <= pos + cps.length) {
      const r = document.createRange()
      r.setStart(...from)
      r.setEnd(node, at(end - pos))
      return r.toString().trim() ? r : null
    }
    pos += cps.length
  }
  return null
}
