import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.answering.engine import answer_stream
from backend.core.db import session_dep
from backend.core.errors import NotFound
from backend.core.models import Document, Message
from backend.security.auth import Principal, get_principal

router = APIRouter(prefix="/api/documents/{document_id}/messages", tags=["chat"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    segments: list[dict[str, Any]]
    created_at: datetime


@router.get("")
async def history(
    document_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> list[MessageOut]:
    owned = await db.scalar(
        select(Document.id).where(
            Document.id == document_id,
            Document.owner_id == p.owner_id,
            Document.workspace_id == p.workspace_id,
        )
    )
    if owned is None:
        raise NotFound()
    rows = await db.scalars(
        select(Message)
        .where(Message.document_id == document_id, Message.owner_id == p.owner_id)
        .order_by(Message.created_at)
        .limit(500)
    )
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            status=m.status,
            segments=m.segments,
            created_at=m.created_at,
        )
        for m in rows
    ]


@router.post("")
async def ask(document_id: uuid.UUID, body: AskIn, p: Principal = Depends(get_principal)) -> StreamingResponse:
    async def sse() -> AsyncIterator[str]:
        async for e in answer_stream(p, document_id, body.question.strip()):
            yield f"event: {e['event']}\ndata: {json.dumps(e['data'], separators=(',', ':'))}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
