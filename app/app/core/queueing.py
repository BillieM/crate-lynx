from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from redis import Redis
from rq import Queue


@dataclass(slots=True)
class StreamingSyncJobEnqueuer:
    redis_url: str
    queue_name: str = "streaming"
    job_timeout: str = "30m"

    def enqueue(
        self,
        *,
        account_id: int,
    ) -> str:
        return self._enqueue(
            "app.streaming.jobs.run_youtube_music_sync_job",
            account_id=account_id,
        )

    def enqueue_metadata_refresh(
        self,
        *,
        account_id: int,
    ) -> str:
        return self._enqueue(
            "app.streaming.jobs.run_youtube_music_playlist_metadata_refresh_job",
            account_id=account_id,
        )

    def _enqueue(
        self,
        job_function: str,
        *,
        account_id: int,
    ) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            job_function,
            account_id,
            job_timeout=self.job_timeout,
        )
        return job.id


@dataclass(slots=True)
class QueueDepthReader:
    redis_url: str | None
    queue_names: Sequence[str]

    def read(self) -> dict[str, int | None]:
        if not self.redis_url:
            return {queue_name: None for queue_name in self.queue_names}

        connection = Redis.from_url(self.redis_url)
        return {
            queue_name: Queue(queue_name, connection=connection).count
            for queue_name in self.queue_names
        }
