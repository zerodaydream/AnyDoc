"""Worker entrypoint: `uv run python -m backend.workers`."""

import asyncio
import logging

from backend.core.config import get_settings
from backend.core.logging import setup_logging
from backend.workers.queue import app

log = logging.getLogger("backend.worker")


async def main() -> None:
    setup_logging()
    s = get_settings()
    if s.embed_provider == "local":
        from backend.indexing.embeddings import get_embedder

        await get_embedder().embed_documents(["warmup"])  # load the model before taking jobs
    async with app.open_async():
        log.info("worker_started", extra={"concurrency": s.worker_concurrency})
        await app.run_worker_async(queues=["ingest"], concurrency=s.worker_concurrency)


if __name__ == "__main__":
    asyncio.run(main())
