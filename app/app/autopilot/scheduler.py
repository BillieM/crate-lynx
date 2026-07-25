from __future__ import annotations

import logging
import os
import signal
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from app.autopilot.jobs import AutopilotJobEnqueuer
from app.autopilot.models import (
    AUTOPILOT_TRIGGER_SCHEDULED,
    AUTOPILOT_TRIGGER_STARTUP,
)
from app.autopilot.store import AutopilotStore

logger = logging.getLogger(__name__)
DEFAULT_SCHEDULER_TICK_SECONDS = 30


def scheduled_idempotency_key(*, now: datetime, schedule_minutes: int) -> str:
    window_seconds = schedule_minutes * 60
    window = int(now.timestamp()) // window_seconds
    return f"scheduled:{schedule_minutes}:{window}"


def run_scheduler(
    *,
    database_url: str,
    redis_url: str,
    stop_event: threading.Event | None = None,
    tick_seconds: float = DEFAULT_SCHEDULER_TICK_SECONDS,
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    if tick_seconds <= 0:
        raise ValueError("Scheduler tick must be positive")
    stop = stop_event or threading.Event()
    store = AutopilotStore(database_url)
    enqueuer = AutopilotJobEnqueuer(redis_url)
    current_time = now_fn or (lambda: datetime.now(UTC))
    last_scheduled_key: str | None = None
    startup_enqueued = False
    startup_key = f"startup:{uuid.uuid4().hex}"
    startup_dry_run = _environment_boolean(
        "AUTOPILOT_STARTUP_RUN_DRY_RUN", default=False
    )

    while not stop.is_set():
        try:
            settings = store.get_settings()
            key = scheduled_idempotency_key(
                now=current_time(),
                schedule_minutes=settings.schedule_minutes,
            )
            if not startup_enqueued:
                enqueuer.enqueue(
                    dry_run=startup_dry_run,
                    idempotency_key=startup_key,
                    trigger=AUTOPILOT_TRIGGER_STARTUP,
                )
                startup_enqueued = True
                last_scheduled_key = key
            elif not settings.paused and key != last_scheduled_key:
                enqueuer.enqueue(
                    dry_run=False,
                    idempotency_key=key,
                    trigger=AUTOPILOT_TRIGGER_SCHEDULED,
                )
                last_scheduled_key = key
        except Exception:
            logger.exception("Autopilot scheduler tick failed")
        stop.wait(tick_seconds)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    database_url = _required_environment("DATABASE_URL")
    redis_url = _required_environment("REDIS_URL")
    tick_seconds = _tick_seconds()
    stop = threading.Event()

    def request_stop(signum, frame) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run_scheduler(
        database_url=database_url,
        redis_url=redis_url,
        stop_event=stop,
        tick_seconds=tick_seconds,
    )


def _tick_seconds() -> float:
    raw = os.environ.get(
        "AUTOPILOT_SCHEDULER_TICK_SECONDS",
        str(DEFAULT_SCHEDULER_TICK_SECONDS),
    )
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("AUTOPILOT_SCHEDULER_TICK_SECONDS must be numeric") from exc
    if value <= 0:
        raise RuntimeError("AUTOPILOT_SCHEDULER_TICK_SECONDS must be positive")
    return value


def _environment_boolean(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be configured for the autopilot scheduler")
    return value


if __name__ == "__main__":
    main()
