# API, worker and migrate share this image. CPU torch in containers (no Apple GPU in Docker on macOS).
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
# shortcut: locked PyPI torch is CPU-only on linux/arm64 (Docker on Apple silicon) but bundles CUDA on
# linux/amd64; pin a CPU index in the lock before building amd64 production images.
RUN uv sync --frozen --no-dev --extra ml --no-install-project
COPY alembic.ini ./
COPY migrations ./migrations
COPY backend ./backend
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
