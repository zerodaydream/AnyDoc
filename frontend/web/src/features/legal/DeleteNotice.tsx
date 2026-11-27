import { Dialog } from '../../components/ui/Dialog'

/** Shown the first time someone deletes a conversation: what goes, that it's permanent, where the terms are. */
export function DeleteNotice({
  title,
  onConfirm,
  onCancel,
  onReadTerms,
}: {
  title: string
  onConfirm: () => void
  onCancel: () => void
  onReadTerms: () => void
}) {
  return (
    <Dialog
      title="Delete this conversation for good?"
      onClose={onCancel}
      footer={
        <>
          <button data-autofocus onClick={onCancel} className="h-9 rounded-lg px-3.5 font-medium text-fg hover:bg-surface">
            Cancel
          </button>
          <button onClick={onConfirm} className="h-9 rounded-lg bg-danger px-3.5 font-medium text-white hover:opacity-90">
            Delete
          </button>
        </>
      }
    >
      <p>
        “<span className="text-fg">{title}</span>” and all its questions and answers will be erased. If it’s the last
        conversation about its document, the uploaded file, its text and its search index are erased too.
      </p>
      <p className="mt-2">This can’t be undone. AnyDoc doesn’t keep hidden copies.</p>
      <p className="mt-3">
        Please read the{' '}
        <button onClick={onReadTerms} className="font-medium text-accent underline-offset-2 hover:underline">
          terms on deleting your information
        </button>{' '}
        before you continue.
      </p>
    </Dialog>
  )
}
