from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import create_engine

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.sonic.models import metadata as sonic_metadata
from app.sonic.router import create_router
from app.sonic.schemas import CreatePlaylistGenerationRunRequest
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
    assert seen == {"redis_url": "redis://example/0", "run_id": response.run.id}
