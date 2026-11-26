import { memo, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type { SourceLocation } from '../../lib/api'
import type { Highlight, ViewerMode, ViewerProps } from '../core/contract'
import { blockAtLine, blocksForLines, findRanges, paintRanges, rangeForQuote, renderMarkdown } from './preview'
import {
  codePointIndex,
  decodeText,
  findAll,
  lineOf,
  lineStarts,
  markdownLineKinds,
  marksByLine,
  pieces,
  type LineKind,
  type LineMark,
  type Mark,
} from './text'

const GROUP = 200 // lines per lazily rendered group
const EAGER_GROUPS = 10 // documents up to 2,000 lines render at once
const LINE_PX = { text: 22, markdown: 27 } // at 100%: placeholder height estimate only

type Doc = { text: string; lines: string[]; starts: number[]; toUnit: (cp: number) => number; kinds: LineKind[] }

const textRegions = (l: SourceLocation) => (l.kind === 'text' ? l.regions : [])

const MODES: ViewerMode[] = [
  { id: 'preview', label: 'Preview' },
  { id: 'source', label: 'Markdown' },
]
const MODE_KEY = 'anydoc.markdownView'
type Mode = 'preview' | 'source'
const savedMode = (): Mode => (localStorage.getItem(MODE_KEY) === 'source' ? 'source' : 'preview')

/** Scroll `el` so it sits ~30% down the container, as the PDF viewer places evidence. */
function placeAt(container: HTMLElement, el: Pick<Element, "getBoundingClientRect">) {
  const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
  container.scrollTop = Math.max(0, top - container.clientHeight * 0.3)
}

export default function TextViewer({ src, format, ref, onState }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<Doc | null>(null)
  const [evidence, setEvidence] = useState<Mark[]>([])
  const [hl, setHl] = useState<Highlight[]>([])
  const [previewFind, setPreviewFind] = useState<{ query: string; step: number } | null>(null)
  const [find, setFind] = useState<{ query: string; hits: number[]; i: number } | null>(null)
  const [scale, setScale] = useState(1)
  const [target, setTarget] = useState<{ line: number; seq: number } | null>(null)
  const [seen, setSeen] = useState<Set<number>>(() => new Set())
  const onStateRef = useRef(onState)
  useEffect(() => {
    onStateRef.current = onState
  })
  const markdown = format === 'markdown'
  const [mode, setModeState] = useState<Mode>(() => (markdown ? savedMode() : 'source'))
  const preview = markdown && mode === 'preview'

  useEffect(() => {
    const ctl = new AbortController()
    onStateRef.current({ status: 'loading' })
    fetch(src, { signal: ctl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`The file could not be loaded (${r.status}).`)
        return r.arrayBuffer()
      })
      .then((buf) => {
        const { text } = decodeText(buf)
        const lines = text.split('\n')
        setDoc({ text, lines, starts: lineStarts(text), toUnit: codePointIndex(text), kinds: markdown ? markdownLineKinds(lines) : [] })
        setSeen(new Set(Array.from({ length: EAGER_GROUPS }, (_, g) => g)))
      })
      .catch((err: Error) => {
        if (!ctl.signal.aborted) onStateRef.current({ status: 'error', message: err.message || 'The file could not be displayed.' })
      })
    return () => ctl.abort()
  }, [src, markdown])

  useEffect(() => {
    if (doc) onStateRef.current({ status: 'ready', scale, ...(markdown ? { modes: MODES, mode } : {}) })
  }, [doc, scale, markdown, mode])

  const scrollToLine = (line: number) => setTarget((t) => ({ line, seq: (t?.seq ?? 0) + 1 }))

  useImperativeHandle(ref, () => ({
    navigateTo(location: SourceLocation, regionIndex = 0) {
      const regions = textRegions(location)
      const region = regions[regionIndex] ?? regions[0]
      if (region) scrollToLine(region.line_start)
    },
    highlight(hs: Highlight[]) {
      if (!doc) return
      setHl(hs)
      setEvidence(
        hs.flatMap((h) =>
          textRegions(h.location).map((r, i) => ({
            start: doc.toUnit(r.char_start),
            end: doc.toUnit(r.char_end),
            kind: h.lowConfidence ? ('low' as const) : ('evidence' as const),
            label: i === 0 ? h.label : undefined,
          })),
        ),
      )
    },
    clearHighlights() {
      setEvidence([])
      setHl([])
    },
    search(query: string, previous = false) {
      if (!doc) return
      if (preview) {
        setPreviewFind((f) => ({ query, step: f?.query === query ? f.step + (previous ? -1 : 1) : previous ? -1 : 0 }))
        return
      }
      const hits = find?.query === query ? find.hits : findAll(doc.text, query)
      if (!hits.length) return setFind({ query, hits, i: -1 })
      const i = find?.query === query ? (find.i + (previous ? -1 : 1) + hits.length) % hits.length : previous ? hits.length - 1 : 0
      setFind({ query, hits, i })
      scrollToLine(lineOf(doc.starts, hits[i]) + 1)
    },
    goToPage() {},
    setMode(id: string) {
      if (!markdown || (id !== 'preview' && id !== 'source')) return
      localStorage.setItem(MODE_KEY, id)
      setModeState(id)
      // Keep the reader where they were: re-show the active evidence in the new view.
      const first = hl.flatMap((h) => textRegions(h.location))[0]
      if (first) scrollToLine(first.line_start)
    },
    zoom(action) {
      setScale((s) => (action === 'in' ? Math.min(2, s * 1.1) : action === 'out' ? Math.max(0.7, s / 1.1) : 1))
    },
  }))

  // Everything painted on the text, grouped by line, then by render group.
  const byGroup = useMemo(() => {
    const groups = new Map<number, Map<number, LineMark[]>>()
    if (!doc) return groups
    const marks: Mark[] = [...evidence]
    if (find && find.query) {
      const len = find.query.length
      find.hits.forEach((h, i) => marks.push({ start: h, end: h + len, kind: i === find.i ? 'find-current' : 'find' }))
    }
    for (const [ln, list] of marksByLine(doc.text, doc.starts, marks)) {
      const g = Math.floor(ln / GROUP)
      if (!groups.has(g)) groups.set(g, new Map())
      groups.get(g)!.set(ln, list)
    }
    return groups
  }, [doc, evidence, find])

  const targetGroup = target ? Math.floor((target.line - 1) / GROUP) : -1
  const markSeen = useCallback((i: number) => setSeen((s) => (s.has(i) ? s : new Set(s).add(i))), [])

  // Scroll so the target line sits ~30% down, as the PDF viewer does. Re-measure after one frame:
  // groups around the target may render and change height once they come into view.
  useLayoutEffect(() => {
    if (!target) return
    const container = containerRef.current
    const place = () => {
      const el = preview
        ? container && blockAtLine(container, target.line)
        : container?.querySelector<HTMLElement>(`[data-line="${target.line}"]`)
      if (container && el) placeAt(container, el)
    }
    place()
    const raf = requestAnimationFrame(() => requestAnimationFrame(place))
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-place only when asked to, not on every mode render
  }, [target])

  const html = useMemo(() => (doc && markdown ? renderMarkdown(doc.text) : ''), [doc, markdown])

  if (!doc) return <div ref={containerRef} className="ad-viewer absolute inset-0" />

  if (preview)
    return (
      <div ref={containerRef} className="ad-viewer absolute inset-0 overflow-auto" tabIndex={0} aria-label="Document" style={{ ['--ad-scale' as string]: scale }}>
        <MarkdownPreview html={html} doc={doc} hl={hl} find={previewFind} container={containerRef} scale={scale} />
      </div>
    )

  const groupCount = Math.ceil(doc.lines.length / GROUP)
  const gutter = `${String(doc.lines.length).length + 1.5}ch`
  return (
    <div
      ref={containerRef}
      className="ad-viewer absolute inset-0 overflow-auto"
      tabIndex={0}
      aria-label="Document"
      style={{ ['--ad-scale' as string]: scale, ['--ad-gutter' as string]: gutter }}
    >
      <div className="ad-sheet" data-format={markdown ? 'markdown' : 'text'}>
        {Array.from({ length: groupCount }, (_, g) => (
          <Group
            key={g}
            index={g}
            lines={doc.lines}
            kinds={doc.kinds}
            marks={byGroup.get(g)}
            render={seen.has(g) || g === targetGroup}
            estimate={Math.min(GROUP, doc.lines.length - g * GROUP) * LINE_PX[markdown ? 'markdown' : 'text'] * scale}
            root={containerRef}
            onSeen={markSeen}
          />
        ))}
      </div>
    </div>
  )
}

type GroupProps = {
  index: number
  lines: string[]
  kinds: LineKind[]
  marks: Map<number, LineMark[]> | undefined
  render: boolean
  estimate: number
  root: RefObject<HTMLDivElement | null>
  onSeen: (index: number) => void
}

const Group = memo(function Group({ index, lines, kinds, marks, render, estimate, root, onSeen }: GroupProps) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (render || !el.current) return
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && onSeen(index), {
      root: root.current,
      rootMargin: '1500px 0px',
    })
    io.observe(el.current)
    return () => io.disconnect()
  }, [render, index, root, onSeen])

  if (!render) return <div ref={el} style={{ height: estimate }} aria-hidden />
  const first = index * GROUP
  const rows = lines.slice(first, first + GROUP)
  return (
    <div ref={el}>
      {rows.map((line, k) => {
        const ln = first + k
        const lineMarks = marks?.get(ln)
        const pin = lineMarks?.find((m) => m.label)
        return (
          <div key={ln} className="ad-tl" data-line={ln + 1} data-kind={kinds[ln] ?? undefined}>
            <span className="ad-tl-no" aria-hidden>
              {pin ? (
                <span className="ad-pin ad-tl-pin" data-low={String(pin.kind === 'low')}>
                  {pin.label}
                </span>
              ) : (
                ln + 1
              )}
            </span>
            <span className="ad-tl-text">
              {line === ''
                ? '​'
                : pieces(line, lineMarks).map((p, i) =>
                    p.kinds.length ? (
                      <mark key={i} className="ad-mark" data-kinds={p.kinds.join(' ')}>
                        {p.text}
                      </mark>
                    ) : (
                      p.text
                    ),
                  )}
            </span>
          </div>
        )
      })}
    </div>
  )
})

type PreviewProps = {
  html: string
  doc: Doc
  hl: Highlight[]
  find: { query: string; step: number } | null
  container: RefObject<HTMLDivElement | null>
  scale: number
}

/** Rendered Markdown. Citations wash their source blocks, paint the exact quote, and pin the margin note. */
const MarkdownPreview = memo(function MarkdownPreview({ html, doc, hl, find, container, scale }: PreviewProps) {
  const root = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    el.querySelectorAll('.ad-md-hit').forEach((n) => n.classList.remove('ad-md-hit'))
    el.querySelectorAll('[data-low]').forEach((n) => n.removeAttribute('data-low'))
    el.querySelectorAll('.ad-md-pin').forEach((n) => n.remove())
    const ranges: Range[] = []
    for (const h of hl) {
      textRegions(h.location).forEach((r, i) => {
        const blocks = blocksForLines(el, r.line_start, r.line_end)
        for (const b of blocks) {
          b.classList.add('ad-md-hit')
          if (h.lowConfidence) b.dataset.low = 'true'
        }
        const range = rangeForQuote(blocks, doc.text.slice(doc.toUnit(r.char_start), doc.toUnit(r.char_end)))
        if (range) ranges.push(range)
        if (i === 0 && h.label && blocks[0]) {
          const pin = document.createElement('span')
          pin.className = 'ad-pin ad-md-pin'
          pin.textContent = h.label
          pin.dataset.low = String(!!h.lowConfidence)
          pin.style.top = `${blocks[0].getBoundingClientRect().top - el.getBoundingClientRect().top}px`
          el.appendChild(pin)
        }
      })
    }
    paintRanges('ad-evidence', ranges)
    return () => paintRanges('ad-evidence', [])
  }, [hl, html, doc, scale])

  useLayoutEffect(() => {
    const el = root.current
    if (!el || !find?.query) return
    const ranges = findRanges(el, find.query)
    if (!ranges.length) return
    const i = ((find.step % ranges.length) + ranges.length) % ranges.length
    paintRanges('ad-find', ranges)
    paintRanges('ad-find-current', [ranges[i]])
    if (container.current) placeAt(container.current, ranges[i])
    return () => {
      paintRanges('ad-find', [])
      paintRanges('ad-find-current', [])
    }
  }, [find, html, container])

  return <div ref={root} className="ad-md" dangerouslySetInnerHTML={{ __html: html }} />
})
