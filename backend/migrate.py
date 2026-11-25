"""`uv run python -m backend.migrate`: app schema (alembic) + job-queue schema (procrastinate, once)."""

import asyncio

import psycopg
from alembic import command
from alembic.config import Config

from backend.core.config import get_settings
from backend.workers.queue import app


async def _queue_schema() -> None:
    async with await psycopg.AsyncConnection.connect(get_settings().psycopg_dsn) as conn:
        exists = (await (await conn.execute("SELECT to_regclass('procrastinate_jobs')")).fetchone() or [None])[0]
    if exists is None:
        async with app.open_async():
            await app.schema_manager.apply_schema_async()


def main() -> None:
    command.upgrade(Config("alembic.ini"), "head")  # alembic env runs its own event loop
    asyncio.run(_queue_schema())


if __name__ == "__main__":
    main()
