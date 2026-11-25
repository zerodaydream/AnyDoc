"""JobQueue boundary: procrastinate on the same Postgres (ADR-0003). Callers use enqueue/cancel only."""

import uuid

import procrastinate
from procrastinate import JobContext, RetryStrategy

from backend.core.config import get_settings
from backend.core.errors import TransientError

app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=get_settings().psycopg_dsn))


@app.task(
    name="ingest",
    queue="ingest",
    pass_context=True,
    retry=RetryStrategy(max_attempts=4, exponential_wait=5, retry_exceptions={TransientError}),
)
async def ingest_task(context: JobContext, version_id: str) -> None:
    from backend.ingestion.pipeline import ingest

    await ingest(uuid.UUID(version_id), should_abort=context.should_abort)


async def enqueue_ingest(version_id: uuid.UUID) -> int:
    # queueing_lock: at most one waiting job per version (idempotent enqueue).
    return await ingest_task.configure(queueing_lock=str(version_id)).defer_async(version_id=str(version_id))


async def cancel(job_id: int) -> bool:
    return await app.job_manager.cancel_job_by_id_async(job_id, abort=True)
