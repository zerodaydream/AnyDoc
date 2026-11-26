"""Ingestion: stored original -> sandboxed extract -> IR blocks -> chunks + FTS + embeddings -> ready."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.db import get_sessionmaker
from backend.core.errors import InvalidFile, TransientError
from backend.core.models import Block, Chunk, DocumentVersion
from backend.document_ir.models import ExtractLimits, ExtractResult
from backend.extraction.registry import handler_for
from backend.extraction.sandbox import run_sandboxed
from backend.indexing.chunker import chunk_blocks
from backend.indexing.embeddings import get_embedder
from backend.observability.tracing import trace_metadata, traced
from backend.storage.local import get_storage

log = logging.getLogger(__name__)

STATES = (
    "pending",
    "uploading",
    "uploaded",
    "validating",
    "queued",
    "processing",
    "indexing",
    "ready",
    "failed",
    "cancelled",
)
TERMINAL = {"ready", "failed", "cancelled"}
_ALLOWED: dict[str, set[str]] = {
    "pending": {"uploading", "failed", "cancelled"},
    "uploading": {"uploaded", "failed", "cancelled"},
    "uploaded": {"validating", "failed", "cancelled"},
    "validating": {"queued", "failed", "cancelled"},
    "queued": {"processing", "failed", "cancelled"},
    "processing": {"indexing", "failed", "cancelled", "queued"},  # queued: retry after a transient error
    "indexing": {"ready", "failed", "cancelled", "queued"},
    "failed": {"queued"},  # manual retry
    "cancelled": {"queued"},
    "ready": set(),
}
EMBED_BATCH = 64


class Cancelled(Exception):
    pass


async def set_state(db: AsyncSession, version_id: uuid.UUID, state: str, **fields: Any) -> None:
    current = await db.scalar(select(DocumentVersion.status).where(DocumentVersion.id == version_id).with_for_update())
    if current is None:
        raise LookupError(version_id)
    if state != current and state not in _ALLOWED[current]:
        raise ValueError(f"illegal transition {current} -> {state}")
    await db.execute(update(DocumentVersion).where(DocumentVersion.id == version_id).values(status=state, **fields))
    await db.commit()


@traced("ingest")
async def ingest(version_id: uuid.UUID, should_abort: Callable[[], bool] = lambda: False) -> None:
    s = get_settings()
    async with get_sessionmaker()() as db:
        v = await db.get(DocumentVersion, version_id)
        if v is None or v.status in TERMINAL:
            return  # idempotent: duplicate or late job
        trace_metadata(document_id=str(v.document_id), document_version=v.version, format=v.detected_format)

        def check() -> None:
            if should_abort():
                raise Cancelled

        try:
            await set_state(
                db,
                version_id,
                "processing",
                progress=0.1,
                stage_detail="Reading the file",
                error_code=None,
                error_detail=None,
            )
            handler = handler_for(v.detected_format or "")
            with get_storage().local_path(v.storage_key) as path:
                result: ExtractResult = await asyncio.to_thread(
                    run_sandboxed,
                    handler.extract,
                    path,
                    ExtractLimits(max_pages=s.max_pages, max_chars=s.max_text_chars),
                    timeout_s=s.parse_timeout_s,
                    mem_mb=s.parse_memory_mb,
                )
            check()

            # Retry-safe: wipe partial output of an earlier attempt.
            await db.execute(delete(Chunk).where(Chunk.version_id == version_id))
            await db.execute(delete(Block).where(Block.version_id == version_id))
            owner = {"owner_id": v.owner_id, "workspace_id": v.workspace_id, "version_id": version_id}
            db.add_all(
                Block(
                    **owner,
                    block_id=b.block_id,
                    ordinal=b.ordinal,
                    page=b.page,
                    type=b.type,
                    content=b.content,
                    source_location=b.source_location.model_dump(),
                    format_metadata=b.format_metadata,
                    confidence=b.confidence,
                    section_path=b.section_path,
                    token_estimate=b.token_estimate,
                )
                for b in result.blocks
            )
            await db.commit()
            await set_state(
                db,
                version_id,
                "indexing",
                progress=0.5,
                stage_detail="Indexing",
                page_count=result.page_count,
                meta=result.metadata,
            )

            drafts = chunk_blocks(result.blocks)
            embedder = get_embedder()
            for i in range(0, len(drafts), EMBED_BATCH):
                check()
                batch = drafts[i : i + EMBED_BATCH]
                vecs = await embedder.embed_documents([d.text for d in batch])
                db.add_all(
                    Chunk(
                        **owner,
                        ordinal=i + j,
                        block_ids=d.block_ids,
                        text=d.text,
                        embedding=vec,
                        embedding_model=embedder.model_id,
                    )
                    for j, (d, vec) in enumerate(zip(batch, vecs, strict=True))
                )
                await db.commit()
                await db.execute(
                    update(DocumentVersion)
                    .where(DocumentVersion.id == version_id)
                    .values(progress=0.5 + 0.45 * min(1.0, (i + len(batch)) / len(drafts)))
                )
                await db.commit()

            n_blocks = await db.scalar(select(func.count()).select_from(Block).where(Block.version_id == version_id))
            n_chunks = await db.scalar(select(func.count()).select_from(Chunk).where(Chunk.version_id == version_id))
            if not n_blocks or not n_chunks:
                raise InvalidFile("index_empty", "No readable text was found in this file.")
            await set_state(db, version_id, "ready", progress=1.0, stage_detail=None)
            trace_metadata(pages=result.page_count, blocks=n_blocks, chunks=n_chunks)
        except InvalidFile as e:
            await db.rollback()
            await set_state(db, version_id, "failed", error_code=e.code, error_detail=e.message, stage_detail=None)
        except Cancelled:
            await db.rollback()
            await set_state(db, version_id, "cancelled", stage_detail=None)
        except TransientError:
            await db.rollback()
            await set_state(db, version_id, "queued", stage_detail="Retrying")
            raise  # procrastinate retries with backoff
        except Exception:
            log.exception("ingest_failed", extra={"version_id": str(version_id)})
            await db.rollback()
            await set_state(
                db,
                version_id,
                "failed",
                error_code="internal_error",
                error_detail="Processing failed unexpectedly. Try again.",
                stage_detail=None,
            )
