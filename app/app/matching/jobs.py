from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import logging
import os
from typing import Any

from redis import Redis
from rq import Queue, get_current_job
from rq.registry import StartedJobRegistry

from app.core.db import create_database_engine
from app.local_tracks.store import LocalTrackStore
from app.matching.models import MatchResult
from app.matching.pipeline import MatchingPipeline, SuggestedLinkStore


logger = logging.getLogger(__name__)
MATCHING_PIPELINE_JOB = "app.matching.jobs.run_matching_pipeline"
UNRESOLVED_LOCAL_TRACK_STATUSES = ("unlinked", "pending")


class MatchingJobLogAdapter(logging.LoggerAdapter):
    def process(
        self,
        msg: object,
        kwargs: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        extra = dict(self.extra)
        extra.update(kwargs.pop("extra", {}))
        kwargs["extra"] = extra
        prefix = f"job_id={extra['job_id']} local_track_id={extra['local_track_id']}"
        return f"{prefix} {msg}", kwargs


@dataclass(slots=True)
class MatchingJobEnqueuer:
    redis_url: str
    queue_name: str = "matching"
    job_timeout: str = "10m"

    def enqueue(self, local_track_id: int) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            MATCHING_PIPELINE_JOB,
            local_track_id,
            job_timeout=self.job_timeout,
        )
        return job.id

    def queued_or_started_local_track_ids(
        self,
        local_track_ids: Collection[int],
    ) -> set[int]:
        target_ids = set(local_track_ids)
        if not target_ids:
            return set()

        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        jobs = list(queue.get_jobs())
        started_registry = StartedJobRegistry(queue=queue)
        for job_id in started_registry.get_job_ids():
            job = queue.fetch_job(job_id)
            if job is not None:
                jobs.append(job)

        return {
            matched_local_track_id
            for job in jobs
            if (matched_local_track_id := _matching_pipeline_local_track_id(job))
            in target_ids
        }


@dataclass(slots=True)
class LocalTrackRematchBackfillJobEnqueuer:
    redis_url: str
    queue_name: str = "matching"
    job_timeout: str = "10m"

    def enqueue(self) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            "app.matching.jobs.run_unresolved_local_tracks_rematch_backfill",
            job_timeout=self.job_timeout,
        )
        return job.id


def run_matching_pipeline(local_track_id: int) -> MatchResult | None:
    job_logger = _job_logger(local_track_id)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for matching")

    job_logger.info("starting matching pipeline")
    pipeline = MatchingPipeline(
        database_url=database_url,
        redis_url=os.environ.get("REDIS_URL"),
        log=job_logger,
    )
    try:
        result = pipeline.run(local_track_id)
    except Exception:
        job_logger.exception("matching pipeline failed")
        raise

    if result is None:
        job_logger.info("matching pipeline completed without suggestion")
    else:
        job_logger.info(
            "matching pipeline completed match_method=%s "
            "streaming_track_id=%s score=%.3f",
            result.match_method,
            result.streaming_track_id,
            result.score,
        )
    return result


def run_unresolved_local_tracks_rematch_backfill() -> dict[str, object]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for local track rematch")

    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL must be configured for local track rematch")

    engine = create_database_engine(database_url)
    try:
        local_track_ids = LocalTrackStore(
            engine=engine
        ).list_unresolved_local_track_ids()
        enqueuer = MatchingJobEnqueuer(redis_url)
        existing_local_track_ids = enqueuer.queued_or_started_local_track_ids(
            local_track_ids
        )
        suggestion_store = SuggestedLinkStore(engine=engine)
        enqueued: dict[int, str] = {}
        skipped: list[int] = []

        for local_track_id in local_track_ids:
            if local_track_id in existing_local_track_ids:
                skipped.append(local_track_id)
                continue

            suggestion_store.clear_non_approved_for_track(local_track_id)
            enqueued[local_track_id] = enqueuer.enqueue(local_track_id)

        return {
            "statuses": list(UNRESOLVED_LOCAL_TRACK_STATUSES),
            "target_count": len(local_track_ids),
            "enqueued": enqueued,
            "skipped_existing": skipped,
        }
    finally:
        engine.dispose()


def _job_logger(local_track_id: int) -> MatchingJobLogAdapter:
    current_job = get_current_job()
    job_id = current_job.id if current_job is not None else "unknown"
    return MatchingJobLogAdapter(
        logger,
        {"job_id": job_id, "local_track_id": local_track_id},
    )


def _matching_pipeline_local_track_id(job: object) -> int | None:
    if getattr(job, "func_name", None) != MATCHING_PIPELINE_JOB:
        return None

    args = getattr(job, "args", ())
    if len(args) != 1:
        return None

    local_track_id = args[0]
    return local_track_id if isinstance(local_track_id, int) else None
