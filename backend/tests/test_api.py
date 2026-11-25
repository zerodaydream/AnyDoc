import json
import uuid
from typing import Any

import pytest

from backend.api.app import app
from backend.ingestion.pipeline import ingest
from backend.security.auth import Principal, get_principal
from backend.tests.pdfgen import sample_report

pytestmark = pytest.mark.usefixtures("database")


async def _upload(client: Any, data: bytes, name: str = "report.pdf") -> dict[str, Any]:
    r = await client.post("/api/documents", params={"filename": name}, content=data)
    assert r.status_code == 201, r.text
    return r.json()


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

    hist = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[1]["segments"][0]["citations"][0]["block_id"] == cite["block_id"]


async def test_hybrid_route_when_over_budget(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings

    doc = await _ready_doc(client)
    monkeypatch.setattr(get_settings(), "full_context_token_budget", 1)
    r = await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "fourth quarter revenue outlook"})
    events = _sse(r.text)
    assert events[0][1]["route"] == "hybrid"
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["page"] == 2


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
        ("x.docx", b"%PDF-", "unsupported_format"),
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

        async def stream_json(self, system: str, prompt: str, schema: object, usage: dict[str, Any]) -> Any:
            yield '{"status":"answered","segments":[{"text":"Unverified claim'
            raise TransientError("gemini 503")

    doc = await _ready_doc(client)
    monkeypatch.setattr(engine, "get_llm", lambda: Flaky())
    events = _sse((await client.post(f"/api/sessions/{doc['sid']}/messages", json={"question": "revenue?"})).text)
    kinds = [k for k, _ in events]
    assert kinds.index("segment_retracted") < kinds.index("error")
    assert ("segment_retracted", {"segment": 0, "reason": "interrupted"}) in events
    assistant = (await client.get(f"/api/sessions/{doc['sid']}/messages")).json()[-1]
    assert assistant["status"] == "error" and assistant["segments"] == [] and assistant["content"] == ""


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

        async def stream_json(self, system: str, prompt: str, schema: Any, usage: dict[str, Any]) -> Any:
            calls.append(1)
            if len(calls) == 1:
                yield '{"status":"answered","segments":[{"text":"Partial'
                raise TransientError("503")
            async for d in fake.stream_json(system, prompt, schema, usage):
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

        async def stream_json(self, system: str, prompt: str, schema: Any, usage: dict[str, Any]) -> Any:
            prompts.append(prompt)
            async for d in fake.stream_json(system, prompt, schema, usage):
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
