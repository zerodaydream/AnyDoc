/** Section starters from the document's real headings: grounded, never invented. */
const SKIP_HEADINGS = /^(abstract|references|bibliography|acknowledg|appendix|contents)/i

export type Starter = { label: string; ref: string; question: string }

export function starterQuestions(headings: { text: string; ref: string }[], max = 4): Starter[] {
  const seen = new Set<string>()
  const out: Starter[] = []
  for (const h of headings.slice(1)) {
    // the first heading is usually the document title; drop "3.2.1 " style numbering
    const label = h.text.replace(/^[\dA-Z]+(\.\d+)*\.?\s+/, '').trim()
    if (label.length <= 2 || label.length >= 70 || SKIP_HEADINGS.test(label) || seen.has(label)) continue
    seen.add(label)
    out.push({ label, ref: h.ref, question: `What does the section “${label}” say?` })
    if (out.length === max) break
  }
  return out
}
