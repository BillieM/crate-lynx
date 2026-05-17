from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path

from redis import Redis
from rq import Queue

from app.ingestion.pipeline import PreparedTrack, build_ingestion_processor


logger = logging.getLogger(__name__)

DEFAULT_INGESTION_QUEUE_NAME = "ingestion"
DEFAULT_INGESTION_JOB_TIMEOUT = "60m"
DEFAULT_DEDUPE_TTL_SECONDS = 6 * 60 * 60
DEDUPE_KEY_PREFIX = "crate-lynx:ingestion:source"


@dataclass(slots=True)
class IngestionJobEnqueuer:
    redis_url: str
    queue_name: str = DEFAULT_INGESTION_QUEUE_NAME
    job_timeout: str = DEFAULT_INGESTION_JOB_TIMEOUT
    dedupe_ttl_seconds: int = DEFAULT_DEDUPE_TTL_SECONDS

    def enqueue(self, source_path: Path | str) -> str | None:
        source = _normalize_source_path(source_path)
        connection = Redis.from_url(self.redis_url)
        key = self.dedupe_key(source)
        claimed = connection.set(
            key,
            "queued",
            nx=True,
            ex=max(1, self.dedupe_ttl_seconds),
        )
        if not claimed:
            return None

        queue = Queue(self.queue_name, connection=connection)
        try:
            job = queue.enqueue(
                "app.ingestion.jobs.run_ingestion_job",
                str(source),
                job_timeout=self.job_timeout,
            )
        except Exception:
            connection.delete(key)
            raise

        return job.id

    def clear(self, source_path: Path | str) -> None:
        connection = Redis.from_url(self.redis_url)
        connection.delete(self.dedupe_key(source_path))

    @classmethod
    def dedupe_key(cls, source_path: Path | str) -> str:
        source = _normalize_source_path(source_path)
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()
        return f"{DEDUPE_KEY_PREFIX}:{digest}"


def run_ingestion_job(source_path: str) -> PreparedTrack:
    source = _normalize_source_path(source_path)
    processor = None
    try:
        processor = build_ingestion_processor()
        return processor.process(source)
    finally:
        try:
            if processor is not None and processor.database_engine is not None:
                processor.database_engine.dispose()
        finally:
            _clear_dedupe_key_from_env(source)


def _clear_dedupe_key_from_env(source_path: Path) -> None:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return

    try:
        IngestionJobEnqueuer(redis_url).clear(source_path)
    except Exception:
        logger.exception(
            "Failed to clear ingestion dedupe key for source_path=%s",
            source_path,
        )


def _normalize_source_path(source_path: Path | str) -> Path:
    return Path(source_path).expanduser().resolve(strict=False)
