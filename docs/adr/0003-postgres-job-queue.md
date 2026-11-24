# ADR-0003: Postgres-backed job queue (procrastinate)

Status: proposed (M0) · Date: 2026-11-25

## Context
Ingestion needs retries with backoff, cancellation (including running jobs), idempotency and progress. The brief says not to add infrastructure the local version does not need.

## Decision
procrastinate 3.12.0 (MIT) behind our `JobQueue` protocol, using the existing Postgres. Progress is stored in our own `ingestion_jobs` table.

## Evidence
Verified in package source: `cancel_job_by_id(abort=True)`, `JobContext.should_abort()`, `RetryStrategy(exponential_wait=…)`, `queueing_lock`. arq is in maintenance-only mode; Celery/Dramatiq/RQ need a broker.

## Consequences
- No Redis in Compose.
- Maintainer-bandwidth risk; swap target is Dramatiq + Redis behind the same protocol.
