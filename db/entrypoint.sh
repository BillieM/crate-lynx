#!/bin/sh
set -eu

postgres_pid=""

forward_signal() {
    if [ -n "$postgres_pid" ] && kill -0 "$postgres_pid" 2>/dev/null; then
        kill "$postgres_pid"
    fi
}

trap forward_signal INT TERM

/usr/local/bin/docker-entrypoint.sh "$@" &
postgres_pid=$!

attempt=0
until pg_isready -h 127.0.0.1 -p 5432 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        echo "Postgres did not become ready in time" >&2
        kill "$postgres_pid"
        wait "$postgres_pid" || true
        exit 1
    fi
    sleep 1
done

alembic -c /srv/db/alembic.ini upgrade head

wait "$postgres_pid"
