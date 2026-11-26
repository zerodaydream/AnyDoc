"""Gemini provider retries transient errors via the SDK's backoff (no network: the HTTP layer is patched)."""

from typing import Any

import pytest
import tenacity
from google.genai import errors

from backend.llm.providers.gemini.provider import GeminiProvider


def _provider(monkeypatch: pytest.MonkeyPatch, codes: list[int]) -> tuple[GeminiProvider, list[int]]:
    p = GeminiProvider(api_key="test", model_id="m", fast_model_id="m", timeout_s=5)
    api = p._client._api_client
    calls: list[int] = []

    async def once(*_: Any, **__: Any) -> Any:
        calls.append(1)
        code = codes[len(calls) - 1]
        raise errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})

    monkeypatch.setattr(api, "_async_request_once", once)
    monkeypatch.setattr(api._async_retry, "wait", tenacity.wait_none())  # keep the test fast
    return p, calls


async def test_retries_transient_up_to_five_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    p, calls = _provider(monkeypatch, [503] * 5)
    with pytest.raises(errors.APIError):
        await p._client.aio.models.generate_content(model="m", contents="hi")
    assert len(calls) == 5


async def test_does_not_retry_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    p, calls = _provider(monkeypatch, [400])
    with pytest.raises(errors.APIError):
        await p._client.aio.models.generate_content(model="m", contents="hi")
    assert len(calls) == 1


def test_backoff_is_exponential_with_jitter() -> None:
    p = GeminiProvider(api_key="test", model_id="m", fast_model_id="m", timeout_s=5)
    wait = p._client._api_client._async_retry.wait
    assert isinstance(wait, tenacity.wait_exponential_jitter)
    assert (wait.initial, wait.max, wait.exp_base, wait.jitter) == (1.0, 60.0, 2, 1.0)
