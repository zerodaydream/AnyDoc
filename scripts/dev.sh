#!/usr/bin/env bash
# One command for local dev: Postgres (Docker) + migrations, then API, worker and web with prefixed logs.
# Ctrl+C stops everything; if any process exits, the rest are stopped too.
# Works with macOS's built-in bash 3.2 (no `wait -n`).
set -euo pipefail
cd "$(dirname "$0")/.."

for port in 8000 5173; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use (another AnyDoc api/web still running?). Stop it, then retry:" >&2
    lsof -nP -iTCP:$port -sTCP:LISTEN >&2
    exit 1
  fi
done

docker compose up -d --wait postgres
uv run python -m backend.migrate
[ -d frontend/web/node_modules ] || (cd frontend/web && npm install)

set -m  # job control: each service runs in its own process group, so one kill reaches uv/node children too
pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

run() {  # run <name> <ansi color> <command...>
  local name=$1 color=$2
  shift 2
  ("$@" 2>&1 | awk -v p="$(printf '\033[%sm%-6s\033[0m ' "$color" "$name")" '{ print p $0; fflush() }') &
  pids+=($!)
}

run api 33 uv run uvicorn backend.api.app:app --port 8000 --reload --reload-dir backend
run worker 36 uv run python -m backend.workers
run web 35 npm --prefix frontend/web run dev -- --port 5173

echo "AnyDoc: http://localhost:5173  (Ctrl+C to stop)"
while :; do
  for pid in "${pids[@]}"; do
    kill -0 "$pid" 2>/dev/null || { echo "a process exited; stopping the others"; exit 1; }
  done
  sleep 1
done
