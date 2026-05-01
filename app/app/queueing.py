from __future__ import annotations

from dataclasses import dataclass

from redis import Redis
from rq import Queue


@dataclass(slots=True)
class MatchingJobEnqueuer:
    redis_url: str
    queue_name: str = "matching"
    job_timeout: str = "10m"

    def enqueue(self, local_track_id: int) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            "app.matching.run_matching_pipeline",
            local_track_id,
            job_timeout=self.job_timeout,
        )
        return job.id
