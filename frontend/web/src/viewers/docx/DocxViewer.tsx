import { renderAsync } from 'docx-preview'
import { useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import type { SourceLocation } from '../../lib/api'
import type { Highlight, ViewerProps } from '../core/contract'
import { findRanges, paintRanges } from '../text/preview'
import { paragraphAnchors, rangeForOffsets, RENDER_OPTIONS, sanitise } from './docx'

const docxRegions = (l: SourceLocation) => (l.kind === 'docx' ? l.regions : [])
const MIN_SCALE = 0.5
const MAX_SCALE = 2

/** Scroll `el` so it sits ~30% down the container, as the other viewers place evidence. */
function placeAt(container: HTMLElement, el: Pick<Element, 'getBoundingClientRect'>) {
  const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop
  container.scrollTop = Math.max(0, top - container.clientHeight * 0.3)
}

/**
 * Word documents rendered as HTML pages (docx-preview), one long page per section. Citations wash their paragraphs,
 * paint the exact quote and pin the margin note, like the Markdown preview.
 */
export default function DocxViewer({ src, ref, onState }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const styleRef = useRef<HTMLDivElement>(null)
  const anchors = useRef<HTMLElement[]>([])
  const pageWidth = useRef(816) // px at 100%, measured after render (8.5in default)
  const [ready, setReady] = useState(false)
  const [scale, setScale] = useState(1)
  const [fit, setFit] = useState(true) // follow the panel width until the reader zooms by hand
  const [hl, setHl] = useState<Highlight[]>([])
  const [find, setFind] = useState<{ query: string; step: number } | null>(null)
  const onStateRef = useRef(onState)
  useEffect(() => {
    onStateRef.current = onState
  })

  const fitScale = () => {
    const w = containerRef.current?.clientWidth ?? 0
    return w > 0 ? Math.min(1.25, Math.max(MIN_SCALE, (w - 32) / pageWidth.current)) : 1
  }

  useEffect(() => {
    const host = hostRef.current
    const styles = styleRef.current
    if (!host || !styles) return
    const ctl = new AbortController()
    setReady(false)
    onStateRef.current({ status: 'loading' })
    fetch(src, { signal: ctl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`The file could not be loaded (${r.status}).`)
        return r.arrayBuffer()
      })
      .then(async (buf) => {
        host.replaceChildren()
        styles.replaceChildren()
        await renderAsync(buf, host, styles, RENDER_OPTIONS)
        if (ctl.signal.aborted) return
        sanitise(host)
        anchors.current = paragraphAnchors(host)
        const page = host.querySelector<HTMLElement>('section.docx')
        if (page?.offsetWidth) pageWidth.current = page.offsetWidth
        setScale(fitScale())
        setReady(true)
      })
      .catch((err: Error) => {
        if (!ctl.signal.aborted) onStateRef.current({ status: 'error', message: err.message || 'The Word file could not be displayed.' })
      })
    return () => ctl.abort()
  }, [src])

  useEffect(() => {
    if (ready) onStateRef.current({ status: 'ready', scale })
  }, [ready, scale])

  // Re-fit when the panel changes size (divider drag, mobile tab shown), unless the reader zoomed by hand.
  useEffect(() => {
    const container = containerRef.current
    if (!container || !ready || !fit) return
    const ro = new ResizeObserver(() => setScale(fitScale()))
    ro.observe(container)
    return () => ro.disconnect()
  }, [ready, fit])

  const scrollTo = (location: SourceLocation, regionIndex = 0) => {
    const regions = docxRegions(location)
    const el = anchors.current[(regions[regionIndex] ?? regions[0])?.para ?? -1]
    if (el && containerRef.current) placeAt(containerRef.current, el)
  }

  useImperativeHandle(ref, () => ({
    navigateTo: scrollTo,
    highlight: (hs: Highlight[]) => setHl(hs),
    clearHighlights: () => setHl([]),
    search(query: string, previous = false) {
      setFind((f) => ({ query, step: f?.query === query ? f.step + (previous ? -1 : 1) : previous ? -1 : 0 }))
    },
    goToPage() {},
    zoom(action) {
      if (action === 'fit-width' || action === 'fit-page') {
        setFit(true)
        setScale(fitScale())
        return
      }
      setFit(false)
      setScale((s) => (action === 'in' ? Math.min(MAX_SCALE, s * 1.1) : Math.max(MIN_SCALE, s / 1.1)))
    },
  }))

  // Evidence: wash the cited paragraphs, paint the exact quote, pin the note beside the first region.
  useLayoutEffect(() => {
    const stage = stageRef.current
    if (!stage || !ready) return
    const host = hostRef.current!
    host.querySelectorAll('.ad-docx-hit').forEach((n) => n.classList.remove('ad-docx-hit'))
    host.querySelectorAll('[data-low]').forEach((n) => n.removeAttribute('data-low'))
    stage.querySelectorAll('.ad-docx-pin').forEach((n) => n.remove())
    void host.offsetWidth // reflow, so a re-cited paragraph replays its swipe-in
    const ranges: Range[] = []
    for (const h of hl) {
      docxRegions(h.location).forEach((r, i) => {
        const p = anchors.current[r.para]
        if (!p) return
        p.classList.add('ad-docx-hit')
        if (h.lowConfidence) p.dataset.low = 'true'
        const range = rangeForOffsets(p, r.char_start, r.char_end)
        if (range) ranges.push(range)
        if (i === 0 && h.label) {
          const at = p.getBoundingClientRect()
          const base = stage.getBoundingClientRect()
          const pin = document.createElement('span')
          pin.className = 'ad-pin ad-docx-pin'
          pin.textContent = h.label
          pin.dataset.low = String(!!h.lowConfidence)
          pin.style.top = `${at.top - base.top}px`
          pin.style.left = `${Math.max(4, at.left - base.left - 34)}px`
          stage.appendChild(pin)
        }
      })
    }
    paintRanges('ad-evidence', ranges)
    return () => paintRanges('ad-evidence', [])
  }, [hl, ready, scale])

  useLayoutEffect(() => {
    const host = hostRef.current
    if (!host || !ready || !find?.query) return
    const ranges = findRanges(host, find.query)
    if (!ranges.length) return
    const i = ((find.step % ranges.length) + ranges.length) % ranges.length
    paintRanges('ad-find', ranges)
    paintRanges('ad-find-current', [ranges[i]])
    if (containerRef.current) placeAt(containerRef.current, ranges[i])
    return () => {
      paintRanges('ad-find', [])
      paintRanges('ad-find-current', [])
    }
  }, [find, ready, scale])

  return (
    <div ref={containerRef} className="ad-viewer absolute inset-0 overflow-auto" tabIndex={0} aria-label="Document">
      <div ref={stageRef} className="ad-docx relative">
        <div ref={styleRef} hidden />
        <div ref={hostRef} style={{ zoom: scale }} />
      </div>
    </div>
  )
}
