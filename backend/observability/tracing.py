"""Tracing boundary. Business code uses @traced / trace_metadata only; LangSmith stays in here.

Default: inputs and outputs are hidden; only metadata (ids, scores, timings, tokens) is sent.
TRACE_CONTENT=true opts in to full content for dev test documents.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar, cast

from backend.core.config import get_settings

log = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


@lru_cache
def _client() -> Any | None:
    s = get_settings()
    if not (s.langsmith_tracing and s.langsmith_api_key):
        return None
    try:
        from langsmith import Client
        from langsmith.anonymizer import create_secret_anonymizer

        hide = not s.trace_content
        return Client(
            api_key=s.langsmith_api_key,
            hide_inputs=hide,
            hide_outputs=hide,
            anonymizer=create_secret_anonymizer(),
        )
    except Exception:  # tracing must never break the app
        log.warning("langsmith_init_failed", exc_info=True)
        return None


def traced(name: str, run_type: str = "chain") -> Callable[[F], F]:
    def deco(fn: F) -> F:
        client = _client()
        if client is None:
            return fn
        from langsmith import traceable

        wrap: Any = traceable(
            name=name,
            run_type=run_type,
            client=client,  # type: ignore[call-overload]
            project_name=get_settings().langsmith_project,
        )
        return cast(F, wrap(fn))

    return deco


def trace_metadata(**kv: Any) -> None:
    """Attach metadata to the current run. Never pass document text here."""
    if _client() is None:
        return
    try:
        from langsmith import get_current_run_tree

        run = get_current_run_tree()
        if run is not None:
            run.metadata.update(kv)
    except Exception:
        log.debug("trace_metadata_failed", exc_info=True)
