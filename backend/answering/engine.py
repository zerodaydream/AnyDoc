"""Streamed answers with per-segment citation validation (ADR-0002).

Events: meta, text_delta, citation, segment_retracted, done, error.
Text streams immediately; a citation is emitted only after it validates; a segment whose
evidence fails is retracted. Locations come from the IR, never from the model.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from pydantic_core import from_json
from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.db import get_sessionmaker
from backend.core.models import AuditLog, Block, Document, DocumentVersion, Message
from backend.grounding.validator import EvidenceBlock, validate_segment
from backend.indexing.embeddings import get_embedder
from backend.llm.base import AnswerOut
from backend.llm.factory import get_llm
from backend.llm.prompts import SYSTEM, build_prompt
from backend.observability.tracing import trace_metadata, traced
from backend.retrieval.retriever import closest_blocks, retrieve
from backend.security.auth import Principal

log = logging.getLogger(__name__)
Event = dict[str, Any]


def _ev(event: str, **data: Any) -> Event:
    return {"event": event, "data": data}


def _evidence_block(b: Block) -> EvidenceBlock:
    return EvidenceBlock(b.block_id, b.source_location["kind"], b.content, b.page, b.format_metadata, b.confidence)


@dataclass(slots=True)
class _State:
    streamed: list[int] = field(default_factory=list)  # chars of text emitted per segment
    verdicts: dict[int, dict[str, Any]] = field(default_factory=dict)  # idx -> {text, citations} | {retracted}
    rejected: int = 0


class AnswerSession:
    def __init__(self, blocks: dict[str, EvidenceBlock], fuzzy_min: float) -> None:
        self.blocks, self.fuzzy_min, self.s = blocks, fuzzy_min, _State()

    def _close(self, idx: int, seg: dict[str, Any]) -> list[Event]:
        text = str(seg.get("text", ""))
        verdict = validate_segment(text, list(seg.get("evidence") or []), self.blocks, self.fuzzy_min)
        self.s.rejected += len(verdict.rejected)
        if not verdict.ok:
            self.s.verdicts[idx] = {"retracted": verdict.reason}
            return [_ev("segment_retracted", segment=idx, reason=verdict.reason)]
        cites = [c.public() for c in verdict.citations]
        self.s.verdicts[idx] = {"text": text, "citations": cites}
        return [_ev("citation", segment=idx, index=i, citation=c) for i, c in enumerate(cites)]

    def feed(self, buf: str) -> list[Event]:
        """Re-parse the accumulated JSON. shortcut: O(n^2) over the answer; fine for answers of a few KB."""
        try:
            obj = from_json(buf, allow_partial="trailing-strings")
        except ValueError:
            return []
        segs = obj.get("segments") if isinstance(obj, dict) else None
        if not isinstance(segs, list):
            return []
        out: list[Event] = []
        for i, seg in enumerate(segs):
            if not isinstance(seg, dict):
                continue
            while len(self.s.streamed) <= i:
                self.s.streamed.append(0)
            text = str(seg.get("text", ""))
            if len(text) > self.s.streamed[i]:
                out.append(_ev("text_delta", segment=i, text=text[self.s.streamed[i] :]))
                self.s.streamed[i] = len(text)
            # A segment is complete once the next one has started.
            if i < len(segs) - 1 and i not in self.s.verdicts:
                out += self._close(i, seg)
        return out

    def finish(self, buf: str) -> tuple[str, list[Event]]:
        answer = AnswerOut.model_validate_json(buf)  # strict: malformed output raises
        out: list[Event] = []
        for i, seg in enumerate(answer.segments):
            text = seg.text
            if len(self.s.streamed) <= i:
                self.s.streamed.append(0)
            if len(text) > self.s.streamed[i]:
                out.append(_ev("text_delta", segment=i, text=text[self.s.streamed[i] :]))
                self.s.streamed[i] = len(text)
            if i not in self.s.verdicts:
                out += self._close(i, seg.model_dump())
        valid = [v for v in self.s.verdicts.values() if "text" in v]
        if answer.status == "insufficient_evidence" or not valid:
            status = "insufficient_evidence"
        elif len(valid) < len(answer.segments):
            status = "partial"
        else:
            status = answer.status
        return status, out


@traced("answer")
async def answer_stream(principal: Principal, document_id: uuid.UUID, question: str) -> AsyncIterator[Event]:
    s = get_settings()
    llm = get_llm()
    started = time.perf_counter()
    async with get_sessionmaker()() as db:
        doc = await db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.owner_id == principal.owner_id,
                Document.workspace_id == principal.workspace_id,
            )
        )
        if doc is None:
            yield _ev("error", code="not_found", message="Document not found.")
            return
        version = await db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == doc.id, DocumentVersion.version == doc.current_version
            )
        )
        if version is None or version.status != "ready":
            yield _ev("error", code="not_ready", message="This document is still being processed.")
            return

        prior = (
            await db.scalars(
                select(Message)
                .where(Message.document_id == doc.id, Message.owner_id == principal.owner_id)
                .order_by(Message.created_at.desc())
                .limit(s.history_turns)
            )
        ).all()
        history = [(m.role, m.content) for m in reversed(prior) if m.content]

        user_msg = Message(
            owner_id=principal.owner_id,
            workspace_id=principal.workspace_id,
            document_id=doc.id,
            version_id=version.id,
            role="user",
            content=question,
        )
        db.add(user_msg)
        db.add(
            AuditLog(
                owner_id=principal.owner_id,
                workspace_id=principal.workspace_id,
                actor=principal.actor,
                action="chat.ask",
                target=str(doc.id),
            )
        )
        await db.commit()

        got = await retrieve(
            db,
            principal,
            version.id,
            question,
            get_embedder(),
            s.full_context_token_budget,
            s.retrieval_top_k,
        )
        session = AnswerSession({b.block_id: _evidence_block(b) for b in got.blocks}, s.quote_fuzzy_min)
        assistant_id = uuid.uuid4()
        yield _ev(
            "meta",
            message_id=str(assistant_id),
            user_message_id=str(user_msg.id),
            route=got.route,
            model=llm.model_id,
            blocks=len(got.blocks),
        )

        usage: dict[str, Any] = {}
        buf = ""
        status = "error"
        error: dict[str, str] | None = None
        try:
            async for delta in llm.stream_json(SYSTEM, build_prompt(question, got.blocks, history), AnswerOut, usage):
                buf += delta
                for e in session.feed(buf):
                    yield e
            try:
                status, tail = session.finish(buf)
            except (ValidationError, ValueError):
                log.warning("llm_malformed_output", extra={"document_id": str(doc.id)})
                status, tail = (
                    "insufficient_evidence",
                    [
                        _ev("segment_retracted", segment=i, reason="malformed_output")
                        for i in range(len(session.s.streamed))
                        if i not in session.s.verdicts
                    ],
                )
            for e in tail:
                yield e
            closest: list[dict[str, Any]] = []
            if status == "insufficient_evidence":
                for b in await closest_blocks(db, principal, version.id, question):
                    closest.append(
                        {
                            "block_id": b.block_id,
                            "page": b.page,
                            "quote": b.content[:240],
                            "location": b.source_location,
                        }
                    )
            usage["total_ms"] = int((time.perf_counter() - started) * 1000)
            yield _ev("done", status=status, usage=usage, closest=closest)
        except Exception:  # provider failure: tell the client, keep the user's question
            log.exception("answer_failed", extra={"document_id": str(doc.id)})
            error = {
                "code": "llm_unavailable",
                "message": "The answer service is unavailable. Try again shortly.",
            }
            yield _ev("error", **error)
        finally:
            verdicts = session.s.verdicts
            segments = [verdicts[i] for i in sorted(verdicts) if "text" in verdicts[i]]
            db.add(
                Message(
                    id=assistant_id,
                    owner_id=principal.owner_id,
                    workspace_id=principal.workspace_id,
                    document_id=doc.id,
                    version_id=version.id,
                    role="assistant",
                    content=" ".join(seg["text"] for seg in segments),
                    status=status if error is None else "error",
                    segments=segments,
                    usage=usage,
                )
            )
            await db.commit()
            trace_metadata(
                document_id=str(doc.id),
                document_version=version.version,
                route=got.route,
                model=llm.model_id,
                status=status,
                citations_valid=sum(len(x["citations"]) for x in segments),
                citations_rejected=session.s.rejected,
                **{k: v for k, v in usage.items() if k != "model"},
            )
