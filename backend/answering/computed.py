"""Exact computations before answering, for formats that register a QueryTool (ADR-0006).

One planning call (document schema + question -> plan), then the plan runs over the original file in the parsing
sandbox. Each result is an extra evidence block, validated and located like any other block. Planning or running may
fail without failing the answer: the model then answers from the retrieved blocks alone, and the numeric check still
rejects any number no cited block contains.
"""

import asyncio
import logging
import time
from typing import Any

from backend.core.config import get_settings
from backend.core.models import Block, DocumentVersion
from backend.document_ir.models import ExtractLimits
from backend.extraction.registry import QueryTool
from backend.extraction.sandbox import run_sandboxed
from backend.llm.base import LLMProvider
from backend.observability.tracing import trace_metadata, traced
from backend.storage.local import get_storage

log = logging.getLogger(__name__)


@traced("compute")
async def computed_blocks(
    llm: LLMProvider,
    tool: QueryTool,
    version: DocumentVersion,
    question: str,
    history: list[tuple[str, str]],
    usage: dict[str, Any],
    model: str,
    thinking: str | None,
) -> list[Block]:
    """Evidence blocks computed for this question (never stored). Records counts and tokens in usage["computed"]."""
    s = get_settings()
    started = time.perf_counter()
    stats: dict[str, Any] = {"queries": 0, "results": 0}
    usage["computed"] = stats
    try:
        # Planning is a small structured task: the model's cheapest thinking level, or none when thinking is off.
        levels, _ = s.thinking_for(model)
        plan_usage: dict[str, Any] = {}
        buf = ""
        async for kind, delta in llm.stream_json(
            tool.plan_system,
            tool.plan_prompt(version.meta or {}, question, history),
            tool.plan_schema,
            plan_usage,
            model=model,
            thinking=levels[0] if thinking and levels else None,
        ):
            if kind == "text":
                buf += delta
        stats.update(input_tokens=plan_usage.get("input_tokens", 0), output_tokens=plan_usage.get("output_tokens", 0))
        plan = tool.plan_schema.model_validate_json(buf).model_dump()  # malformed plans raise: no computation
        stats["queries"] = len(plan.get("queries") or [])
        if not stats["queries"]:
            return []
        limits = ExtractLimits(max_pages=s.max_pages, max_chars=s.max_text_chars)
        with get_storage().local_path(version.storage_key) as path:
            results = await asyncio.to_thread(
                run_sandboxed, tool.run, path, plan, limits, timeout_s=s.query_timeout_s, mem_mb=s.parse_memory_mb
            )
        stats["results"] = len(results)
        return [
            Block(
                owner_id=version.owner_id,
                workspace_id=version.workspace_id,
                version_id=version.id,
                block_id=b.block_id,
                ordinal=b.ordinal,
                page=None,
                type=b.type,
                content=b.content,
                source_location=b.source_location.model_dump(),
                format_metadata=b.format_metadata,
                confidence=None,
                section_path=b.section_path,
                token_estimate=b.token_estimate,
            )
            for b in results
        ]
    except Exception as e:  # noqa: BLE001 - computing is an aid: the answer goes on without it
        stats["error"] = type(e).__name__
        log.warning("compute_failed", extra={"version_id": str(version.id), "reason": type(e).__name__})
        return []
    finally:
        stats["ms"] = int((time.perf_counter() - started) * 1000)
        trace_metadata(computed_queries=stats["queries"], computed_results=stats["results"], computed_ms=stats["ms"])
