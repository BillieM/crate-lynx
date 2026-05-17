#!/usr/bin/env bash
set -euo pipefail

uvicorn app.main:app --host 0.0.0.0 --port 8000 &
api_pid=$!

worker_pids=()

if [[ -n "${RQ_QUEUE_NAMES:-}" ]]; then
  python -m app.core.worker &
  worker_pids+=("$!")
else
  INGESTION_WORKER_COUNT="${INGESTION_WORKER_COUNT:-1}"
  for ((i = 0; i < INGESTION_WORKER_COUNT; i++)); do
    RQ_QUEUE_NAMES=ingestion python -m app.core.worker &
    worker_pids+=("$!")
  done

  RQ_QUEUE_NAMES="${RQ_BACKGROUND_QUEUE_NAMES:-matching,streaming}" python -m app.core.worker &
  worker_pids+=("$!")
fi

shutdown() {
  kill "$api_pid" "${worker_pids[@]}" 2>/dev/null || true
  wait "$api_pid" "${worker_pids[@]}" 2>/dev/null || true
}

trap shutdown INT TERM

wait -n "$api_pid" "${worker_pids[@]}"
exit_code=$?
shutdown
exit "$exit_code"
