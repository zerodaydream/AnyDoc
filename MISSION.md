# Mission

AnyDoc lets a person open a document, ask it questions, and check every answer against the exact place in the original file it came from.

## Who it is for
People who must trust what they read back: analysts, researchers, lawyers, auditors, students. They do not want a summary they cannot verify. They want an answer plus the evidence, one click away.

## What "good" means
- **Grounded.** Every claim links to a verified span in the original. No link, no claim.
- **Honest.** When the document does not say, AnyDoc says so. Abstaining is a correct answer.
- **Faithful to the original.** The file the user uploaded is the source of truth, shown as it is, not a re-typed copy.
- **Structure-aware.** Pages, sections, tables, cells, timestamps are understood, not flattened into one string.
- **Private by default.** Document text stays out of logs and third-party traces unless the user opts in.

## What it is not (for now)
- Not multi-document chat. v1 opens one document per workspace session.
- Not an editor. Originals are immutable.
- Not a general chatbot. It answers from the document, not from the model's memory.

## Shape
Local-first today, shaped for a hosted multi-user service tomorrow. Every interface (storage, jobs, auth, LLM, tracing) has a production implementation designed in, so the move to production is a swap, not a rewrite.
