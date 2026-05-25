from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select

from app.local_tracks.store import metadata as local_tracks_metadata
from app.sonic.jobs import (
    SONIC_FEATURE_BACKFILL_FUNC,
    SONIC_FEATURE_EXTRACTION_FUNC,
    SONIC_FEATURE_RECONCILIATION_FUNC,
    SonicJobEnqueuer,
    reconcile_failed_sonic_feature_jobs,
    run_sonic_feature_backfill_job,
)
from app.sonic.models import (
    DEFAULT_SONIC_BACKFILL_LIMIT,
    MAX_SONIC_FEATURE_ATTEMPTS,
    SONIC_FEATURE_STATUS_FAILED,
    SONIC_FEATURE_STATUS_PENDING,
    SONIC_FEATURE_STATUS_READY,
    metadata as sonic_metadata,
    sonic_track_features_table,
)
from app.sonic.store import SonicStore
from tests.factories import TestDataFactory


def test_sonic_job_enqueuer_uses_default_backfill_limit(monkeypatch) -> None:
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
            self, func: str, limit: int, *, job_timeout: str
        ) -> SimpleNamespace:
            seen["func"] = func
            seen["limit"] = limit
            seen["job_timeout"] = job_timeout
            return SimpleNamespace(id="sonic-backfill-job")

    monkeypatch.setattr("app.sonic.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.sonic.jobs.Queue", FakeQueue)

    job_id = SonicJobEnqueuer(
        redis_url="redis://redis:6379/0"
    ).enqueue_feature_backfill()

    assert job_id == "sonic-backfill-job"
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "sonic",
        "connection": seen["connection"],
        "func": SONIC_FEATURE_BACKFILL_FUNC,
        "limit": DEFAULT_SONIC_BACKFILL_LIMIT,
        "job_timeout": "30m",
    }


def test_run_sonic_feature_backfill_claims_and_enqueues_extraction_jobs(
    monkeypatch,
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'sonic-jobs.db'}")
    local_tracks_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    ready_track_id = factory.local_track(file_path="Ready.mp3")
    missing_track_id = factory.local_track(file_path="Missing.mp3")
    failed_track_id = factory.local_track(file_path="Failed.mp3")
    untouched_missing_track_id = factory.local_track(file_path="Later.mp3")
    factory.sonic_track_feature(
        local_track_id=ready_track_id,
        status=SONIC_FEATURE_STATUS_READY,
    )
    factory.sonic_track_feature(
        failure_detail="bad decode",
        local_track_id=failed_track_id,
        status=SONIC_FEATURE_STATUS_FAILED,
    )
    seen: dict[str, object] = {"jobs": []}

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
            local_track_id: int | None = None,
            *,
            depends_on: object | None = None,
            job_timeout: str,
        ) -> SimpleNamespace:
            if func == SONIC_FEATURE_RECONCILIATION_FUNC:
                seen["reconciliation_job"] = (func, job_timeout, depends_on)
                return SimpleNamespace(id="sonic-reconciliation-job")
            seen["jobs"].append((func, local_track_id, job_timeout))
            return SimpleNamespace(id=f"sonic-job-{local_track_id}")

    class FakeDependency:
        def __init__(self, *, jobs: list[SimpleNamespace], allow_failure: bool) -> None:
            seen["dependency_jobs"] = [job.id for job in jobs]
            seen["dependency_allow_failure"] = allow_failure

    class FakeFailedJobRegistry:
        def __init__(self, name: str, connection: object) -> None:
            seen["failed_registry_name"] = name
            seen["failed_registry_connection"] = connection

        def get_job_ids(self) -> list[str]:
            return []

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sonic-jobs.db'}")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr("app.sonic.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.sonic.jobs.Queue", FakeQueue)
    monkeypatch.setattr("app.sonic.jobs.Dependency", FakeDependency)
    monkeypatch.setattr("app.sonic.jobs.FailedJobRegistry", FakeFailedJobRegistry)

    job_ids = run_sonic_feature_backfill_job(limit=2)

    assert job_ids == [
        f"sonic-job-{missing_track_id}",
        f"sonic-job-{failed_track_id}",
    ]
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "sonic",
        "connection": seen["connection"],
        "failed_registry_name": "sonic",
        "failed_registry_connection": seen["failed_registry_connection"],
        "dependency_jobs": [
            f"sonic-job-{missing_track_id}",
            f"sonic-job-{failed_track_id}",
        ],
        "dependency_allow_failure": True,
        "reconciliation_job": (
            SONIC_FEATURE_RECONCILIATION_FUNC,
            "30m",
            seen["reconciliation_job"][2],
        ),
        "jobs": [
            (
                SONIC_FEATURE_EXTRACTION_FUNC,
                missing_track_id,
                "30m",
            ),
            (
                SONIC_FEATURE_EXTRACTION_FUNC,
                failed_track_id,
                "30m",
            ),
        ],
    }

    with engine.connect() as connection:
        rows = {
            int(row["local_track_id"]): row
            for row in connection.execute(select(sonic_track_features_table)).mappings()
        }

    assert rows[ready_track_id]["status"] == SONIC_FEATURE_STATUS_READY
    assert rows[missing_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert rows[missing_track_id]["failure_detail"] is None
    assert rows[missing_track_id]["attempt_count"] == 0
    assert rows[failed_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert rows[failed_track_id]["failure_detail"] is None
    assert rows[failed_track_id]["attempt_count"] == 0
    assert untouched_missing_track_id not in rows


def test_reconcile_failed_sonic_feature_jobs_marks_pending_rows_failed(
    monkeypatch,
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'sonic-reconcile.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    local_track_id = factory.local_track(file_path="Crash.mp3")
    factory.sonic_track_feature(
        attempt_count=1,
        local_track_id=local_track_id,
        status=SONIC_FEATURE_STATUS_PENDING,
    )
    seen: dict[str, object] = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeFailedJobRegistry:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def get_job_ids(self) -> list[str]:
            return ["failed-job-1"]

    class FakeJob:
        @staticmethod
        def fetch(job_id: str, connection: object) -> SimpleNamespace:
            seen["fetched_job_id"] = job_id
            seen["fetch_connection"] = connection
            return SimpleNamespace(
                id=job_id,
                func_name=SONIC_FEATURE_EXTRACTION_FUNC,
                args=(local_track_id,),
                exc_info="Work-horse terminated unexpectedly; waitpid returned 139",
            )

    monkeypatch.setattr("app.sonic.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.sonic.jobs.FailedJobRegistry", FakeFailedJobRegistry)
    monkeypatch.setattr("app.sonic.jobs.Job", FakeJob)

    reconciled_count = reconcile_failed_sonic_feature_jobs(
        database_url=database_url,
        redis_url="redis://redis:6379/0",
    )

    assert reconciled_count == 1
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "sonic",
        "connection": seen["connection"],
        "fetched_job_id": "failed-job-1",
        "fetch_connection": seen["connection"],
    }

    with engine.connect() as connection:
        row = connection.execute(select(sonic_track_features_table)).mappings().one()

    assert row["status"] == SONIC_FEATURE_STATUS_FAILED
    assert row["attempt_count"] == 1
    assert "failed-job-1" in row["failure_detail"]
    assert "waitpid returned 139" in row["failure_detail"]


def test_claim_missing_feature_track_ids_reclaims_stale_pending_with_retry_budget(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'sonic-claims.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    now = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    stale_pending_track_id = factory.local_track(file_path="Stale.mp3")
    fresh_pending_track_id = factory.local_track(file_path="Fresh.mp3")
    exhausted_failed_track_id = factory.local_track(file_path="Exhausted.mp3")
    outdated_ready_track_id = factory.local_track(file_path="Outdated.mp3")
    missing_track_id = factory.local_track(file_path="Missing.mp3")
    factory.sonic_track_feature(
        attempt_count=1,
        local_track_id=stale_pending_track_id,
        status=SONIC_FEATURE_STATUS_PENDING,
        updated_at=now - timedelta(hours=2),
    )
    factory.sonic_track_feature(
        attempt_count=1,
        local_track_id=fresh_pending_track_id,
        status=SONIC_FEATURE_STATUS_PENDING,
        updated_at=now - timedelta(minutes=30),
    )
    factory.sonic_track_feature(
        attempt_count=MAX_SONIC_FEATURE_ATTEMPTS,
        failure_detail="crashed too often",
        local_track_id=exhausted_failed_track_id,
        status=SONIC_FEATURE_STATUS_FAILED,
        updated_at=now - timedelta(hours=2),
    )
    factory.sonic_track_feature(
        analyzer_version="0",
        attempt_count=MAX_SONIC_FEATURE_ATTEMPTS,
        local_track_id=outdated_ready_track_id,
        status=SONIC_FEATURE_STATUS_READY,
        updated_at=now - timedelta(hours=2),
    )

    claimed_ids = SonicStore(database_url).claim_missing_feature_track_ids(
        analyzer_key="librosa_v1",
        analyzer_version="1",
        limit=10,
        max_attempts=MAX_SONIC_FEATURE_ATTEMPTS,
        pending_stale_before=now - timedelta(hours=1),
    )

    assert claimed_ids == [
        stale_pending_track_id,
        outdated_ready_track_id,
        missing_track_id,
    ]

    with engine.connect() as connection:
        rows = {
            int(row["local_track_id"]): row
            for row in connection.execute(select(sonic_track_features_table)).mappings()
        }

    assert rows[stale_pending_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert rows[stale_pending_track_id]["failure_detail"] is None
    assert rows[stale_pending_track_id]["attempt_count"] == 1
    assert rows[fresh_pending_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert rows[fresh_pending_track_id]["attempt_count"] == 1
    assert rows[exhausted_failed_track_id]["status"] == SONIC_FEATURE_STATUS_FAILED
    assert (
        rows[exhausted_failed_track_id]["attempt_count"] == MAX_SONIC_FEATURE_ATTEMPTS
    )
    assert rows[outdated_ready_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert rows[outdated_ready_track_id]["analyzer_version"] == "1"
    assert rows[outdated_ready_track_id]["attempt_count"] == 0
    assert rows[missing_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert rows[missing_track_id]["attempt_count"] == 0
