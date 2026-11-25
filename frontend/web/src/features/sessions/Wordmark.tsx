/** AnyDoc mark: a page corner with a clay margin tab, the product's own citation pin. */
export function Wordmark() {
  return (
    <span className="flex items-center gap-2 text-fg">
      <svg width="20" height="22" viewBox="0 0 20 22" aria-hidden className="shrink-0">
        <path d="M3 1.5h9.5L17 6v14.5H3z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="M12.5 1.5V6H17" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <rect x="0" y="10" width="6" height="6" rx="1.5" fill="var(--accent)" />
      </svg>
      <span className="font-serif text-[19px] leading-none tracking-[-0.01em]">AnyDoc</span>
    </span>
  )
}
