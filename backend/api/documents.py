import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.db import session_dep
from backend.core.errors import Conflict, InvalidFile, NotFound
from backend.core.models import AuditLog, Block, Document, DocumentVersion
from backend.extraction.registry import HANDLERS, describe, detect, handler_for
from backend.ingestion.pipeline import set_state
from backend.security.auth import Principal, get_principal
from backend.storage.local import get_storage
from backend.workers import queue

router = APIRouter(prefix="/api/documents", tags=["documents"])
HEAD_BYTES = 1024


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    filename: str
    format: str | None
    size_bytes: int
    page_count: int | None
    extent: str | None  # size in the format's own unit: "15 pages", "1,240 lines"
    version: int
    status: str
    progress: float
    stage_detail: str | None
    error: dict[str, str] | None
    file_url: str
    created_at: datetime  # when it was added (uploaded)
    ingested_at: datetime | None  # when it became ready to ask; None until then


def _out(d: Document, v: DocumentVersion) -> DocumentOut:
    handler = handler_for(v.detected_format) if v.detected_format else None
    return DocumentOut(
        id=d.id,
        title=d.title,
        filename=v.filename,
        format=v.detected_format,
        size_bytes=v.size_bytes,
        page_count=v.page_count,
        extent=handler.extent(v.page_count, v.meta or {}) if handler else None,
        version=v.version,
        status=v.status,
        progress=v.progress,
        stage_detail=v.stage_detail,
        error={"code": v.error_code, "message": v.error_detail or ""} if v.error_code else None,
        file_url=f"/api/documents/{d.id}/file",
        created_at=d.created_at,
        ingested_at=v.updated_at if v.status == "ready" else None,  # "ready" is final: its last update
    )


async def _load(db: AsyncSession, p: Principal, document_id: uuid.UUID) -> tuple[Document, DocumentVersion]:
    row = (
        await db.execute(
            select(Document, DocumentVersion)
            .join(
                DocumentVersion,
                (DocumentVersion.document_id == Document.id) & (DocumentVersion.version == Document.current_version),
            )
            .where(
                Document.id == document_id,
                Document.owner_id == p.owner_id,
                Document.workspace_id == p.workspace_id,
            )
        )
    ).first()
    if row is None:
        raise NotFound()
    return row[0], row[1]


def _audit(p: Principal, action: str, target: uuid.UUID, **details: Any) -> AuditLog:
    return AuditLog(
        owner_id=p.owner_id,
        workspace_id=p.workspace_id,
        actor=p.actor,
        action=action,
        target=str(target),
        details=details,
    )


@router.post("", status_code=201)
async def upload(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(session_dep),
) -> DocumentOut:
    """Raw-body upload streamed straight to storage (no multipart buffering)."""
    s = get_settings()
    if int(request.headers.get("content-length") or 0) > s.max_upload_bytes:
        raise InvalidFile("too_large", f"File is larger than {s.max_upload_mb} MB.")
    filename = filename.replace("/", "_").replace("\\", "_")

    body = request.stream()
    head = b""
    async for chunk in body:
        head += chunk
        if len(head) >= HEAD_BYTES:
            break
    if not head:
        raise InvalidFile("empty_file", "The file is empty.")
    handler = detect(filename, head)  # extension + magic bytes, before anything is stored

    async def all_chunks() -> AsyncIterator[bytes]:
        yield head
        async for chunk in body:
            yield chunk

    stored = await get_storage().put_stream(all_chunks(), s.max_upload_bytes)
    doc = Document(owner_id=p.owner_id, workspace_id=p.workspace_id, title=filename.rsplit(".", 1)[0][:512])
    db.add(doc)
    await db.flush()
    v = DocumentVersion(
        owner_id=p.owner_id,
        workspace_id=p.workspace_id,
        document_id=doc.id,
        version=1,
        filename=filename,
        storage_key=stored.key,
        sha256=stored.sha256,
        size_bytes=stored.size,
        detected_format=handler.name,
        status="queued",
        progress=0.0,
        stage_detail="Waiting to start",
        meta={},
    )
    db.add(v)
    db.add(_audit(p, "document.upload", doc.id, size=stored.size, format=handler.name))
    await db.commit()
    try:
        v.queue_job_id = await queue.enqueue_ingest(v.id)
        await db.commit()
    except Exception:
        await set_state(
            db,
            v.id,
            "failed",
            error_code="queue_unavailable",
            error_detail="Couldn't start processing. Try again.",
        )
        raise
    return _out(doc, v)


@router.get("")
async def list_documents(
    p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> list[DocumentOut]:
    rows = await db.execute(
        select(Document, DocumentVersion)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == Document.id) & (DocumentVersion.version == Document.current_version),
        )
        .where(Document.owner_id == p.owner_id, Document.workspace_id == p.workspace_id)
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    return [_out(d, v) for d, v in rows]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> DocumentOut:
    return _out(*await _load(db, p, document_id))


@router.get("/{document_id}/file")
async def get_file(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> FileResponse:
    _, v = await _load(db, p, document_id)
    with get_storage().local_path(v.storage_key) as path:
        # FileResponse serves HTTP Range requests, so pdf.js loads large files progressively.
        return FileResponse(
            path,
            media_type=handler_for(v.detected_format or "").media_type,
            filename=v.filename,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "X-Content-Type-Options": "nosniff",
            },
        )


@router.post("/{document_id}/cancel", status_code=202)
async def cancel(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> DocumentOut:
    d, v = await _load(db, p, document_id)
    if v.status not in ("queued", "processing", "indexing"):
        raise Conflict("not_cancellable", "Only documents that are still processing can be cancelled.")
    if v.queue_job_id is not None:
        await queue.cancel(v.queue_job_id)
    if v.status == "queued":  # not started: mark now. Running jobs see the abort and mark themselves.
        await set_state(db, v.id, "cancelled", stage_detail=None)
    db.add(_audit(p, "document.cancel", d.id))
    await db.commit()
    await db.refresh(v)
    return _out(d, v)


@router.post("/{document_id}/retry", status_code=202)
async def retry(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> DocumentOut:
    d, v = await _load(db, p, document_id)
    if v.status not in ("failed", "cancelled"):
        raise Conflict("not_retryable", "Only failed or cancelled documents can be retried.")
    await set_state(
        db, v.id, "queued", progress=0.0, stage_detail="Waiting to start", error_code=None, error_detail=None
    )
    v.queue_job_id = await queue.enqueue_ingest(v.id)
    db.add(_audit(p, "document.retry", d.id))
    await db.commit()
    await db.refresh(v)
    return _out(d, v)


class OutlineItem(BaseModel):
    block_id: str
    text: str
    page: int | None
    ref: str
    location: dict[str, Any]


@router.get("/{document_id}/outline")
async def outline(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> list[OutlineItem]:
    """Headings in reading order: section navigation and grounded starter questions."""
    _, v = await _load(db, p, document_id)
    rows = await db.scalars(
        select(Block)
        .where(Block.version_id == v.id, Block.owner_id == p.owner_id, Block.type == "heading")
        .order_by(Block.ordinal)
        .limit(200)
    )
    return [
        OutlineItem(
            block_id=b.block_id,
            text=(b.section_path[-1] if b.section_path else b.content)[:200],
            page=b.page,
            ref=describe(b.source_location),
            location=b.source_location,
        )
        for b in rows
    ]


class FormatOut(BaseModel):
    name: str
    label: str
    extensions: list[str]


formats_router = APIRouter(prefix="/api/formats", tags=["documents"])


@formats_router.get("")
async def formats() -> list[FormatOut]:
    """What can be uploaded. The upload UI reads this, so a new format needs no frontend change there."""
    return [FormatOut(name=h.name, label=h.label, extensions=list(h.extensions)) for h in HANDLERS]
