from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from rq import Queue

from app.autopilot.gateway import ExistingServicesGateway
from app.autopilot.lock import LockUnavailableError, RenewableRedisLock
from app.autopilot.models import (
    AUTOPILOT_RUN_STATUS_SKIPPED,
)
from app.autopilot.recipes import SonicRecipeRegenerationAdapter
from app.autopilot.service import AutopilotCoordinator
from app.autopilot.store import AutopilotStore
from app.core.db import create_database_engine
from redis import Redis

AUTOPILOT_QUEUE_NAME = "autopilot"
AUTOPILOT_JOB_TIMEOUT = "2h"
AUTOPILOT_JOB_FUNCTION = "app.autopilot.jobs.run_autopilot_job"
AUTOPILOT_LOCK_KEY = "crate-lynx:autopilot:coordinator"
DEFAULT_AUTOPILOT_LOCK_TTL_SECONDS = 300


@dataclass(slots=True)
class AutopilotJobEnqueuer:
    redis_url: str
    queue_name: str = AUTOPILOT_QUEUE_NAME
    job_timeout: str = AUTOPILOT_JOB_TIMEOUT

    def enqueue(
        self,
        *,
        dry_run: bool,
        idempotency_key: str,
        trigger: str,
    ) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job_id = _job_id(idempotency_key)
        existing = queue.fetch_job(job_id)
        if existing is not None and existing.get_status(refresh=True) in {
            "queued",
            "started",
            "deferred",
            "scheduled",
            "finished",
        }:
            return existing.id
        job = queue.enqueue(
            AUTOPILOT_JOB_FUNCTION,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
            trigger=trigger,
            job_id=job_id,
            job_timeout=self.job_timeout,
            result_ttl=24 * 60 * 60,
            failure_ttl=7 * 24 * 60 * 60,
        )
        return job.id


def run_autopilot_job(
    *,
    dry_run: bool,
    idempotency_key: str,
    trigger: str,
) -> dict[str, object]:
    database_url = _required_environment("DATABASE_URL")
    redis_url = _required_environment("REDIS_URL")
    engine = create_database_engine(database_url)
    store = AutopilotStore(engine=engine)
    lock = RenewableRedisLock.from_url(
        redis_url,
        key=AUTOPILOT_LOCK_KEY,
        ttl_seconds=_lock_ttl_seconds(),
        wait_seconds=0,
    )
    try:
        with lock:
            coordinator = AutopilotCoordinator(
                store=store,
                gateway=ExistingServicesGateway(
                    engine=engine,
                    lease_checkpoint=lock.assert_owned,
                ),
                recipe_adapter=SonicRecipeRegenerationAdapter(
                    engine=engine,
                    lease_checkpoint=lock.assert_owned,
                ),
                lease_checkpoint=lock.assert_owned,
            )
            run = coordinator.run(
                dry_run=dry_run,
                idempotency_key=idempotency_key,
                trigger=trigger,
            )
            lock.assert_owned()
    except LockUnavailableError:
        run, _ = store.get_or_create_run(
            dry_run=dry_run,
            idempotency_key=idempotency_key,
            trigger=trigger,
        )
        run = store.update_run(
            run.id,
            status=AUTOPILOT_RUN_STATUS_SKIPPED,
            finished_at=datetime.now(UTC),
            error_detail="Another autopilot coordinator owns the renewable lease",
        )
    finally:
        engine.dispose()
    return {
        "run_id": run.id,
        "status": run.status,
        "dry_run": run.dry_run,
        "refreshed_playlists": run.refreshed_playlists,
        "searched_tracks": run.searched_tracks,
        "queued_downloads": run.queued_downloads,
        "review_items": run.review_items,
        "failed_items": run.failed_items,
    }


def _job_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"autopilot:{digest}"


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be configured for autopilot jobs")
    return value


def _lock_ttl_seconds() -> int:
    raw = os.environ.get(
        "AUTOPILOT_LOCK_TTL_SECONDS",
        str(DEFAULT_AUTOPILOT_LOCK_TTL_SECONDS),
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("AUTOPILOT_LOCK_TTL_SECONDS must be an integer") from exc
    if value < 30:
        raise RuntimeError("AUTOPILOT_LOCK_TTL_SECONDS must be at least 30")
    return value
