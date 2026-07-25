from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import app.autopilot.scheduler as scheduler_module
import pytest
from app.autopilot.lock import (
    LockOwnershipLostError,
    RenewableRedisLock,
)
from app.autopilot.scheduler import scheduled_idempotency_key


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self._lock = threading.Lock()
        self.renewals = 0

    def set(self, key, value, *, nx, px):
        with self._lock:
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

    def eval(self, script, key_count, key, token, *args):
        with self._lock:
            if self.values.get(key) != token:
                return 0
            if "pexpire" in script:
                self.renewals += 1
                return 1
            if "del" in script:
                del self.values[key]
                return 1
            raise AssertionError("Unexpected script")


def test_renewable_lock_renews_and_releases_only_its_token() -> None:
    redis = FakeRedis()
    lock = RenewableRedisLock(
        connection=redis,
        key="lock",
        ttl_seconds=1,
        renewal_interval_seconds=0.05,
    )

    lock.acquire()
    assert lock.token == redis.values["lock"]
    lock.renew()
    assert redis.renewals >= 1

    redis.values["lock"] = "new-owner"
    with pytest.raises(LockOwnershipLostError):
        lock.renew()
    lock.release()

    assert redis.values["lock"] == "new-owner"


def test_scheduled_idempotency_key_is_stable_within_window() -> None:
    first = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    assert scheduled_idempotency_key(
        now=first, schedule_minutes=60
    ) == scheduled_idempotency_key(
        now=first + timedelta(minutes=59), schedule_minutes=60
    )
    assert scheduled_idempotency_key(
        now=first, schedule_minutes=60
    ) != scheduled_idempotency_key(
        now=first + timedelta(minutes=60), schedule_minutes=60
    )


def test_scheduler_suppresses_initial_duplicate_then_enqueues_next_window(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []
    enqueue_counts_at_wait: list[int] = []
    clock = [datetime(2026, 7, 25, 12, 0, tzinfo=UTC)]

    class FakeStore:
        def get_settings(self):
            return SimpleNamespace(paused=False, schedule_minutes=60)

    class FakeEnqueuer:
        def enqueue(self, **kwargs):
            calls.append(kwargs)
            return f"job-{len(calls)}"

    class StepStop:
        waits = 0

        def is_set(self):
            return self.waits >= 2

        def wait(self, timeout):
            enqueue_counts_at_wait.append(len(calls))
            self.waits += 1
            if self.waits == 1:
                clock[0] += timedelta(minutes=61)
            return self.is_set()

    monkeypatch.setattr(
        scheduler_module,
        "AutopilotStore",
        lambda database_url: FakeStore(),
    )
    monkeypatch.setattr(
        scheduler_module,
        "AutopilotJobEnqueuer",
        lambda redis_url: FakeEnqueuer(),
    )

    scheduler_module.run_scheduler(
        database_url="sqlite://",
        redis_url="redis://",
        stop_event=StepStop(),
        tick_seconds=1,
        now_fn=lambda: clock[0],
    )

    assert enqueue_counts_at_wait == [1, 2]
    assert [call["trigger"] for call in calls] == ["startup", "scheduled"]
    assert calls[1]["idempotency_key"] == scheduled_idempotency_key(
        now=clock[0],
        schedule_minutes=60,
    )


def test_scheduler_retries_startup_after_database_is_temporarily_unavailable(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeStore:
        attempts = 0

        def get_settings(self):
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError("database is still migrating")
            return SimpleNamespace(paused=False, schedule_minutes=60)

    class FakeEnqueuer:
        def enqueue(self, **kwargs):
            calls.append(kwargs)
            return "startup-job"

    class StepStop:
        waits = 0

        def is_set(self):
            return self.waits >= 2

        def wait(self, timeout):
            self.waits += 1
            return self.is_set()

    monkeypatch.setattr(
        scheduler_module,
        "AutopilotStore",
        lambda database_url: FakeStore(),
    )
    monkeypatch.setattr(
        scheduler_module,
        "AutopilotJobEnqueuer",
        lambda redis_url: FakeEnqueuer(),
    )

    scheduler_module.run_scheduler(
        database_url="sqlite://",
        redis_url="redis://",
        stop_event=StepStop(),
        tick_seconds=1,
        now_fn=lambda: datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
    )

    assert [call["trigger"] for call in calls] == ["startup"]
