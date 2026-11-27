"""Hard deletion of a document and everything derived from it. Used by the admin endpoint and by deleting the last
conversation about a document.

Rows go by database cascade: versions, blocks, chunks and embeddings, chat sessions, messages. Then each stored
original that no version uses any more is removed (storage is content-addressed: identical uploads share one file).
Nothing is soft-deleted. The audit log keeps that the deletion happened (ids and counts, never content).
"""

import logging
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.errors import Conflict
from backend.core.models import AuditLog, Document, DocumentVersion
from backend.security.auth import Principal
from backend.storage.local import get_storage

log = logging.getLogger(__name__)
BUSY = ("queued", "processing", "indexing")


async def ensure_not_busy(db: AsyncSession, p: Principal, document_id: uuid.UUID) -> None:
    statuses = await db.scalars(
        select(DocumentVersion.status).where(
            DocumentVersion.document_id == document_id, DocumentVersion.owner_id == p.owner_id
        )
    )
    if any(s in BUSY for s in statuses):
        raise Conflict(
            "still_processing", "This document is still being processed. Wait for it to finish or cancel it."
        )


async def purge_document(db: AsyncSession, p: Principal, document_id: uuid.UUID, reason: str) -> None:
    """Delete the caller's document for good and commit. The caller checks ownership and `ensure_not_busy` first."""
    keys = set(
        await db.scalars(
            select(DocumentVersion.storage_key).where(
                DocumentVersion.document_id == document_id, DocumentVersion.owner_id == p.owner_id
            )
        )
    )
    await db.execute(
        delete(Document).where(
            Document.id == document_id, Document.owner_id == p.owner_id, Document.workspace_id == p.workspace_id
        )
    )
    db.add(
        AuditLog(
            owner_id=p.owner_id,
            workspace_id=p.workspace_id,
            actor=p.actor,
            action="document.delete",
            target=str(document_id),
            details={"versions": len(keys), "reason": reason},
        )
    )
    await db.commit()
    # Files go after the rows are gone, so a failure here leaves an orphan file, never a document without its file.
    for key in keys:
        # Storage-level reference check across all owners: the bytes are shared, nothing about them is returned.
        uses = select(func.count()).select_from(DocumentVersion).where(DocumentVersion.storage_key == key)
        if not await db.scalar(uses):
            try:
                get_storage().delete(key)
            except OSError:
                log.warning("stored_file_delete_failed", extra={"document_id": str(document_id)})
