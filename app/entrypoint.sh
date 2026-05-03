#!/usr/bin/env bash
set -euo pipefail

uvicorn app.main:app --host 0.0.0.0 --port 8000 &
api_pid=$!

python -m app.core.worker &
worker_pid=$!

shutdown() {
  kill "$api_pid" "$worker_pid" 2>/dev/null || true
  wait "$api_pid" "$worker_pid" 2>/dev/null || true
}

trap shutdown INT TERM

wait -n "$api_pid" "$worker_pid"
exit_code=$?
shutdown
exit "$exit_code"
