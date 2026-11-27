/**
 * Terms and conditions, loaded from terms_and_conditions.json (edit the text there, not here).
 * The text must match the backend: core/purge.py, api/chat.py delete_session, answering/web.py.
 */
import terms from './terms_and_conditions.json'

export type TermsSection = { heading: string; points: string[] }
type Terms = { title: string; subtitle: string; updated: string; sections: TermsSection[] }

const t: Terms = terms

export const TERMS_TITLE = t.title
export const TERMS_SUBTITLE = t.subtitle
export const TERMS_UPDATED = t.updated
export const TERMS = t.sections
