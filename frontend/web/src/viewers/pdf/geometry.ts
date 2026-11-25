import type { Rect } from '../../lib/api'

type Viewport = { convertToViewportPoint(x: number, y: number): ArrayLike<number> }

/** PDF user-space rect -> CSS box inside the page div. pdf.js applies scale, rotation and CropBox offset. */
export function toCssBox(viewport: Viewport, [x0, y0, x1, y1]: Rect, pad = 1.5) {
  // pdf.js 6 has no rectangle helper; converting both corners is equivalent (and correct under rotation).
  const a = viewport.convertToViewportPoint(x0, y0)
  const b = viewport.convertToViewportPoint(x1, y1)
  return {
    left: Math.min(a[0], b[0]) - pad,
    top: Math.min(a[1], b[1]) - pad,
    width: Math.abs(b[0] - a[0]) + 2 * pad,
    height: Math.abs(b[1] - a[1]) + 2 * pad,
  }
}
