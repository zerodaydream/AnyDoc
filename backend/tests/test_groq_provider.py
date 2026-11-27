"""Groq provider through the real SDK, with the HTTP layer mocked (no network, no key)."""

import json
from collections.abc import Callable, Coroutine
from typing import Any

import groq
import httpx
import pytest

from backend.core.errors import TransientError
from backend.llm.base import AnswerOut, UnsupportedOption
from backend.llm.providers.fake import FakeProvider
from backend.llm.providers.groq.provider import GroqProvider

Handler = Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]


def _provider(handler: Handler) -> GroqProvider:
    p = GroqProvider(api_key="test", model_id="qwen/qwen3.8-27b", fast_model_id="qwen/qwen3.8-27b", timeout_s=5)
    p._client = groq.AsyncGroq(
        api_key="test", max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return p


def _completion(content: str, reasoning: str | None = None) -> httpx.Response:
    message = {"role": "assistant", "content": content, **({"reasoning": reasoning} if reasoning else {})}
    details = {"completion_tokens_details": {"reasoning_tokens": 17}} if reasoning else {}
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "qwen/qwen3.8-27b",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150, **details},
        },
    )


def _error(status: int) -> Handler:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "x", "type": "x"}})

    return handler


async def test_answer_is_one_json_mode_call_with_the_schema_in_the_prompt() -> None:
    sent: list[dict[str, Any]] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return _completion('{"status":"insufficient_evidence","segments":[]}')

    usage: dict[str, Any] = {}
    deltas = [d async for d in _provider(handler).stream_json("SYS", "Q", AnswerOut, usage)]

    assert deltas == [("text", '{"status":"insufficient_evidence","segments":[]}')]
    body = sent[0]
    assert body["response_format"] == {"type": "json_object"} and body["temperature"] == 0.0
    assert body["model"] == "qwen/qwen3.8-27b" and "stream" not in body
    assert "reasoning_effort" not in body  # thinking off: nothing sent, so direct models answer directly
    system = body["messages"][0]["content"]
    assert system.startswith("SYS") and '"web_query"' in system  # full schema, every property
    assert usage["model"] == "qwen/qwen3.8-27b" and (usage["input_tokens"], usage["output_tokens"]) == (120, 30)


async def test_thinking_sends_the_level_and_shows_the_reasoning_first() -> None:
    sent: list[dict[str, Any]] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return _completion('{"status":"insufficient_evidence","segments":[]}', reasoning="91 = 7 x 13.")

    usage: dict[str, Any] = {}
    deltas = [d async for d in _provider(handler).stream_json("S", "Q", AnswerOut, usage, thinking="low")]
    assert sent[0]["reasoning_effort"] == "low"
    assert deltas == [("thought", "91 = 7 x 13."), ("text", '{"status":"insufficient_evidence","segments":[]}')]
    assert usage["thinking_tokens"] == 17


async def test_reasoning_stays_hidden_when_thinking_is_off() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:  # gpt-oss reasons even when not asked
        return _completion("{}", reasoning="hidden")

    assert [d async for d in _provider(handler).stream_json("S", "Q", AnswerOut, {})] == [("text", "{}")]


@pytest.mark.parametrize(
    ("status", "raised"),
    [
        (429, TransientError),
        (498, TransientError),
        (503, TransientError),
        (413, UnsupportedOption),
        (400, UnsupportedOption),
    ],
)
async def test_errors_map_to_engine_exceptions(status: int, raised: type[Exception]) -> None:
    with pytest.raises(raised):
        [d async for d in _provider(_error(status)).stream_json("S", "Q", AnswerOut, {})]


async def test_bad_key_is_not_retried_or_hidden() -> None:
    with pytest.raises(groq.AuthenticationError):
        [d async for d in _provider(_error(401)).stream_json("S", "Q", AnswerOut, {})]


async def test_describe_models_reads_limits_from_one_list_call() -> None:
    paths: list[str] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)  # never /models/qwen%2F...: Groq 404s on the encoded "/"
        model = {"id": "qwen/qwen3.8-27b", "object": "model", "created": 0, "owned_by": "Alibaba"}
        return httpx.Response(
            200, json={"object": "list", "data": [{**model, "context_window": 131072, "max_completion_tokens": 16384}]}
        )

    p = _provider(handler)
    ok, gone = await p.describe_models(["qwen/qwen3.8-27b", "gone"])
    assert ok == {
        "id": "qwen/qwen3.8-27b",
        "name": "qwen/qwen3.8-27b",
        "input_token_limit": 131072,
        "output_token_limit": 16384,
        "thinking": True,  # the config's levels decide what the picker offers
        "available": True,
    }
    assert gone["available"] is False and paths == ["/openai/v1/models"]
    await p.describe_models(["qwen/qwen3.8-27b"])
    assert len(paths) == 1  # cached


async def test_check_fails_loudly_on_a_missing_model() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "list", "data": []})

    with pytest.raises(RuntimeError, match="no access"):
        await _provider(handler).check()


def test_factory_routes_only_providers_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings
    from backend.llm.factory import get_llm
    from backend.llm.router import RoutedProvider

    monkeypatch.setenv("LLM_PROVIDER", "gemini")  # conftest forces "fake"

    def build(gemini: str, groq_key: str) -> Any:
        monkeypatch.setenv("GEMINI_API_KEY", gemini)
        monkeypatch.setenv("GROQ_API_KEY", groq_key)
        get_settings.cache_clear()
        get_llm.cache_clear()
        return get_llm()

    assert isinstance(build("", ""), FakeProvider)
    only_groq = build("", "gsk_test")
    assert isinstance(only_groq, RoutedProvider) and list(only_groq._providers) == ["groq"]
    both = build("g_test", "gsk_test")
    assert isinstance(both, RoutedProvider) and list(both._providers) == ["gemini", "groq"]
    assert isinstance(both._pick("qwen/qwen3.8-27b"), GroqProvider)
    get_settings.cache_clear()
    get_llm.cache_clear()


async def test_cited_answer_end_to_end(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine validates Groq's one-shot answer like any other: citations resolve against the document."""
    from backend.answering import engine
    from backend.tests.test_api import _ready_doc, _sse

    async def handler(req: httpx.Request) -> httpx.Response:
        prompt = json.loads(req.content)["messages"][1]["content"]
        raw = "".join([t async for _, t in FakeProvider().stream_json("", prompt, AnswerOut, {})])
        return _completion(raw)

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: _provider(handler))
    events = _sse(
        (await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "third quarter revenue"})).text
    )
    kinds = [k for k, _ in events]
    assert "citation" in kinds and kinds[-1] == "done" and events[-1][1]["status"] == "answered"


def test_picker_tabs_list_each_providers_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import Settings

    monkeypatch.setenv("LLM_PROVIDER", "gemini")  # conftest forces "fake"
    monkeypatch.setenv("MODELS_ENABLED", '{"gemini-x": "low,high*"}')
    monkeypatch.setenv("GROQ_MODELS_ENABLED", '{"qwen/qwen3.8-27b": "off*,low,high", "openai/gpt-oss-20b": ""}')
    monkeypatch.setenv("GEMINI_API_KEY", "g_test")
    assert Settings().providers == ["gemini"]  # no Groq key: no Groq tab

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    s = Settings()
    assert s.providers == ["gemini", "groq"]
    assert s.allowed_models[-2:] == ["qwen/qwen3.8-27b", "openai/gpt-oss-20b"] and "gemini-x" in s.allowed_models
    assert s.provider_for("openai/gpt-oss-20b") == "groq" and s.provider_for("gemini-x") == "gemini"
    assert s.default_model == s.llm_answer_model
    assert s.thinking_for("openai/gpt-oss-20b")[0] == [] and s.thinking_for("gemini-x")[0] == ["low", "high"]
    # Qwen thinks on request and answers directly by default.
    assert s.thinking_for("qwen/qwen3.8-27b") == (["low", "high"], "off")
    assert s.context_budget("qwen/qwen3.8-27b") == 4000  # Groq free plan: 7,000 input tokens a minute
    assert s.context_budget("gemini-x") == s.full_context_token_budget

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert Settings().default_model == "qwen/qwen3.8-27b"  # LLM_PROVIDER picks the default tab


async def test_router_sends_each_call_to_the_models_provider() -> None:
    from backend.llm.router import RoutedProvider

    calls: list[tuple[str, str | None]] = []

    class Stub(FakeProvider):
        def __init__(self, name: str) -> None:
            self.name = name

        async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
            calls.append((self.name, ",".join(model_ids)))
            return [{"id": m, "by": self.name} for m in model_ids]

    r = RoutedProvider(
        {"gemini": Stub("gemini"), "groq": Stub("groq")}, lambda m: "groq" if "llama" in m else "gemini", "g1"
    )
    metas = await r.describe_models(["g1", "llama-a", "g2"])
    assert [(m["id"], m["by"]) for m in metas] == [("g1", "gemini"), ("llama-a", "groq"), ("g2", "gemini")]
    assert calls == [("gemini", "g1,g2"), ("groq", "llama-a")]
    assert [d async for d in r.stream_json("s", "q", AnswerOut, {}, model="llama-a")]  # Groq's stub answers


async def test_off_by_default_reaches_the_picker_and_the_answer(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings
    from backend.tests.test_api import _ready_doc, _sse

    s = get_settings()
    monkeypatch.setattr(s, "models_enabled", {s.llm_answer_model: "off*,low,high", "no-levels": ""})
    models = {m["id"]: m for m in (await client.get("/api/models")).json()["models"]}
    assert models[s.llm_answer_model]["default_thinking"] == "off" and models[s.llm_answer_model]["thinking"]
    assert models["no-levels"]["thinking"] is False and models["no-levels"]["thinking_levels"] == []

    doc = await _ready_doc(client)
    ask = f"/api/sessions/{doc['sid']}/messages"
    kinds = [k for k, _ in _sse((await client.post(ask, json={"question": "third quarter revenue"})).text)]
    assert "thinking_delta" not in kinds and kinds[-1] == "done"  # the fake model thinks only when asked
    kinds = [k for k, _ in _sse((await client.post(ask, json={"question": "revenue", "thinking": "low"})).text)]
    assert "thinking_delta" in kinds
