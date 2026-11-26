import os
import tempfile

# Must run before any backend import: settings are cached on first use.
os.environ.update(
    ANYDOC_ENV_FILE="",
    ANYDOC_CONFIG_FILE="",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://anydoc:anydoc@localhost:5432/anydoc_test"),
    DATA_DIR=tempfile.mkdtemp(prefix="anydoc-test-"),
    LLM_PROVIDER="fake",
    GEMINI_API_KEY="",
    EMBED_PROVIDER="fake",
    LANGSMITH_TRACING="false",
)

from collections.abc import AsyncIterator  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session")
def database() -> str:
    """Fresh test database with the app schema. Skips DB tests when Postgres is not running."""
    from backend.core.config import get_settings

    dsn = get_settings().psycopg_dsn
    admin = dsn.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(admin, autocommit=True, connect_timeout=2) as c:
            c.execute("DROP DATABASE IF EXISTS anydoc_test WITH (FORCE)")
            c.execute("CREATE DATABASE anydoc_test")
    except psycopg.OperationalError:
        pytest.skip("Postgres not running: `docker compose up -d postgres`")
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")
    return dsn


@pytest.fixture
async def client(database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[object]:
    import httpx

    from backend.api.app import app
    from backend.workers import queue

    enqueued: list[str] = []

    async def fake_enqueue(version_id: object) -> int:
        enqueued.append(str(version_id))
        return len(enqueued)

    async def fake_cancel(job_id: int) -> bool:
        return True

    monkeypatch.setattr(queue, "enqueue_ingest", fake_enqueue)
    monkeypatch.setattr(queue, "cancel", fake_cancel)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.enqueued = enqueued  # type: ignore[attr-defined]
        yield c
