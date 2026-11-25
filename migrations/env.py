import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from backend.core import models  # noqa: F401 - registers tables
from backend.core.config import get_settings
from backend.core.db import Base

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)
target_metadata = Base.metadata


def _include(obj, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    # procrastinate owns its schema (backend.migrate applies it); never let autogenerate drop it.
    return not (type_ == "table" and name and name.startswith("procrastinate_"))


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=True, include_object=_include
    )
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


asyncio.run(main())
