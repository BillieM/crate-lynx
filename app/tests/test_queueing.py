from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.queueing import QueueDepthReader, StreamingSyncJobEnqueuer
from app.ingestion.jobs import IngestionJobEnqueuer, run_ingestion_job
from app.matching.jobs import MatchingJobEnqueuer


def test_ingestion_job_enqueuer_uses_ingestion_queue(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeRedisConnection:
        def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
            seen["dedupe_key"] = key
            seen["dedupe_value"] = value
            seen["dedupe_nx"] = nx
            seen["dedupe_ex"] = ex
            return True

        def delete(self, key: str) -> None:
            seen["deleted_key"] = key

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> FakeRedisConnection:
            seen["redis_url"] = url
            return FakeRedisConnection()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def enqueue(
            self,
            func: str,
            source_path: str,
            *,
            job_timeout: str,
        ) -> SimpleNamespace:
            seen["func"] = func
            seen["source_path"] = source_path
            seen["job_timeout"] = job_timeout
            return SimpleNamespace(id="ingestion-job-123")

    monkeypatch.setattr("app.ingestion.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.ingestion.jobs.Queue", FakeQueue)

    job_id = IngestionJobEnqueuer(
        redis_url="redis://redis:6379/0",
        job_timeout="15m",
        dedupe_ttl_seconds=90,
    ).enqueue("/incoming/track.mp3")

    assert job_id == "ingestion-job-123"
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "dedupe_key": IngestionJobEnqueuer.dedupe_key("/incoming/track.mp3"),
        "dedupe_value": "queued",
        "dedupe_nx": True,
        "dedupe_ex": 90,
        "queue_name": "ingestion",
        "connection": seen["connection"],
        "func": "app.ingestion.jobs.run_ingestion_job",
        "source_path": "/incoming/track.mp3",
        "job_timeout": "15m",
    }


def test_ingestion_job_enqueuer_skips_duplicate_sources(monkeypatch) -> None:
    seen: dict[str, object] = {"enqueued": False}

    class FakeRedisConnection:
        def set(self, key: str, value: str, *, nx: bool, ex: int) -> None:
            seen["dedupe_key"] = key
            return None

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> FakeRedisConnection:
            return FakeRedisConnection()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            pass

        def enqueue(self, *args, **kwargs) -> SimpleNamespace:
            seen["enqueued"] = True
            return SimpleNamespace(id="unexpected")

    monkeypatch.setattr("app.ingestion.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.ingestion.jobs.Queue", FakeQueue)

    job_id = IngestionJobEnqueuer(redis_url="redis://redis:6379/0").enqueue(
        "/incoming/track.mp3"
    )

    assert job_id is None
    assert seen == {
        "dedupe_key": IngestionJobEnqueuer.dedupe_key("/incoming/track.mp3"),
        "enqueued": False,
    }


def test_run_ingestion_job_builds_processor_and_clears_dedupe_key(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}

    class FakeProcessor:
        database_engine = None

        def process(self, source_path):
            seen["processed_source_path"] = source_path
            return "processed"

    class FakeRedisConnection:
        def delete(self, key: str) -> None:
            seen["deleted_key"] = key

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> FakeRedisConnection:
            seen["redis_url"] = url
            return FakeRedisConnection()

    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(
        "app.ingestion.jobs.build_ingestion_processor",
        lambda: FakeProcessor(),
    )
    monkeypatch.setattr("app.ingestion.jobs.Redis", FakeRedis)

    result = run_ingestion_job("/incoming/track.mp3")

    assert result == "processed"
    assert seen == {
        "processed_source_path": Path("/incoming/track.mp3"),
        "redis_url": "redis://redis:6379/0",
        "deleted_key": IngestionJobEnqueuer.dedupe_key("/incoming/track.mp3"),
    }


def test_run_ingestion_job_clears_dedupe_key_after_failure(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeProcessor:
        database_engine = None

        def process(self, source_path):
            seen["processed_source_path"] = source_path
            raise ValueError("bad import")

    class FakeRedisConnection:
        def delete(self, key: str) -> None:
            seen["deleted_key"] = key

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> FakeRedisConnection:
            seen["redis_url"] = url
            return FakeRedisConnection()

    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(
        "app.ingestion.jobs.build_ingestion_processor",
        lambda: FakeProcessor(),
    )
    monkeypatch.setattr("app.ingestion.jobs.Redis", FakeRedis)

    with pytest.raises(ValueError, match="bad import"):
        run_ingestion_job("/incoming/track.mp3")

    assert seen == {
        "processed_source_path": Path("/incoming/track.mp3"),
        "redis_url": "redis://redis:6379/0",
        "deleted_key": IngestionJobEnqueuer.dedupe_key("/incoming/track.mp3"),
    }


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

    monkeypatch.setattr("app.matching.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.matching.jobs.Queue", FakeQueue)

    job_id = MatchingJobEnqueuer(
        redis_url="redis://redis:6379/0", job_timeout="5m"
    ).enqueue(17)

    assert job_id == "job-abc"
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "matching",
        "connection": seen["connection"],
        "func": "app.matching.jobs.run_matching_pipeline",
        "local_track_id": 17,
        "job_timeout": "5m",
    }


def test_matching_job_enqueuer_finds_equivalent_queued_and_started_jobs(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}
    queued_job = SimpleNamespace(
        args=(17,),
        func_name="app.matching.jobs.run_matching_pipeline",
    )
    unrelated_job = SimpleNamespace(
        args=(18,),
        func_name="app.ingestion.jobs.run_ingestion_job",
    )
    malformed_job = SimpleNamespace(
        args=("19",),
        func_name="app.matching.jobs.run_matching_pipeline",
    )
    started_job = SimpleNamespace(
        args=(23,),
        func_name="app.matching.jobs.run_matching_pipeline",
    )

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def get_jobs(self):
            return [queued_job, unrelated_job, malformed_job]

        def fetch_job(self, job_id: str):
            return {"started-23": started_job, "missing": None}[job_id]

    class FakeStartedJobRegistry:
        def __init__(self, *, queue: FakeQueue) -> None:
            seen["registry_queue"] = queue

        def get_job_ids(self):
            return ["started-23", "missing"]

    monkeypatch.setattr("app.matching.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.matching.jobs.Queue", FakeQueue)
    monkeypatch.setattr("app.matching.jobs.StartedJobRegistry", FakeStartedJobRegistry)

    local_track_ids = MatchingJobEnqueuer(
        redis_url="redis://redis:6379/0"
    ).queued_or_started_local_track_ids({17, 19, 23, 99})

    assert local_track_ids == {17, 23}
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "matching",
        "connection": seen["connection"],
        "registry_queue": seen["registry_queue"],
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

    monkeypatch.setattr("app.core.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.core.queueing.Queue", FakeQueue)

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

    monkeypatch.setattr("app.core.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.core.queueing.Queue", FakeQueue)

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
        "func": "app.streaming.jobs.run_youtube_music_sync_job",
        "account_id": 19,
        "job_timeout": "20m",
    }


def test_streaming_sync_job_enqueuer_enqueues_metadata_refresh_job(
    monkeypatch,
) -> None:
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
            return SimpleNamespace(id="metadata-refresh-job-123")

    monkeypatch.setattr("app.core.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.core.queueing.Queue", FakeQueue)

    job_id = StreamingSyncJobEnqueuer(
        redis_url="redis://redis:6379/2",
        job_timeout="20m",
    ).enqueue_metadata_refresh(
        account_id=19,
    )

    assert job_id == "metadata-refresh-job-123"
    assert seen == {
        "redis_url": "redis://redis:6379/2",
        "queue_name": "streaming",
        "connection": seen["connection"],
        "func": "app.streaming.jobs.run_youtube_music_playlist_metadata_refresh_job",
        "account_id": 19,
        "job_timeout": "20m",
    }


def test_streaming_sync_job_enqueuer_enqueues_playlist_sync_job(
    monkeypatch,
) -> None:
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
            playlist_id: int,
            *,
            job_timeout: str,
        ) -> SimpleNamespace:
            seen["func"] = func
            seen["playlist_id"] = playlist_id
            seen["job_timeout"] = job_timeout
            return SimpleNamespace(id="playlist-sync-job-123")

    monkeypatch.setattr("app.core.queueing.Redis", FakeRedis)
    monkeypatch.setattr("app.core.queueing.Queue", FakeQueue)

    job_id = StreamingSyncJobEnqueuer(
        redis_url="redis://redis:6379/2",
        job_timeout="20m",
    ).enqueue_playlist_sync(
        playlist_id=23,
    )

    assert job_id == "playlist-sync-job-123"
    assert seen == {
        "redis_url": "redis://redis:6379/2",
        "queue_name": "streaming",
        "connection": seen["connection"],
        "func": "app.streaming.jobs.run_youtube_music_playlist_sync_job",
        "playlist_id": 23,
        "job_timeout": "20m",
    }
