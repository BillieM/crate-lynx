from __future__ import annotations

from types import SimpleNamespace

from app.worker import build_worker, main, resolve_queue_names


def test_resolve_queue_names_uses_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("RQ_QUEUE_NAMES", raising=False)

    assert resolve_queue_names() == ("ingestion", "matching")


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

    monkeypatch.setattr("app.worker.Redis", FakeRedis)
    monkeypatch.setattr("app.worker.Queue", FakeQueue)
    monkeypatch.setattr("app.worker.Worker", FakeWorker)

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

    monkeypatch.setattr("app.worker.build_worker", fake_build_worker)

    main()

    assert seen["worked"] is True
