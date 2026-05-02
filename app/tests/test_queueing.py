from types import SimpleNamespace

from app.queueing import (
    MatchingJobEnqueuer,
    QueueDepthReader,
    StreamingSyncJobEnqueuer,
)


def test_matching_job_enqueuer_uses_default_queue(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def enqueue(
            self, func: str, local_track_id: int, *, job_timeout: str
        ) -> SimpleNamespace:
            seen["func"] = func
            seen["local_track_id"] = local_track_id
            seen["job_timeout"] = job_timeout
            return SimpleNamespace(id="job-abc")

    monkeypatch.setattr("app.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.queueing.Queue", FakeQueue)

    job_id = MatchingJobEnqueuer(
        redis_url="redis://redis:6379/0", job_timeout="5m"
    ).enqueue(17)

    assert job_id == "job-abc"
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "matching",
        "connection": seen["connection"],
        "func": "app.matching.run_matching_pipeline",
        "local_track_id": 17,
        "job_timeout": "5m",
    }


def test_queue_depth_reader_reads_counts(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen.setdefault("queue_names", []).append(name)
            self.count = {"ingestion": 4, "matching": 1}[name]

    monkeypatch.setattr("app.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.queueing.Queue", FakeQueue)

    depths = QueueDepthReader(
        redis_url="redis://redis:6379/0",
        queue_names=("ingestion", "matching"),
    ).read()

    assert depths == {"ingestion": 4, "matching": 1}
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_names": ["ingestion", "matching"],
    }


def test_queue_depth_reader_returns_none_without_redis_url() -> None:
    depths = QueueDepthReader(
        redis_url=None,
        queue_names=("ingestion", "matching"),
    ).read()

    assert depths == {"ingestion": None, "matching": None}


def test_streaming_sync_job_enqueuer_uses_streaming_queue(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def enqueue(
            self,
            func: str,
            account_id: int,
            *,
            job_timeout: str,
        ) -> SimpleNamespace:
            seen["func"] = func
            seen["account_id"] = account_id
            seen["job_timeout"] = job_timeout
            return SimpleNamespace(id="sync-job-123")

    monkeypatch.setattr("app.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.queueing.Queue", FakeQueue)

    job_id = StreamingSyncJobEnqueuer(
        redis_url="redis://redis:6379/2",
        job_timeout="20m",
    ).enqueue(
        account_id=19,
    )

    assert job_id == "sync-job-123"
    assert seen == {
        "redis_url": "redis://redis:6379/2",
        "queue_name": "streaming",
        "connection": seen["connection"],
        "func": "app.streaming_accounts.run_youtube_music_sync_job",
        "account_id": 19,
        "job_timeout": "20m",
    }
