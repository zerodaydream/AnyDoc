/** AnyDoc brand marks. Colours come from --logo-* tokens (index.css), so both follow the theme. */

export type MarkState = 'idle' | 'thinking' | 'streaming'

/**
 * The 24×24 icon: a page with text lines and the four-point AnyDoc sparkle.
 * `state` drives the motion: thinking = the sparkle breathes and the lines read in turn,
 * streaming = a softer twinkle, idle = still. `enter` draws the page in once on mount.
 */
export function LogoMark({ size = 24, state = 'idle', enter = false, className = '' }: { size?: number; state?: MarkState; enter?: boolean; className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      data-state={state}
      data-enter={enter || undefined}
      className={`ad-mark shrink-0 ${className}`}
    >
      <path
        className="ad-mark-page"
        pathLength={1}
        d="M5 2.5H13L19.5 9V20.5C19.5 21.05 19.05 21.5 18.5 21.5H5C3.9 21.5 3 20.6 3 19.5V4.5C3 3.4 3.9 2.5 5 2.5Z"
        stroke="var(--logo-ink)"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path className="ad-mark-page" pathLength={1} d="M13 2.8V7.5C13 8.33 13.67 9 14.5 9H19.2" stroke="var(--logo-ink)" strokeWidth="1.8" strokeLinejoin="round" />
      <path className="ad-mark-line" d="M6.5 11H11" stroke="var(--logo-line)" strokeWidth="1.6" strokeLinecap="round" />
      <path className="ad-mark-line" d="M6.5 14H10" stroke="var(--logo-line)" strokeWidth="1.6" strokeLinecap="round" />
      <path className="ad-mark-line" d="M6.5 17H8.5" stroke="var(--logo-line)" strokeWidth="1.6" strokeLinecap="round" />
      <path className="ad-mark-spark" d="M16 11.2C16.385 13.29 17.21 14.115 19.3 14.5C17.21 14.885 16.385 15.71 16 17.8C15.615 15.71 14.79 14.885 12.7 14.5C14.79 14.115 15.615 13.29 16 11.2Z" fill="var(--logo-spark)" />
    </svg>
  )
}

/**
 * Full lockup (elongated page icon + wordmark), the owner's artwork with theme-aware colours.
 * viewBox is cropped to the artwork and the text spaced out a little, so it reads at sidebar size.
 */
export function Wordmark({ height = 38 }: { height?: number }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" height={height} width={Math.round((height * 1160) / 365)} viewBox="50 20 1160 365" fill="none" role="img" aria-label="AnyDoc" className="shrink-0">
      <path d="M105 35H255L335 115V335Q335 365 305 365H105Q65 365 65 325V75Q65 35 105 35Z" stroke="var(--logo-ink)" strokeWidth="24" strokeLinejoin="round" />
      <path d="M255 38V90Q255 115 280 115H332" stroke="var(--logo-ink)" strokeWidth="24" strokeLinejoin="round" />
      <path d="M120 165H215" stroke="var(--logo-line)" strokeWidth="20" strokeLinecap="round" />
      <path d="M120 210H240" stroke="var(--logo-line)" strokeWidth="20" strokeLinecap="round" />
      <path d="M120 255H190" stroke="var(--logo-line)" strokeWidth="20" strokeLinecap="round" />
      <path d="M275 220C285 270 305 290 355 300C305 310 285 330 275 380C265 330 245 310 195 300C245 290 265 270 275 220Z" fill="var(--logo-spark)" />
      <text x="440" y="275" fontFamily="Georgia, 'Times New Roman', serif" fontSize="190" fontWeight="bold" letterSpacing="-2" fill="var(--logo-ink)">
        AnyDoc
      </text>
    </svg>
  )
}
