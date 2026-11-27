import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest

from backend.api.app import app
from backend.ingestion.pipeline import ingest
from backend.security.auth import Principal, get_principal
from backend.tests.pdfgen import sample_report

pytestmark = pytest.mark.usefixtures("database")


async def _upload(client: Any, data: bytes, name: str = "report.pdf") -> dict[str, Any]:
    r = await client.post("/api/documents", params={"filename": name}, content=data)
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


async def _ready_doc(client: Any) -> dict[str, Any]:
    doc = await _upload(client, sample_report())
    assert doc["status"] == "queued"
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "ready", doc
    return {**doc, "sid": await _session(client, doc["id"])}


async def _session(client: Any, document_id: str) -> str:
    r = await client.post("/api/sessions", json={"document_id": document_id})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for frame in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


async def test_upload_ingest_ask_cite(client: Any) -> None:
    doc = await _ready_doc(client)
    assert doc["page_count"] == 2 and doc["format"] == "pdf"

    r = await client.get(doc["file_url"], headers={"Range": "bytes=0-7"})
    assert r.status_code == 206 and r.content == b"%PDF-1.7"

    r = await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "What was third quarter revenue?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert events[0][1]["route"] == "full_context"
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["page"] == 1 and cite["location"]["kind"] == "pdf"
    assert cite["block_id"].startswith("pdf:1:")  # alias shown to the model mapped back to the real id
    assert cite["location"]["regions"][0]["rects"]
    assert events[-1][1]["status"] == "answered"
    tip = next(d["text"] for k, d in events if k == "suggestion")

    hist = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[1]["suggestion"] == tip and hist[0]["suggestion"] is None
    assert hist[1]["segments"][0]["citations"][0]["block_id"] == cite["block_id"]


async def test_hybrid_route_when_over_budget(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings

    doc = await _ready_doc(client)
    ask = f"/api/sessions/{doc['sid']}/messages"
    monkeypatch.setattr(get_settings(), "full_context_token_budget", 30)  # the sample is 62 tokens
    events = _sse((await client.post(ask, json={"question": "fourth quarter revenue outlook"})).text)
    assert events[0][1]["route"] == "hybrid"
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["page"] == 2

    # The budget also caps what passage search sends (Groq's free plan): best hits first, never nothing.
    monkeypatch.setattr(get_settings(), "full_context_token_budget", 1)
    events = _sse((await client.post(ask, json={"question": "fourth quarter revenue outlook"})).text)
    assert events[0][1]["route"] == "hybrid" and events[0][1]["blocks"] == 1


async def test_owner_scoping(client: Any) -> None:
    doc = await _ready_doc(client)
    other = Principal(uuid.uuid4(), uuid.uuid4(), "intruder")
    app.dependency_overrides[get_principal] = lambda: other
    try:
        for path in ("", "/file", "/outline"):
            assert (await client.get(f"/api/documents/{doc['id']}{path}")).status_code == 404
        assert (await client.get(f"/api/sessions/{doc['sid']}/messages")).status_code == 404
        assert (await client.patch(f"/api/sessions/{doc['sid']}", json={"title": "x"})).status_code == 404
        assert (await client.delete(f"/api/sessions/{doc['sid']}")).status_code == 404
        assert (await client.post("/api/sessions", json={"document_id": doc["id"]})).status_code == 404
        assert all(x["id"] != doc["sid"] for x in (await client.get("/api/sessions")).json())
        r = await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "revenue?"})
        assert _sse(r.text)[0][0] == "error"
        assert all(d["id"] != doc["id"] for d in (await client.get("/api/documents")).json())
    finally:
        app.dependency_overrides.clear()


async def test_malformed_pdf_fails_gracefully(client: Any) -> None:
    doc = await _upload(client, b"%PDF-1.7\n" + b"\x00garbage" * 200, "broken.pdf")
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "failed"
    assert doc["error"]["code"] == "malformed_pdf"
    doc["sid"] = await _session(client, doc["id"])
    r = await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "anything"})
    assert _sse(r.text)[0] == (
        "error",
        {"code": "not_ready", "message": "This document is still being processed."},
    )


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("x.pdf", b"PK\x03\x04notpdf", "type_mismatch"),
        ("x.exe", b"MZ\x90\x00", "unsupported_format"),
        ("x.txt", b"", "empty_file"),
        ("x.pdf", b"", "empty_file"),
    ],
)
async def test_upload_validation(client: Any, name: str, data: bytes, code: str) -> None:
    r = await client.post("/api/documents", params={"filename": name}, content=data)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


async def test_cancel_and_retry(client: Any) -> None:
    doc = await _upload(client, sample_report())
    r = await client.post(f"/api/documents/{doc['id']}/cancel")
    assert r.status_code == 202 and r.json()["status"] == "cancelled"
    await ingest(uuid.UUID(client.enqueued[-1]))  # late job is a no-op
    assert (await client.get(f"/api/documents/{doc['id']}")).json()["status"] == "cancelled"
    r = await client.post(f"/api/documents/{doc['id']}/retry")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    await ingest(uuid.UUID(client.enqueued[-1]))
    assert (await client.get(f"/api/documents/{doc['id']}")).json()["status"] == "ready"
    assert (await client.post(f"/api/documents/{doc['id']}/cancel")).status_code == 409


async def test_abort_while_processing(client: Any) -> None:
    doc = await _upload(client, sample_report())
    await ingest(uuid.UUID(client.enqueued[-1]), should_abort=lambda: True)
    assert (await client.get(f"/api/documents/{doc['id']}")).json()["status"] == "cancelled"


async def test_stream_failure_retracts_unvalidated_text(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine
    from backend.core.errors import TransientError

    class Flaky:
        model_id = "flaky"

        async def stream_json(self, system: str, prompt: str, schema: object, usage: dict[str, Any], **kw: Any) -> Any:
            yield ("text", '{"status":"answered","segments":[{"text":"Unverified claim')
            raise TransientError("gemini 503")

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: Flaky())
    events = _sse((await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "revenue?"})).text)
    kinds = [k for k, _ in events]
    assert kinds.index("segment_retracted") < kinds.index("error")
    assert ("segment_retracted", {"segment": 0, "reason": "interrupted"}) in events
    assistant = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()[-1]
    assert assistant["status"] == "error" and assistant["segments"] == [] and assistant["content"] == ""
    assert assistant["error"].startswith("The AI model is busy right now.")


async def test_retrieval_failure_still_saves_a_readable_reply(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine

    async def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("embedder exploded")

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "retrieve", broken)
    events = _sse((await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "hi"})).text)
    assert [k for k, _ in events] == ["meta", "error"]
    msgs = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]  # every question gets a reply
    assert msgs[1]["id"] == events[0][1]["message_id"] and msgs[1]["status"] == "error"
    assert msgs[1]["error"] == events[1][1]["message"]
    assert "embedder" not in msgs[1]["error"]  # internals never reach the reader


def test_cors_origins_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


async def test_mid_stream_failure_restarts_once(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine
    from backend.core.errors import TransientError
    from backend.llm.providers.fake import FakeProvider

    fake, calls = FakeProvider(), []

    class FlakyOnce:
        model_id = "flaky-once"

        async def stream_json(self, system: str, prompt: str, schema: Any, usage: dict[str, Any], **kw: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                yield ("text", '{"status":"answered","segments":[{"text":"Partial')
                raise TransientError("503")
            async for d in fake.stream_json(system, prompt, schema, usage, **kw):
                yield d

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: FlakyOnce())
    events = _sse(
        (await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "third quarter revenue"})).text
    )
    kinds = [k for k, _ in events]
    assert "reset" in kinds and kinds[-1] == "done" and events[-1][1]["status"] == "answered"
    after = kinds[kinds.index("reset") :]
    assert "citation" in after and "segment_retracted" not in kinds


async def test_sessions_do_not_share_context(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine
    from backend.llm.providers.fake import FakeProvider

    prompts: list[str] = []
    fake = FakeProvider()

    class Spy:
        model_id = "spy"

        async def stream_json(self, system: str, prompt: str, schema: Any, usage: dict[str, Any], **kw: Any) -> Any:
            prompts.append(prompt)
            async for d in fake.stream_json(system, prompt, schema, usage, **kw):
                yield d

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: Spy())
    other = await _session(client, doc["id"])
    await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "zebra third quarter revenue?"})
    await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "and operating costs?"})
    await client.post(f"/api/sessions/{other}/messages", json={"question": "fourth quarter outlook?"})
    assert "zebra" in prompts[1]  # follow-up sees its own session's history
    assert "zebra" not in prompts[2]  # a new session on the same document starts clean
    assert len((await client.get(f"/api/sessions/{other}/messages")).json()) == 2

    listed = {x["id"]: x for x in (await client.get("/api/sessions")).json()}
    assert listed[doc["sid"]]["title"] == "zebra third quarter revenue?"
    assert listed[other]["document_title"] == "report"
    assert list(listed)[0] == other  # most recently active first


async def test_rename_and_delete_session(client: Any) -> None:
    doc = await _ready_doc(client)
    await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "revenue?"})
    r = await client.patch(f"/api/sessions/{doc['sid']}", json={"title": "  Q3   numbers "})
    assert r.json()["title"] == "Q3 numbers"
    assert (await client.delete(f"/api/sessions/{doc['sid']}")).status_code == 204
    assert (await client.get(f"/api/sessions/{doc['sid']}/messages")).status_code == 404
    assert (await client.get(f"/api/documents/{doc['id']}")).json()["status"] == "ready"  # document kept


async def test_outline_lists_headings(client: Any) -> None:
    doc = await _ready_doc(client)
    items = (await client.get(f"/api/documents/{doc['id']}/outline")).json()
    assert [(i["text"], i["page"]) for i in items] == [("Quarterly Report", 1), ("Outlook", 2)]
    assert items[0]["location"]["kind"] == "pdf"


def test_session_title_cuts_at_word_boundary() -> None:
    from backend.answering.engine import session_title

    assert session_title("short  question ") == "short question"
    t = session_title("word " * 40)
    assert t.endswith("…") and len(t) <= 81 and not t.endswith(" …")


async def test_models_endpoint_lists_env_choices(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "models_enabled", {"gemini-x": "low,high*", s.llm_answer_model: ""})
    monkeypatch.setattr(s, "llm_thinking_levels", ["LOW", "high"])
    body = (await client.get("/api/models")).json()
    assert [m["id"] for m in body["models"]] == [s.llm_answer_model, "gemini-x"]  # default first, no duplicates
    assert body["thinking_levels"] == ["low", "high"]
    assert body["max_question_chars"] == s.max_question_chars
    assert body["models"][0]["input_token_limit"] > 0


@pytest.mark.parametrize(
    "payload",
    [{"question": "q", "model": "not-enabled"}, {"question": "q", "thinking": "ultra"}, {"question": "x" * 5000}],
)
async def test_ask_rejects_options_outside_allow_lists(client: Any, payload: dict[str, Any]) -> None:
    doc = await _ready_doc(client)
    assert (await client.post(f"/api/sessions/{doc['sid']}/messages", json=payload)).status_code == 422


async def test_thinking_streams_and_persists(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine
    from backend.llm.providers.fake import FakeProvider

    seen: dict[str, Any] = {}
    fake = FakeProvider()

    class Spy:
        model_id = "spy"

        async def stream_json(self, system: str, prompt: str, schema: Any, usage: dict[str, Any], **kw: Any) -> Any:
            seen.update(kw)
            async for d in fake.stream_json(system, prompt, schema, usage, **kw):
                yield d

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: Spy())
    r = await client.post(
        f"/api/sessions/{doc['sid']}/messages", json={"question": "third quarter revenue", "thinking": "HIGH"}
    )
    events = _sse(r.text)
    assert seen == {"model": None, "thinking": "high"}
    assert events[0][1]["thinking"] == "high"
    kinds = [k for k, _ in events]
    assert kinds.index("thinking_delta") < kinds.index("text_delta")
    msg = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()[-1]
    assert msg["reasoning"] == "Looking for the passage that answers the question."
    assert msg["thinking_level"] == "high" and msg["thinking_ms"] is not None

    await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "revenue?", "thinking": "off"})
    assert seen["thinking"] is None


async def test_unsupported_option_is_explained(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine
    from backend.llm.base import UnsupportedOption

    class Picky:
        model_id = "picky"

        async def stream_json(self, *a: Any, **kw: Any) -> Any:
            raise UnsupportedOption("picky rejected this request: thinking level xhigh is not supported.")
            yield  # pragma: no cover

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: Picky())
    events = _sse((await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "revenue?"})).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "unsupported_option"
    assert "xhigh" in events[-1][1]["message"]


@pytest.mark.parametrize(
    ("level", "supported", "want"),
    [
        ("minimal", ["low", "medium", "high"], "low"),
        ("xhigh", ["low", "medium", "high"], "high"),
        ("xhigh", ["minimal", "low", "medium", "high"], "high"),
        ("medium", ["low", "high"], "low"),  # tie goes to the cheaper level
        ("high", ["low", "medium", "high", "xhigh"], "high"),
    ],
)
def test_clamp_level(level: str, supported: list[str], want: str) -> None:
    from backend.core.config import clamp_level

    assert clamp_level(level, supported) == want


def test_per_model_thinking_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import Settings

    monkeypatch.setenv("MODELS_ENABLED", '{"neon": "low,medium,high*,xhigh", "lite": "minimal*,low,medium,high"}')
    monkeypatch.setenv("LLM_THINKING_LEVELS", "minimal,low,medium,high")  # global list still caps levels
    s = Settings()
    assert s.thinking_for("neon") == (["low", "medium", "high"], "high")
    assert s.thinking_for("lite") == (["minimal", "low", "medium", "high"], "minimal")
    assert s.thinking_for("unlisted") == (["minimal", "low", "medium", "high"], "medium")


async def test_models_and_ask_use_per_model_levels(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import engine
    from backend.core.config import get_settings
    from backend.llm.providers.fake import FakeProvider

    s = get_settings()
    monkeypatch.setattr(s, "models_enabled", {"capped": "low,medium*,high"})
    by_id = {m["id"]: m for m in (await client.get("/api/models")).json()["models"]}
    assert by_id["capped"]["thinking_levels"] == ["low", "medium", "high"]
    assert by_id["capped"]["default_thinking"] == "medium"

    seen: list[str | None] = []
    fake = FakeProvider()

    class Spy:
        model_id = "spy"

        async def stream_json(self, system: str, prompt: str, schema: Any, usage: dict[str, Any], **kw: Any) -> Any:
            seen.append(kw["thinking"])
            async for d in fake.stream_json(system, prompt, schema, usage, **kw):
                yield d

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: Spy())
    url = f"/api/sessions/{doc['sid']}/messages"
    await client.post(url, json={"question": "revenue?", "model": "capped", "thinking": "xhigh"})
    await client.post(url, json={"question": "revenue?", "model": "capped", "thinking": "minimal"})
    await client.post(url, json={"question": "revenue?", "model": "capped"})
    assert seen == ["high", "low", "medium"]


NOTES_MD = (
    "# Field notes\n\nThe pump station runs on a 48 volt battery bank.\n\n"
    "## Maintenance\n\nReplace the intake filter every 90 days.\n"
)


async def test_markdown_upload_ingest_ask_cite(client: Any) -> None:
    doc = await _upload(client, NOTES_MD.encode(), "notes.md")
    assert doc["format"] == "markdown"
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "ready", doc
    assert doc["page_count"] is None and doc["extent"] == "7 lines"

    r = await client.get(doc["file_url"])
    assert r.headers["content-type"].startswith("text/markdown") and r.content == NOTES_MD.encode()

    items = (await client.get(f"/api/documents/{doc['id']}/outline")).json()
    assert [(i["text"], i["ref"]) for i in items] == [("Field notes", "line 1"), ("Maintenance", "line 5")]

    sid = await _session(client, doc["id"])
    r = await client.post(
        f"/api/sessions/{sid}/messages", json={"question": "How often is the intake filter replaced?"}
    )
    events = _sse(r.text)
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["block_id"].startswith("md:7:")
    assert cite["location"]["kind"] == "text" and cite["ref"] == "line 7" and cite["page"] is None
    region = cite["location"]["regions"][0]
    assert NOTES_MD[region["char_start"] : region["char_end"]] == cite["quote"]
    assert events[-1][1]["status"] == "answered"


async def test_text_file_with_binary_content_is_rejected(client: Any) -> None:
    r = await client.post(
        "/api/documents", params={"filename": "a.txt"}, content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "type_mismatch"


async def test_undecodable_text_fails_gracefully(client: Any) -> None:
    # Passes the head sniff (valid UTF-8 start), fails the full parse test later in the file.
    doc = await _upload(client, b"fine start\n" * 500 + b"\x81\x8d broken tail", "log.txt")
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "failed" and doc["error"]["code"] == "unsupported_encoding"


async def test_formats_endpoint(client: Any) -> None:
    got = (await client.get("/api/formats")).json()
    assert [(f["name"], f["extensions"]) for f in got] == [
        ("pdf", [".pdf"]),
        ("text", [".txt"]),
        ("markdown", [".md", ".markdown"]),
        ("docx", [".docx"]),
        ("csv", [".csv", ".tsv"]),
    ]


async def test_docx_upload_ingest_ask_cite(client: Any) -> None:
    from backend.tests.docxgen import _paragraph_texts, sample_agreement

    data = sample_agreement()
    doc = await _upload(client, data, "msa.docx")
    assert doc["format"] == "docx"
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "ready", doc
    assert doc["page_count"] is None and doc["extent"].endswith(" words")

    r = await client.get(doc["file_url"])
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats") and r.content == data

    items = (await client.get(f"/api/documents/{doc['id']}/outline")).json()
    assert ("1. Scope", "paragraph 3") in [(i["text"], i["ref"]) for i in items]

    sid = await _session(client, doc["id"])
    r = await client.post(f"/api/sessions/{sid}/messages", json={"question": "What is the monthly fee?"})
    events = _sse(r.text)
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["block_id"].startswith("docx:") and cite["location"]["kind"] == "docx" and cite["page"] is None
    assert cite["ref"].startswith(("paragraph", "table"))
    paras = _paragraph_texts(data)
    got = " ".join(paras[g["para"]][g["char_start"] : g["char_end"]] for g in cite["location"]["regions"])
    assert got and got in cite["quote"].replace(" | ", " ").replace("\n", " ") or cite["quote"].startswith(got)
    assert events[-1][1]["status"] == "answered"


async def test_renamed_zip_as_docx_fails_gracefully(client: Any) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("notes.txt", "not a word file")
    doc = await _upload(client, buf.getvalue(), "notes.docx")
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "failed" and doc["error"]["code"] == "type_mismatch"


async def _ready_csv(client: Any, data: bytes, name: str = "orders.csv") -> dict[str, Any]:
    doc = await _upload(client, data, name)
    assert doc["format"] == "csv"
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "ready", doc
    return {**doc, "sid": await _session(client, doc["id"])}


async def test_csv_upload_ingest_ask_cites_computed_result(client: Any) -> None:
    from backend.tests.csvgen import sample_orders

    data = sample_orders()
    doc = await _ready_csv(client, data)
    assert doc["page_count"] is None and doc["extent"] == "120 rows, 11 columns"
    r = await client.get(doc["file_url"])
    assert r.headers["content-type"].startswith("text/csv") and r.content == data

    r = await client.post(
        f"/api/sessions/{doc['sid']}/messages", json={"question": "What is the sum of Units for West?"}
    )
    events = _sse(r.text)
    cites = [d["citation"] for k, d in events if k == "citation"]
    assert cites and all(c["location"]["kind"] == "csv" and c["page"] is None for c in cites)
    cite = cites[0]
    assert cite["block_id"].startswith("csvq:")  # the computed result, not a guess from rows
    assert cite["ref"] == "47 rows, Region and Units" and cite["location"]["rows"] == 47
    done = events[-1][1]
    assert done["status"] == "answered" and done["usage"]["computed"]["queries"] == 1
    assert done["usage"]["computed"]["results"] == 1

    # History keeps the validated citation; the computed block itself is never stored.
    msgs = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()
    assert msgs[-1]["segments"][0]["citations"][0]["block_id"] == cite["block_id"]


async def test_csv_lookup_without_computation_cites_rows(client: Any) -> None:
    from backend.tests.csvgen import sample_orders

    doc = await _ready_csv(client, sample_orders())
    r = await client.post(
        f"/api/sessions/{doc['sid']}/messages", json={"question": "Which order mentions warranty ticket?"}
    )
    events = _sse(r.text)
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["block_id"].startswith("csv:") and cite["location"]["kind"] == "csv"
    assert events[-1][1]["usage"]["computed"]["queries"] == 0


async def test_csv_planning_failure_still_answers(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.answering import computed
    from backend.tests.csvgen import sample_orders

    doc = await _ready_csv(client, sample_orders())

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("sandbox down")

    monkeypatch.setattr(computed, "run_sandboxed", broken)
    r = await client.post(
        f"/api/sessions/{doc['sid']}/messages", json={"question": "What is the sum of Units for West?"}
    )
    events = _sse(r.text)
    done = events[-1]
    assert done[0] == "done" and done[1]["usage"]["computed"]["error"] == "RuntimeError"
    assert all(d["citation"]["block_id"].startswith("csv:") for k, d in events if k == "citation")


async def test_tsv_and_binary_csv(client: Any) -> None:
    doc = await _ready_csv(client, b"id\tname\n1\talpha\n2\tbeta\n", "items.tsv")
    assert doc["extent"] == "2 rows, 2 columns"
    r = await client.post("/api/documents", params={"filename": "photo.csv"}, content=b"\x89PNG\r\n\x1a\n\x00\x00")
    assert r.status_code == 422 and r.json()["error"]["code"] == "type_mismatch"


async def test_malformed_csv_fails_gracefully(client: Any) -> None:
    doc = await _upload(client, b'a,b\n"never closed,1\n2,3\n', "broken.csv")
    await ingest(uuid.UUID(client.enqueued[-1]))
    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "failed" and doc["error"]["code"] == "malformed_csv"
    assert "never closed" in doc["error"]["message"]


async def test_stopped_answer_is_recorded_without_unverified_text(client: Any) -> None:
    from backend.answering.engine import answer_stream
    from backend.core.config import get_settings

    doc = await _ready_doc(client)
    s = get_settings()
    me = Principal(s.local_owner_id, s.local_workspace_id, "local")
    stream = cast(
        AsyncGenerator[dict[str, Any]],
        answer_stream(me, uuid.UUID(doc["sid"]), "What was third quarter revenue?", None, None),
    )
    async for e in stream:
        if e["event"] == "text_delta":
            break  # the reader presses Stop while text is streaming, before its citations validate
    await stream.aclose()

    hist = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()
    assert [(m["role"], m["status"]) for m in hist] == [("user", "complete"), ("assistant", "stopped")]
    assert hist[1]["segments"] == [] and hist[1]["content"] == ""  # streamed-but-unverified text is not kept
    assert hist[1]["suggestion"] is None


def test_config_json_is_valid_and_env_overrides_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import _CONFIG_JSON, Settings

    monkeypatch.setenv("ANYDOC_CONFIG_FILE", str(_CONFIG_JSON))
    s = Settings()
    assert s.models_enabled and s.llm_answer_model in s.allowed_models
    for model in s.allowed_models:
        levels, default = s.thinking_for(model)
        assert levels and default in levels, model
    assert isinstance(s.web_search_enabled, bool) and isinstance(s.langsmith_tracing, bool)
    monkeypatch.setenv("APP_ENV", "staging")  # an env var still wins over config.json
    assert Settings().app_env == "staging"


class _Engine:
    name = "Test search"

    def __init__(self, fail: str | None = None) -> None:
        self.fail, self.queries = fail, []  # type: ignore[var-annotated]

    async def search(self, query: str, max_results: int) -> list[Any]:
        from backend.websearch.base import SearchHit, SearchUnavailable

        self.queries.append(query)
        if self.fail:
            raise SearchUnavailable(self.fail)
        return [
            SearchHit(
                "Zebra facts",
                "https://example.org/zebra",
                "example.org",
                "Plains zebras migrate up to 500 km each year across the Serengeti.",
            )
        ]


def _use_engine(monkeypatch: pytest.MonkeyPatch, engine: _Engine) -> _Engine:
    from backend.answering import engine as answer_engine
    from backend.core.config import get_settings

    monkeypatch.setattr(answer_engine, "get_web_search", lambda: engine)
    monkeypatch.setattr(get_settings(), "web_search_enabled", True)
    return engine


async def test_web_lookup_runs_when_document_cannot_answer(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = await _ready_doc(client)
    engine = _use_engine(monkeypatch, _Engine())
    r = await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "zebra migration patterns"})
    events = _sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds.index("web_searching") < kinds.index("web") < kinds.index("done")
    web = dict(events)["web"]
    assert web["status"] == "answered" and web["query"] == "zebra migration patterns"
    assert web["segments"][0]["sources"] == [0] and web["sources"][0]["uri"].startswith("https://")
    assert "500 km" in web["segments"][0]["text"] and web["engine"] == "Test search"
    assert engine.queries == ["zebra migration patterns"]
    assert events[-1][1]["usage"]["web_engine"] == "Test search"
    assert events[-1][1]["status"] == "insufficient_evidence"  # the document answer is still an abstention
    assert not any(k == "citation" for k in kinds)  # web text never becomes a document citation

    hist = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()
    assert hist[1]["web"]["status"] == "answered" and hist[1]["segments"] == []


async def test_web_lookup_off_by_flag_and_skipped_when_answered(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = await _ready_doc(client)
    url = f"/api/sessions/{doc['sid']}/messages"
    kinds = [k for k, _ in _sse((await client.post(url, json={"question": "zebra migration patterns"})).text)]
    assert "web_searching" not in kinds  # flag off (the default)
    engine = _use_engine(monkeypatch, _Engine())
    kinds = [k for k, _ in _sse((await client.post(url, json={"question": "What was third quarter revenue?"})).text)]
    assert "citation" in kinds and "web_searching" not in kinds  # answered from the document, no web query
    assert engine.queries == []


async def test_web_lookup_failure_degrades(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _use_engine(monkeypatch, _Engine(fail="Web search quota is used up for now."))
    doc = await _ready_doc(client)
    events = _sse((await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "zebra herds"})).text)
    web = dict(events)["web"]
    assert web["status"] == "unavailable" and "quota" in web["note"] and web["segments"] == []
    assert events[-1][0] == "done" and events[-1][1]["status"] == "insufficient_evidence"
