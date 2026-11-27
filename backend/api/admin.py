"""Admin-only maintenance endpoints (see security/admin.py for the gate).

DELETE /api/admin/documents/{id}: removes a document for good: its versions, blocks, chunks and embeddings,
chat sessions and messages (database cascades), then each stored original no other version still uses (storage is
content-addressed, so two uploads of the same bytes share one file). Scoped to the caller's owner and workspace.
A document still being ingested must be cancelled first.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db import session_dep
from backend.core.errors import Conflict, NotFound
from backend.core.models import AuditLog, Document, DocumentVersion
from backend.security.admin import require_admin
from backend.security.auth import Principal, get_principal
from backend.storage.local import get_storage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])
_BUSY = ("queued", "processing", "indexing")


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> Response:
    doc = await db.scalar(
        select(Document).where(
            Document.id == document_id, Document.owner_id == p.owner_id, Document.workspace_id == p.workspace_id
        )
    )
    if doc is None:
        raise NotFound()
    versions = (
        await db.execute(
            select(DocumentVersion.storage_key, DocumentVersion.status).where(
                DocumentVersion.document_id == doc.id, DocumentVersion.owner_id == p.owner_id
            )
        )
    ).all()
    if any(status in _BUSY for _, status in versions):
        raise Conflict("still_processing", "This document is still being processed. Cancel it first, then delete.")
    keys = {key for key, _ in versions}
    await db.execute(delete(Document).where(Document.id == doc.id, Document.owner_id == p.owner_id))
    db.add(
        AuditLog(
            owner_id=p.owner_id,
            workspace_id=p.workspace_id,
            actor=p.actor,
            action="document.delete",
            target=str(doc.id),
            details={"versions": len(versions)},
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
                log.warning("stored_file_delete_failed", extra={"document_id": str(doc.id)})
    return Response(status_code=204)
