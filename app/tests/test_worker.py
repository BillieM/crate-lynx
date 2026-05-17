from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from app.core.worker import build_worker, main, resolve_queue_names
from app.matching.jobs import run_matching_pipeline


def test_resolve_queue_names_uses_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("RQ_QUEUE_NAMES", raising=False)

    assert resolve_queue_names() == ("ingestion", "matching", "streaming")


def test_resolve_queue_names_strips_commas_and_whitespace() -> None:
    assert resolve_queue_names(" ingestion, matching , default ,, ") == (
        "ingestion",
        "matching",
        "default",
    )


def test_build_worker_uses_redis_url_and_queue_names(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen.setdefault("queue_names", []).append(name)
            seen["queue_connection"] = connection
            self.name = name

    class FakeWorker:
        def __init__(self, queues: list[FakeQueue], connection: object) -> None:
            seen["worker_queue_names"] = [queue.name for queue in queues]
            seen["worker_connection"] = connection

    monkeypatch.setattr("app.core.worker.Redis", FakeRedis)
    monkeypatch.setattr("app.core.worker.Queue", FakeQueue)
    monkeypatch.setattr("app.core.worker.Worker", FakeWorker)

    build_worker(
        redis_url="redis://redis:6379/5",
        queue_names=("ingestion", "matching"),
    )

    assert seen == {
        "redis_url": "redis://redis:6379/5",
        "queue_names": ["ingestion", "matching"],
        "queue_connection": seen["queue_connection"],
        "worker_queue_names": ["ingestion", "matching"],
        "worker_connection": seen["worker_connection"],
    }


def test_main_starts_worker(monkeypatch) -> None:
    seen: dict[str, bool] = {"worked": False}

    def fake_build_worker() -> SimpleNamespace:
        return SimpleNamespace(work=lambda: seen.__setitem__("worked", True))

    monkeypatch.setattr("app.core.worker.build_worker", fake_build_worker)

    main()

    assert seen["worked"] is True


def test_entrypoint_splits_ingestion_from_matching_and_streaming_workers() -> None:
    entrypoint = Path(__file__).resolve().parents[1] / "entrypoint.sh"
    script = entrypoint.read_text()

    assert 'INGESTION_WORKER_COUNT="${INGESTION_WORKER_COUNT:-1}"' in script
    assert "RQ_QUEUE_NAMES=ingestion python -m app.core.worker &" in script
    assert (
        'RQ_QUEUE_NAMES="${RQ_BACKGROUND_QUEUE_NAMES:-matching,streaming}" '
        "python -m app.core.worker &"
    ) in script
    assert 'if [[ -n "${RQ_QUEUE_NAMES:-}" ]]; then' in script


def test_run_matching_pipeline_logs_job_context(monkeypatch, caplog) -> None:
    class FakePipeline:
        def __init__(self, *, database_url: str, redis_url: str | None, log) -> None:
            self.log = log
            assert database_url == "sqlite:///app.db"
            assert redis_url == "redis://redis:6379/0"

        def run(self, local_track_id: int) -> None:
            self.log.info("downstream matching log")
            assert local_track_id == 42
            return None

    monkeypatch.setenv("DATABASE_URL", "sqlite:///app.db")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr("app.matching.jobs.MatchingPipeline", FakePipeline)
    monkeypatch.setattr(
        "app.matching.jobs.get_current_job",
        lambda: SimpleNamespace(id="job-123"),
    )

    with caplog.at_level(logging.INFO, logger="app.matching.jobs"):
        assert run_matching_pipeline(42) is None

    matching_records = [
        record for record in caplog.records if record.name == "app.matching.jobs"
    ]
    assert len(matching_records) == 3
    assert all(record.job_id == "job-123" for record in matching_records)
    assert all(record.local_track_id == 42 for record in matching_records)
    assert [record.getMessage() for record in matching_records] == [
        "job_id=job-123 local_track_id=42 starting matching pipeline",
        "job_id=job-123 local_track_id=42 downstream matching log",
        "job_id=job-123 local_track_id=42 "
        "matching pipeline completed without suggestion",
    ]
