from __future__ import annotations

from dataclasses import dataclass
import os

from redis import Redis
from rq import Queue

from app.matching.pipeline import MatchingPipeline
from app.matching.models import MatchResult


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
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for matching")

    pipeline = MatchingPipeline(
        database_url=database_url,
        redis_url=os.environ.get("REDIS_URL"),
    )
    return pipeline.run(local_track_id)
