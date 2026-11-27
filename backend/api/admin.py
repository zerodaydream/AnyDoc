"""Admin-only maintenance endpoints (see security/admin.py for the gate).

DELETE /api/admin/documents/{id}: removes a document for good (core/purge.py), whatever conversations it has.
Scoped to the caller's owner and workspace. A document still being ingested must be cancelled first.
"""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db import session_dep
from backend.core.errors import NotFound
from backend.core.models import Document
from backend.core.purge import ensure_not_busy, purge_document
from backend.security.admin import require_admin
from backend.security.auth import Principal, get_principal

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> Response:
    found = await db.scalar(
        select(Document.id).where(
            Document.id == document_id, Document.owner_id == p.owner_id, Document.workspace_id == p.workspace_id
        )
    )
    if found is None:
        raise NotFound()
    await ensure_not_busy(db, p, document_id)
    await purge_document(db, p, document_id, reason="admin")
    return Response(status_code=204)
