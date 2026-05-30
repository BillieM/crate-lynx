from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, insert, select

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.sonic.jobs import (
    SONIC_FEATURE_EXTRACTION_FUNC,
    SONIC_FEATURE_RECONCILIATION_FUNC,
)
from app.sonic.models import (
    PLAYLIST_GENERATION_STATUS_COMPLETED,
    PLAYLIST_GENERATION_STATUS_FAILED,
    PLAYLIST_GENERATION_STATUS_PENDING,
    SONIC_ANALYZER_LIBROSA_V1,
    SONIC_FEATURE_STATUS_FAILED,
    SONIC_FEATURE_STATUS_PENDING,
    SONIC_FEATURE_STATUS_READY,
    generated_playlist_tracks_table,
    generated_playlists_table,
    metadata as sonic_metadata,
    playlist_generation_runs_table,
    sonic_track_features_table,
)
from app.sonic.router import create_router
from app.sonic.schemas import (
    CreatePlaylistGenerationRunRequest,
    DeletePlaylistGenerationRunsRequest,
    SonicBackfillRequest,
)
from tests.factories import TestDataFactory


def _call_endpoint(endpoint, *args, **kwargs):
    result = endpoint(*args, **kwargs)
    if inspect.isawaitable(result):
        raise AssertionError("Unexpected async sonic endpoint")
    return result


def _route(router, method: str, path: str):
    return next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def _create_engine(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    return engine


def test_sonic_feature_summary_endpoint_counts_tracks(tmp_path: Path) -> None:
    engine = _create_engine(tmp_path / "sonic-summary.db")
    factory = TestDataFactory(engine)
    ready_track_id = factory.local_track(file_path="A/Ready.mp3")
    factory.local_track(file_path="B/Missing.mp3")
    factory.sonic_track_feature(local_track_id=ready_track_id)

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "GET", "/sonic/features/summary").endpoint,
        engine=engine,
    )

    assert response.model_dump() == {
        "failed_tracks": 0,
        "missing_tracks": 1,
        "pending_tracks": 0,
        "ready_tracks": 1,
        "total_tracks": 2,
    }


def test_backfill_features_endpoint_claims_and_enqueues_immediately(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-backfill.db")
    factory = TestDataFactory(engine)
    ready_track_id = factory.local_track(file_path="A/Ready.mp3")
    missing_track_id = factory.local_track(file_path="B/Missing.mp3")
    untouched_missing_track_id = factory.local_track(file_path="C/Later.mp3")
    factory.sonic_track_feature(
        local_track_id=ready_track_id,
        status=SONIC_FEATURE_STATUS_READY,
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

    monkeypatch.setattr("app.sonic.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.sonic.jobs.Queue", FakeQueue)
    monkeypatch.setattr("app.sonic.jobs.Dependency", FakeDependency)

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "POST", "/sonic/features/backfill").endpoint,
        SonicBackfillRequest(limit=1),
        engine=engine,
    )

    assert response.job_id == "sonic-reconciliation-job"
    assert response.limit == 1
    assert seen == {
        "redis_url": "redis://example/0",
        "queue_name": "sonic",
        "connection": seen["connection"],
        "dependency_jobs": [f"sonic-job-{missing_track_id}"],
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
        ],
    }

    with engine.connect() as connection:
        rows = {
            int(row["local_track_id"]): row
            for row in connection.execute(select(sonic_track_features_table)).mappings()
        }

    assert rows[ready_track_id]["status"] == SONIC_FEATURE_STATUS_READY
    assert rows[missing_track_id]["status"] == SONIC_FEATURE_STATUS_PENDING
    assert untouched_missing_track_id not in rows


def test_create_generation_run_endpoint_persists_and_enqueues(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-create-run.db")
    seen: dict[str, object] = {}

    class FakeSonicJobEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue_generation(self, run_id: int) -> str:
            seen["run_id"] = run_id
            return "sonic-job-1"

    monkeypatch.setattr("app.sonic.router.SonicJobEnqueuer", FakeSonicJobEnqueuer)

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "POST", "/sonic/runs").endpoint,
        CreatePlaylistGenerationRunRequest.model_validate(
            {
                "generation_config": {
                    "clustering_method": "agglomerative",
                    "max_depth": 2,
                    "target_playlist_size": 12,
                    "min_playlist_size": 4,
                    "max_children": 3,
                    "feature_profile": "balanced_v1",
                    "random_seed": 11,
                },
                "source_filter": {
                    "source_type": "all_local",
                    "streaming_playlist_ids": [],
                    "tag_filters": [],
                },
            }
        ),
        engine=engine,
    )

    assert response.job_id == "sonic-job-1"
    assert response.run.status == "pending"
    assert response.run.generation_config["clustering_method"] == "agglomerative"
    assert response.run.generation_config["resolved_feature_profile"]["key"] == (
        "balanced_v1"
    )
    assert seen == {"redis_url": "redis://example/0", "run_id": response.run.id}


def test_list_generation_runs_uses_retained_run_ordinal_for_generation_number(
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-run-numbering.db")
    factory = TestDataFactory(engine)
    for _ in range(18):
        factory.playlist_generation_run(status=PLAYLIST_GENERATION_STATUS_COMPLETED)
    with engine.begin() as connection:
        connection.execute(
            insert(playlist_generation_runs_table).values(
                id=50,
                generation_config_json={"clustering_method": "kmeans"},
                playlist_count=43,
                source_filter_json={"source_type": "all_local"},
                status=PLAYLIST_GENERATION_STATUS_COMPLETED,
                track_count=1361,
            )
        )

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "GET", "/sonic/runs").endpoint,
        engine=engine,
    )

    newest_run = response.runs[0]
    assert newest_run.id == 50
    assert newest_run.generation_number == 19


def test_delete_generation_run_endpoint_removes_generated_tree(
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-delete-run.db")
    factory = TestDataFactory(engine)
    run_id = factory.playlist_generation_run(
        playlist_count=2,
        status=PLAYLIST_GENERATION_STATUS_COMPLETED,
        track_count=2,
    )
    first_track_id = factory.local_track(file_path="A/First.mp3")
    second_track_id = factory.local_track(file_path="A/Second.mp3")
    root_playlist_id = factory.generated_playlist(run_id=run_id, track_count=2)
    child_playlist_id = factory.generated_playlist(
        depth=1,
        name="Child",
        parent_playlist_id=root_playlist_id,
        position=1,
        run_id=run_id,
        track_count=1,
    )
    factory.generated_playlist_track(
        generated_playlist_id=root_playlist_id,
        local_track_id=first_track_id,
    )
    factory.generated_playlist_track(
        generated_playlist_id=child_playlist_id,
        local_track_id=second_track_id,
    )

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "DELETE", "/sonic/runs/{run_id}").endpoint,
        run_id,
        engine=engine,
    )

    assert response.status_code == 204
    with engine.connect() as connection:
        assert connection.execute(select(playlist_generation_runs_table)).all() == []
        assert connection.execute(select(generated_playlists_table)).all() == []
        assert connection.execute(select(generated_playlist_tracks_table)).all() == []


def test_delete_generation_run_endpoint_returns_404_for_missing_run(
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-delete-run-missing.db")
    router = create_router(require_redis_url=lambda: "redis://example/0")

    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint(
            _route(router, "DELETE", "/sonic/runs/{run_id}").endpoint,
            404,
            engine=engine,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Generation run not found"


def test_delete_generation_run_endpoint_blocks_active_run(
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-delete-run-active.db")
    run_id = TestDataFactory(engine).playlist_generation_run(
        status=PLAYLIST_GENERATION_STATUS_PENDING
    )
    router = create_router(require_redis_url=lambda: "redis://example/0")

    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint(
            _route(router, "DELETE", "/sonic/runs/{run_id}").endpoint,
            run_id,
            engine=engine,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Active generation runs cannot be deleted"


def test_delete_selected_generation_runs_reports_partial_outcomes(
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-delete-selected-runs.db")
    factory = TestDataFactory(engine)
    deletable_run_id = factory.playlist_generation_run(
        playlist_count=1,
        status=PLAYLIST_GENERATION_STATUS_COMPLETED,
        track_count=1,
    )
    active_run_id = factory.playlist_generation_run(
        status=PLAYLIST_GENERATION_STATUS_PENDING,
    )
    track_id = factory.local_track(file_path="A/First.mp3")
    playlist_id = factory.generated_playlist(
        run_id=deletable_run_id,
        track_count=1,
    )
    factory.generated_playlist_track(
        generated_playlist_id=playlist_id,
        local_track_id=track_id,
    )

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "POST", "/sonic/runs/delete-selected").endpoint,
        DeletePlaylistGenerationRunsRequest(
            run_ids=[deletable_run_id, active_run_id, 404, deletable_run_id],
        ),
        engine=engine,
    )

    assert response.model_dump() == {
        "deleted_run_ids": [deletable_run_id],
        "missing_run_ids": [404],
        "skipped_active_run_ids": [active_run_id],
    }
    with engine.connect() as connection:
        remaining_run_ids = [
            row.id
            for row in connection.execute(
                select(playlist_generation_runs_table.c.id)
            ).all()
        ]
        assert remaining_run_ids == [active_run_id]
        assert connection.execute(select(generated_playlists_table)).all() == []
        assert connection.execute(select(generated_playlist_tracks_table)).all() == []


def test_create_generation_run_marks_run_failed_when_enqueue_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = _create_engine(tmp_path / "sonic-create-run-enqueue-fail.db")

    class FakeSonicJobEnqueuer:
        def __init__(self, redis_url: str) -> None:
            self.redis_url = redis_url

        def enqueue_generation(self, run_id: int) -> str:
            raise RuntimeError(f"redis unavailable for run {run_id}")

    monkeypatch.setattr("app.sonic.router.SonicJobEnqueuer", FakeSonicJobEnqueuer)

    router = create_router(require_redis_url=lambda: "redis://example/0")
    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint(
            _route(router, "POST", "/sonic/runs").endpoint,
            CreatePlaylistGenerationRunRequest.model_validate(
                {
                    "generation_config": {"feature_profile": "balanced_v1"},
                    "source_filter": {"source_type": "all_local"},
                }
            ),
            engine=engine,
        )

    assert exc_info.value.status_code == 503
    with engine.connect() as connection:
        row = (
            connection.execute(select(playlist_generation_runs_table)).mappings().one()
        )

    assert row["status"] == PLAYLIST_GENERATION_STATUS_FAILED
    assert "redis unavailable" in row["error_detail"]


def test_preview_generation_run_endpoint_counts_selected_source(tmp_path: Path) -> None:
    engine = _create_engine(tmp_path / "sonic-preview.db")
    factory = TestDataFactory(engine)
    ready_track_id = factory.local_track(file_path="Ready.mp3")
    failed_track_id = factory.local_track(file_path="Failed.mp3")
    old_track_id = factory.local_track(file_path="Old.mp3")
    factory.local_track(file_path="Missing.mp3")
    factory.sonic_track_feature(local_track_id=ready_track_id)
    factory.sonic_track_feature(
        local_track_id=failed_track_id,
        status=SONIC_FEATURE_STATUS_FAILED,
    )
    factory.sonic_track_feature(
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="0",
        local_track_id=old_track_id,
    )

    router = create_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "POST", "/sonic/runs/preview").endpoint,
        CreatePlaylistGenerationRunRequest.model_validate(
            {
                "generation_config": {"feature_profile": "texture_v1"},
                "source_filter": {"source_type": "all_local"},
            }
        ),
        engine=engine,
    )

    assert response.model_dump() == {
        "analyzer_key": SONIC_ANALYZER_LIBROSA_V1,
        "analyzer_version": "1",
        "can_generate": True,
        "failed_feature_count": 1,
        "feature_profile": "texture_v1",
        "missing_feature_count": 1,
        "pending_feature_count": 0,
        "projection": {
            "config_notes": [
                "Ready tracks are below the minimum size, so expect one small playlist."
            ],
            "depth_counts": {"0": 1},
            "leaf_playlist_count": 1,
            "mode": "estimated",
            "playlist_count": 1,
            "sample_names": [
                "Ambient Dub / 84-102 BPM",
                "Fastest / Peak",
                "Warm-up / Low Energy + Warm",
            ],
            "size_max": 1,
            "size_median": 1,
            "size_min": 1,
        },
        "ready_track_count": 1,
        "skipped_track_count": 3,
        "source_track_count": 4,
    }
