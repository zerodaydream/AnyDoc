"""Chat sessions. Each session is one conversation about one document; its messages are its only context."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.answering.engine import answer_stream
from backend.core.db import session_dep
from backend.core.errors import NotFound
from backend.core.models import AuditLog, ChatSession, Document, DocumentVersion, Message
from backend.security.auth import Principal, get_principal

router = APIRouter(prefix="/api/sessions", tags=["chat"])


class SessionIn(BaseModel):
    document_id: uuid.UUID


class SessionPatch(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str | None
    document_id: uuid.UUID
    document_title: str
    document_status: str
    created_at: datetime
    updated_at: datetime


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    segments: list[dict[str, Any]]
    created_at: datetime


def _scoped(p: Principal) -> Any:
    return (
        select(ChatSession, Document.title, DocumentVersion.status)
        .join(Document, Document.id == ChatSession.document_id)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == Document.id) & (DocumentVersion.version == Document.current_version),
        )
        .where(ChatSession.owner_id == p.owner_id, ChatSession.workspace_id == p.workspace_id)
    )


def _out(row: Any) -> SessionOut:
    c, title, status = row
    return SessionOut(
        id=c.id,
        title=c.title,
        document_id=c.document_id,
        document_title=title,
        document_status=status,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _get(db: AsyncSession, p: Principal, session_id: uuid.UUID) -> Any:
    row = (await db.execute(_scoped(p).where(ChatSession.id == session_id))).first()
    if row is None:
        raise NotFound("Conversation")
    return row


def _audit(p: Principal, action: str, target: uuid.UUID) -> AuditLog:
    return AuditLog(owner_id=p.owner_id, workspace_id=p.workspace_id, actor=p.actor, action=action, target=str(target))


@router.get("")
async def list_sessions(
    p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> list[SessionOut]:
    rows = await db.execute(_scoped(p).order_by(ChatSession.updated_at.desc()).limit(300))
    return [_out(r) for r in rows]


@router.post("", status_code=201)
async def create_session(
    body: SessionIn, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> SessionOut:
    owned = await db.scalar(
        select(Document.id).where(
            Document.id == body.document_id, Document.owner_id == p.owner_id, Document.workspace_id == p.workspace_id
        )
    )
    if owned is None:
        raise NotFound()
    chat = ChatSession(owner_id=p.owner_id, workspace_id=p.workspace_id, document_id=body.document_id)
    db.add(chat)
    await db.flush()
    db.add(_audit(p, "session.create", chat.id))
    await db.commit()
    return _out(await _get(db, p, chat.id))


@router.patch("/{session_id}")
async def rename_session(
    session_id: uuid.UUID,
    body: SessionPatch,
    p: Principal = Depends(get_principal),
    db: AsyncSession = Depends(session_dep),
) -> SessionOut:
    chat = (await _get(db, p, session_id))[0]
    chat.title = " ".join(body.title.split())
    await db.commit()
    return _out(await _get(db, p, session_id))


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> Response:
    chat = (await _get(db, p, session_id))[0]
    await db.delete(chat)  # messages cascade; the document and its index stay
    db.add(_audit(p, "session.delete", session_id))
    await db.commit()
    return Response(status_code=204)


@router.get("/{session_id}/messages")
async def history(
    session_id: uuid.UUID, p: Principal = Depends(get_principal), db: AsyncSession = Depends(session_dep)
) -> list[MessageOut]:
    await _get(db, p, session_id)
    rows = await db.scalars(
        select(Message)
        .where(Message.session_id == session_id, Message.owner_id == p.owner_id)
        .order_by(Message.created_at)
        .limit(500)
    )
    return [
        MessageOut(
            id=m.id, role=m.role, content=m.content, status=m.status, segments=m.segments, created_at=m.created_at
        )
        for m in rows
    ]


@router.post("/{session_id}/messages")
async def ask(session_id: uuid.UUID, body: AskIn, p: Principal = Depends(get_principal)) -> StreamingResponse:
    async def sse() -> AsyncIterator[str]:
        async for e in answer_stream(p, session_id, body.question.strip()):
            yield f"event: {e['event']}\ndata: {json.dumps(e['data'], separators=(',', ':'))}\n\n"

    return StreamingResponse(
        sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
