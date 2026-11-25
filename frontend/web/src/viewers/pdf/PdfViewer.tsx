import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { EventBus, PDFFindController, PDFLinkService, PDFViewer } from 'pdfjs-dist/web/pdf_viewer.mjs'
import { useEffect, useImperativeHandle, useRef } from 'react'
import type { SourceLocation } from '../../lib/api'
import type { Highlight, ViewerProps } from '../core/contract'
import { toCssBox } from './geometry'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

type PageView = { div: HTMLDivElement; viewport: { convertToViewportPoint(x: number, y: number): ArrayLike<number> } }

export default function PdfViewer({ src, ref, onState }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<PDFViewer | null>(null)
  const busRef = useRef<EventBus | null>(null)
  const highlights = useRef<Highlight[]>([])
  const onStateRef = useRef(onState)
  useEffect(() => {
    onStateRef.current = onState
  })

  const paint = (pageNumber: number) => {
    const view = viewerRef.current?.getPageView(pageNumber - 1) as PageView | undefined
    if (!view?.div) return
    view.div.querySelectorAll('.ad-hl').forEach((n) => n.remove())
    for (const h of highlights.current) {
      for (const region of h.location.regions) {
        if (region.page !== pageNumber) continue
        // Margin note: the citation's numeral pinned beside the first line of evidence.
        if (h.label && region.rects.length) {
          const first = toCssBox(view.viewport, region.rects[0])
          const pin = document.createElement('div')
          pin.className = 'ad-hl ad-pin'
          pin.textContent = h.label
          pin.dataset.low = String(!!h.lowConfidence)
          Object.assign(pin.style, { left: `${Math.max(4, first.left - 30)}px`, top: `${first.top + first.height / 2 - 11}px` })
          view.div.appendChild(pin)
        }
        for (const rect of region.rects) {
          const box = toCssBox(view.viewport, rect)
          const el = document.createElement('div')
          el.className = 'ad-hl'
          el.dataset.low = String(!!h.lowConfidence)
          Object.assign(el.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px` })
          view.div.appendChild(el)
        }
      }
    }
  }

  const pagesOf = (hs: Highlight[]) => new Set(hs.flatMap((h) => h.location.regions.map((r) => r.page)))

  useImperativeHandle(ref, () => ({
    navigateTo(location: SourceLocation, regionIndex = 0) {
      const region = location.regions[regionIndex] ?? location.regions[0]
      if (!region || !viewerRef.current) return
      const top = Math.max(...region.rects.map((r) => r[3]))
      const left = Math.min(...region.rects.map((r) => r[0]))
      // XYZ destination is in PDF user space. Put the evidence ~30% down the viewport so the lines before it
      // stay visible and the cited page (not the next one) is the page the toolbar reports.
      const cssPerPt = viewerRef.current.currentScale * (96 / 72)
      const above = (containerRef.current?.clientHeight ?? 600) * 0.3 / cssPerPt
      viewerRef.current.scrollPageIntoView({
        pageNumber: region.page,
        destArray: [null, { name: 'XYZ' }, Math.max(0, left - 24), top + above, null],
        allowNegativeOffset: true,
      })
    },
    highlight(hs) {
      const touched = new Set([...pagesOf(highlights.current), ...pagesOf(hs)])
      highlights.current = hs
      touched.forEach(paint)
    },
    clearHighlights() {
      const touched = pagesOf(highlights.current)
      highlights.current = []
      touched.forEach(paint)
    },
    search(query, previous = false) {
      busRef.current?.dispatch('find', { source: null, type: 'again', query, caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: previous, matchDiacritics: false })
    },
    goToPage(page) {
      const v = viewerRef.current
      if (v && page >= 1 && page <= v.pagesCount) v.currentPageNumber = page
    },
    zoom(action) {
      const v = viewerRef.current
      if (!v) return
      if (action === 'fit-width') v.currentScaleValue = 'page-width'
      else if (action === 'fit-page') v.currentScaleValue = 'page-fit'
      else v.currentScale = Math.min(4, Math.max(0.25, v.currentScale * (action === 'in' ? 1.2 : 1 / 1.2)))
    },
  }))

  useEffect(() => {
    const container = containerRef.current!
    const eventBus = new EventBus()
    const linkService = new PDFLinkService({ eventBus })
    const findController = new PDFFindController({ eventBus, linkService })
    const viewer = new PDFViewer({ container, eventBus, linkService, findController, removePageBorders: true })
    linkService.setViewer(viewer)
    viewerRef.current = viewer
    busRef.current = eventBus

    const report = () =>
      onStateRef.current({ status: 'ready', page: viewer.currentPageNumber, pages: viewer.pagesCount, scale: viewer.currentScale })
    eventBus.on('pagesinit', () => {
      viewer.currentScaleValue = 'page-width'
      report()
    })
    eventBus.on('pagechanging', report)
    eventBus.on('scalechanging', report)
    // Re-paint after every (re)render: zoom rebuilds the page layers.
    eventBus.on('pagerendered', (e: { pageNumber: number }) => paint(e.pageNumber))

    // Re-fit when the container changes size (divider drag, hidden mobile tab becoming visible).
    let fit = 'page-width'
    eventBus.on('scalechanging', (e: { presetValue?: string }) => {
      fit = e.presetValue ?? ''
    })
    const ro = new ResizeObserver(() => {
      if (fit && container.clientWidth > 0 && viewer.pagesCount) viewer.currentScaleValue = fit
    })
    ro.observe(container)

    onStateRef.current({ status: 'loading' })
    // Range requests: the API serves Accept-Ranges, so big PDFs stream page by page.
    const task = pdfjs.getDocument({ url: src, rangeChunkSize: 256 * 1024, disableAutoFetch: true })
    let cancelled = false
    task.promise.then(
      (doc) => {
        if (cancelled) return
        viewer.setDocument(doc)
        linkService.setDocument(doc)
      },
      (err: Error) => {
        if (!cancelled) onStateRef.current({ status: 'error', message: err.message || 'The PDF could not be displayed.' })
      },
    )
    return () => {
      ro.disconnect()
      cancelled = true
      void task.destroy()
      viewerRef.current = null
      busRef.current = null
    }
  }, [src])

  return (
    <div ref={containerRef} className="ad-viewer absolute inset-0 overflow-auto" tabIndex={0} aria-label="Document">
      <div className="pdfViewer" />
    </div>
  )
}
