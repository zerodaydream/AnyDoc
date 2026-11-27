import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.api import admin, chat, documents, models
from backend.core.config import get_settings
from backend.core.db import get_engine
from backend.core.errors import AppError
from backend.core.logging import request_id, setup_logging
from backend.llm.factory import get_llm
from backend.workers.queue import app as queue_app

log = logging.getLogger("backend.api")


def _hardware() -> dict[str, object]:
    ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    return {"cpus": os.cpu_count(), "ram_gb": round(ram / 2**30, 1)}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    s = get_settings()
    log.info("startup", extra={"env": s.app_env, **_hardware(), "embed": s.embed_model, "llm": get_llm().model_id})
    # Fails loudly if a configured model is unavailable or structured output is broken.
    log.info("llm_check", extra={"result": await get_llm().check()})
    async with queue_app.open_async():
        yield
    await get_engine().dispose()


app = FastAPI(title="AnyDoc API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Range"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


@app.middleware("http")
async def with_request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


@app.exception_handler(AppError)
async def app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)


@app.get("/api/health")
async def health() -> dict[str, str]:
    async with get_engine().connect() as c:
        await c.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(documents.router)
app.include_router(documents.formats_router)
app.include_router(chat.router)
app.include_router(models.router)
app.include_router(admin.router)
