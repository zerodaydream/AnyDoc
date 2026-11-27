"""Streamed answers with per-segment citation validation (ADR-0002).

Events: meta, text_delta, citation, segment_retracted, suggestion, web_searching, web, done, error.
The suggestion is an uncited next-step hint, sent only for answers that cite something.
When the document can't answer (or the model asks for a web query) and WEB_SEARCH_ENABLED is on, the web search
tool runs (answering/web.py), except for questions the table planner turned into queries over the file's rows.
Its result is a separate `web` event, never mixed into the document answer or its citations.
Text streams immediately; a citation is emitted only after it validates; a segment whose
evidence fails is retracted. Locations come from the IR, never from the model.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anyio
from pydantic import ValidationError
from pydantic_core import from_json
from sqlalchemy import func, select

from backend.answering.computed import computed_blocks
from backend.answering.web import web_lookup
from backend.core.config import get_settings
from backend.core.db import get_sessionmaker
from backend.core.errors import TransientError
from backend.core.models import AuditLog, Block, ChatSession, Document, DocumentVersion, Message
from backend.extraction.registry import describe, query_tool
from backend.grounding.validator import EvidenceBlock, validate_segment
from backend.indexing.embeddings import get_embedder
from backend.llm.base import AnswerOut, UnsupportedOption, WebResult
from backend.llm.factory import get_llm
from backend.llm.prompts import SYSTEM, build_prompt
from backend.observability.tracing import trace_metadata, traced
from backend.retrieval.retriever import Retrieved, closest_blocks, retrieve
from backend.security.auth import Principal
from backend.websearch.factory import get_web_search

log = logging.getLogger(__name__)
Event = dict[str, Any]


def session_title(question: str, limit: int = 80) -> str:
    """First question, cut at a word boundary. shortcut: no LLM title; add one if titles read poorly."""
    q = " ".join(question.split())
    return q if len(q) <= limit else q[:limit].rsplit(" ", 1)[0] + "…"


_MAX_SUGGESTION = 400
_MAX_WEB_QUERY = 300
_ALIAS_REF = re.compile(r"\b[Bb]lock\s+b(\d+)\b")


def _alias_ref(aliased: list[tuple[str, Block]], m: re.Match[str]) -> str:
    """Thought summaries mention internal aliases ("Block b130"); show readers where the passage is instead."""
    i = int(m.group(1))
    return f"the passage on {describe(aliased[i][1].source_location)}" if i < len(aliased) else "a passage"


def _ev(event: str, **data: Any) -> Event:
    return {"event": event, "data": data}


def _evidence_block(b: Block) -> EvidenceBlock:
    return EvidenceBlock(b.block_id, b.source_location["kind"], b.content, b.page, b.format_metadata, b.confidence)


@dataclass(slots=True)
class _State:
    streamed: list[int] = field(default_factory=list)  # chars of text emitted per segment
    verdicts: dict[int, dict[str, Any]] = field(default_factory=dict)  # idx -> {text, citations} | {retracted}
    rejected: int = 0
    suggestion: str | None = None  # uncited next-step hint; kept only for answers that cite something
    web_query: str = ""  # model's search query for what the blocks couldn't answer


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
            # A segment is complete once the next one (or the suggestion after the list) has started.
            if (i < len(segs) - 1 or "suggestion" in obj) and i not in self.s.verdicts:
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
        self.s.web_query = " ".join(answer.web_query.split())[:_MAX_WEB_QUERY]
        tip = " ".join(answer.suggestion.split())[:_MAX_SUGGESTION]
        if tip and status != "insufficient_evidence":
            self.s.suggestion = tip
            out.append(_ev("suggestion", text=tip))
        return status, out


# Shown to the reader as-is, live and in history. Plain words, what happened, what to do next.
_ERRORS: dict[str, dict[str, str]] = {
    "llm_busy": {
        "code": "llm_busy",
        "message": "The AI model is busy right now. Your question is saved, so try asking again in a moment.",
    },
    "answer_failed": {
        "code": "answer_failed",
        "message": "Something went wrong while answering. Your question is saved, so try asking again.",
    },
}


@traced("answer")
async def answer_stream(
    principal: Principal,
    session_id: uuid.UUID,
    question: str,
    model: str | None = None,
    thinking: str | None = None,
) -> AsyncIterator[Event]:
    """`model` / `thinking` must already be validated against the configured allow-lists."""
    s = get_settings()
    llm = get_llm()
    started = time.perf_counter()
    async with get_sessionmaker()() as db:
        row = (
            await db.execute(
                select(ChatSession, Document)
                .join(Document, Document.id == ChatSession.document_id)
                .where(
                    ChatSession.id == session_id,
                    ChatSession.owner_id == principal.owner_id,
                    ChatSession.workspace_id == principal.workspace_id,
                )
            )
        ).first()
        if row is None:
            yield _ev("error", code="not_found", message="Conversation not found.")
            return
        chat, doc = row
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
                # Context is this conversation only: other sessions on the same document are never shared.
                .where(Message.session_id == chat.id, Message.owner_id == principal.owner_id)
                .order_by(Message.created_at.desc())
                .limit(s.history_turns)
            )
        ).all()
        history = [(m.role, m.content) for m in reversed(prior) if m.content]

        user_msg = Message(
            owner_id=principal.owner_id,
            workspace_id=principal.workspace_id,
            session_id=chat.id,
            version_id=version.id,
            role="user",
            content=question,
        )
        db.add(user_msg)
        chat.updated_at = func.now()
        if not chat.title:
            chat.title = session_title(question)
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

        # Everything after the question is saved runs inside the try below, so every question gets an assistant
        # message (an answer, a stop, or a readable error), even if retrieval itself fails.
        assistant_id = uuid.uuid4()
        usage: dict[str, Any] = {"thinking_level": thinking}
        buf = ""
        reasoning: list[str] = []  # model's thought summaries: shown as reasoning, never as evidence
        think_started: float | None = None
        status = "error"
        error: dict[str, str] | None = None
        web: WebResult | None = None
        got: Retrieved | None = None
        session = AnswerSession({}, s.quote_fuzzy_min)
        meta_sent = False
        try:
            got = await retrieve(
                db,
                principal,
                version.id,
                question,
                get_embedder(),
                s.context_budget(model or llm.model_id),
                s.retrieval_top_k,
            )
            # Tabular formats: exact results computed over the whole file go first (ADR-0006).
            tool = query_tool(version.detected_format)
            computed = (
                await computed_blocks(llm, tool, version, question, history, usage, model or llm.model_id, thinking)
                if tool
                else []
            )
            # Model sees b0, b1, ...: it truncated long ids like pdf:8:7:38b2d058 in live tests.
            aliased = [(f"b{i}", b) for i, b in enumerate([*computed, *got.blocks])]
            session = AnswerSession({a: _evidence_block(b) for a, b in aliased}, s.quote_fuzzy_min)
            meta_sent = True
            yield _ev(
                "meta",
                message_id=str(assistant_id),
                user_message_id=str(user_msg.id),
                route=got.route,
                model=model or llm.model_id,
                thinking=thinking,
                blocks=len(aliased),
            )
            prompt = build_prompt(question, aliased, history)
            for attempt in range(2):
                # Thinking time = request start to first answer text (summaries often arrive in one late chunk).
                think_started = time.perf_counter() if thinking else None
                try:
                    async for kind, delta in llm.stream_json(
                        SYSTEM, prompt, AnswerOut, usage, model=model, thinking=thinking
                    ):
                        if kind == "thought":
                            delta = _ALIAS_REF.sub(lambda m: _alias_ref(aliased, m), delta)
                            reasoning.append(delta)
                            yield _ev("thinking_delta", text=delta)
                            continue
                        if think_started is not None and reasoning and "thinking_ms" not in usage:
                            usage["thinking_ms"] = int((time.perf_counter() - think_started) * 1000)
                        buf += delta
                        for e in session.feed(buf):
                            yield e
                    break
                except TransientError:
                    if attempt == 1:
                        raise
                    # Mid-stream provider failure: tell the client to drop partial text, then start over once.
                    log.warning("answer_stream_restart", extra={"document_id": str(doc.id)})
                    session = AnswerSession(session.blocks, session.fuzzy_min)
                    buf, reasoning, think_started = "", [], None
                    usage.pop("thinking_ms", None)
                    yield _ev("reset")
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
                            "ref": describe(b.source_location),
                            "quote": b.content[:240],
                            "location": b.source_location,
                        }
                    )
            # A question the table planner turned into queries is about this file's own rows: the web can't know
            # them, so a failed or empty computation never falls back to a web search.
            about_rows = bool((usage.get("computed") or {}).get("queries"))
            if s.web_search_enabled and not about_rows and (status == "insufficient_evidence" or session.s.web_query):
                query = session.s.web_query or " ".join(question.split())[:_MAX_WEB_QUERY]
                yield _ev("web_searching", query=query)
                web = await web_lookup(
                    llm, get_web_search(), question, query, doc.title, usage, model or llm.model_id, thinking
                )
                yield _ev("web", **web.model_dump())
            usage["total_ms"] = int((time.perf_counter() - started) * 1000)
            yield _ev("done", status=status, usage=usage, closest=closest)
        except (asyncio.CancelledError, GeneratorExit):
            # The reader pressed Stop (client disconnected). Keep only what was verified; never show the rest.
            status = "stopped"
            for i in range(len(session.s.streamed)):
                session.s.verdicts.setdefault(i, {"retracted": "stopped"})
            log.info("answer_stopped", extra={"document_id": str(doc.id)})
            raise
        except Exception as e:  # tell the client in plain words, keep the user's question
            if isinstance(e, UnsupportedOption):
                error = {"code": "unsupported_option", "message": f"{e} Pick another model or thinking level."}
            else:
                log.exception("answer_failed", extra={"document_id": str(doc.id)})
                error = _ERRORS["llm_busy" if isinstance(e, TransientError) else "answer_failed"]
            if not meta_sent:  # failed before retrieval finished: the client still needs this reply's id
                yield _ev("meta", message_id=str(assistant_id), user_message_id=str(user_msg.id), route=None, blocks=0)
            # Text already streamed but never validated must not stay on screen as an answer.
            for i in range(len(session.s.streamed)):
                if i not in session.s.verdicts:
                    session.s.verdicts[i] = {"retracted": "interrupted"}
                    yield _ev("segment_retracted", segment=i, reason="interrupted")
            yield _ev("error", **error)
        finally:
            if error is not None:
                usage["error"] = error  # our own wording, never document text: history shows it again
            verdicts = session.s.verdicts
            segments = [verdicts[i] for i in sorted(verdicts) if "text" in verdicts[i]]
            db.add(
                Message(
                    id=assistant_id,
                    owner_id=principal.owner_id,
                    workspace_id=principal.workspace_id,
                    session_id=chat.id,
                    version_id=version.id,
                    role="assistant",
                    content=" ".join(seg["text"] for seg in segments),
                    status=status if error is None else "error",
                    segments=segments,
                    usage=usage,
                    reasoning="".join(reasoning) or None,
                    suggestion=session.s.suggestion if error is None and status != "stopped" else None,
                    web=web.model_dump() if web is not None and status != "stopped" else None,
                )
            )
            # Shielded: a stopped (cancelled) request must still record its answer, or the question is left
            # without one in the conversation.
            with anyio.CancelScope(shield=True):
                await db.commit()
            trace_metadata(
                document_id=str(doc.id),
                document_version=version.version,
                route=got.route if got else None,
                status=status,
                citations_valid=sum(len(x["citations"]) for x in segments),
                citations_rejected=session.s.rejected,
                web_status=web.status if web else None,
                **{k: v for k, v in usage.items() if k not in ("model", "error")},
            )
