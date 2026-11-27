import { Dialog } from '../../components/ui/Dialog'
import { TERMS, TERMS_SUBTITLE, TERMS_TITLE, TERMS_UPDATED } from './terms'

export function TermsDialog({ onClose, layer }: { onClose: () => void; layer?: number }) {
  return (
    <Dialog
      title={TERMS_TITLE}
      onClose={onClose}
      layer={layer}
      footer={
        <button data-autofocus onClick={onClose} className="h-9 rounded-lg bg-surface px-3.5 font-medium text-fg hover:bg-line">
          Got it
        </button>
      }
    >
      <p className="mb-3 text-muted">{TERMS_SUBTITLE}</p>
      {TERMS.map((s) => (
        <section key={s.heading} className="mt-3 first:mt-0">
          <h3 className="text-[13px] font-medium text-muted">{s.heading}</h3>
          <ul className="mt-1.5 space-y-1.5">
            {s.points.map((p) => (
              <li key={p} className="flex gap-2.5">
                <span aria-hidden className="mt-[9px] size-1 shrink-0 rounded-full bg-accent" />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <p className="mt-4 text-[12px] text-muted">Last updated {TERMS_UPDATED}.</p>
    </Dialog>
  )
}
