from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any

from redis import Redis
from rq import Queue, get_current_job

from app.matching.pipeline import MatchingPipeline
from app.matching.models import MatchResult


logger = logging.getLogger(__name__)


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
            "app.matching.jobs.run_matching_pipeline",
            local_track_id,
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


def _job_logger(local_track_id: int) -> MatchingJobLogAdapter:
    current_job = get_current_job()
    job_id = current_job.id if current_job is not None else "unknown"
    return MatchingJobLogAdapter(
        logger,
        {"job_id": job_id, "local_track_id": local_track_id},
    )
