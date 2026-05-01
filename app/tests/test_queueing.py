from types import SimpleNamespace

from app.queueing import MatchingJobEnqueuer, QueueDepthReader


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
