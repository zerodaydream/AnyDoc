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
    return doc


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

    r = await client.post(f"/api/documents/{doc['id']}/messages", json={"question": "What was third quarter revenue?"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert events[0][1]["route"] == "full_context"
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["page"] == 1 and cite["location"]["kind"] == "pdf"
    assert cite["location"]["regions"][0]["rects"]
    assert events[-1][1]["status"] == "answered"

    hist = (await client.get(f"/api/documents/{doc['id']}/messages")).json()
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[1]["segments"][0]["citations"][0]["block_id"] == cite["block_id"]


async def test_hybrid_route_when_over_budget(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings

    doc = await _ready_doc(client)
    monkeypatch.setattr(get_settings(), "full_context_token_budget", 1)
    r = await client.post(f"/api/documents/{doc['id']}/messages", json={"question": "fourth quarter revenue outlook"})
    events = _sse(r.text)
    assert events[0][1]["route"] == "hybrid"
    cite = next(d["citation"] for k, d in events if k == "citation")
    assert cite["page"] == 2


async def test_owner_scoping(client: Any) -> None:
    doc = await _ready_doc(client)
    other = Principal(uuid.uuid4(), uuid.uuid4(), "intruder")
    app.dependency_overrides[get_principal] = lambda: other
    try:
        for path in ("", "/file", "/messages"):
            assert (await client.get(f"/api/documents/{doc['id']}{path}")).status_code == 404
        r = await client.post(f"/api/documents/{doc['id']}/messages", json={"question": "revenue?"})
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
    r = await client.post(f"/api/documents/{doc['id']}/messages", json={"question": "anything"})
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
