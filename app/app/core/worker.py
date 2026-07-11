from __future__ import annotations

from collections.abc import Sequence
import logging
import os

from redis import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError
from rq import Queue, Worker


DEFAULT_QUEUE_NAMES = ("ingestion", "matching", "streaming", "sonic", "soulseek")
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class CrateLynxWorker(Worker):
    """Keep RQ's control-channel listener alive across idle Redis timeouts."""

    def _pubsub_exception_handler(
        self,
        exc: Exception,
        pubsub: object,
        pubsub_thread: object,
    ) -> None:
        if isinstance(exc, RedisTimeoutError):
            self.log.warning("Redis pubsub timed out; reconnecting")
            return
        super()._pubsub_exception_handler(exc, pubsub, pubsub_thread)


def resolve_queue_names(raw_queue_names: str | None = None) -> tuple[str, ...]:
    candidate = raw_queue_names
    if candidate is None:
        candidate = os.environ.get("RQ_QUEUE_NAMES")

    if candidate is None:
        return DEFAULT_QUEUE_NAMES

    queue_names = tuple(name.strip() for name in candidate.split(",") if name.strip())
    if queue_names:
        return queue_names

    return DEFAULT_QUEUE_NAMES


def build_worker(
    *,
    redis_url: str | None = None,
    queue_names: Sequence[str] | None = None,
) -> Worker:
    resolved_redis_url = redis_url or os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    resolved_queue_names = tuple(queue_names or resolve_queue_names())
    connection = Redis.from_url(resolved_redis_url)
    queues = [Queue(name, connection=connection) for name in resolved_queue_names]
    return CrateLynxWorker(queues, connection=connection)


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        format="%(levelname)s:%(name)s:%(message)s",
        level=level,
    )


def main() -> None:
    configure_logging()
    worker = build_worker()
    worker.work()


if __name__ == "__main__":
    main()
