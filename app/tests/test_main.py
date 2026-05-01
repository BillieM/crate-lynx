from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from app.ingest_status import IngestionStatusStore
from app.ingestion import PreparedTrack
from app.main import create_app
from starlette.requests import Request


def test_ingest_status_endpoint_reports_queue_depths_and_recent_results() -> None:
    app = create_app()

    timestamp = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    status_store = IngestionStatusStore(
        queue_depth_reader=lambda: {"ingestion": 2, "matching": 1},
        now=lambda: timestamp,
    )
    status_store.record_success(
        source_path=Path("/ingestion/track.mp3"),
        prepared_track=PreparedTrack(
            source_path=Path("/ingestion/track.mp3"),
            prepared_path=Path("/staging/track.mp3"),
            transcoded=False,
            fingerprint="fp-123",
            library_path=Path("/library/Artist/track.mp3"),
            local_track_id=9,
            matching_job_id="job-9",
        ),
    )
    app.state.ingestion_status = status_store

    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/ingest/status"
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ingest/status",
            "headers": [],
            "app": app,
        }
    )
    response = asyncio.run(route.endpoint(request))

    assert response == {
        "status": "ok",
        "queue_depths": {"ingestion": 2, "matching": 1},
        "recent_results": [
            {
                "timestamp": "2026-05-01T12:00:00+00:00",
                "status": "ok",
                "source_path": "/ingestion/track.mp3",
                "library_path": "/library/Artist/track.mp3",
                "fingerprint": "fp-123",
                "local_track_id": 9,
                "matching_job_id": "job-9",
                "error": None,
            }
        ],
    }


def test_ingestion_status_store_records_failures() -> None:
    timestamp = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
    status_store = IngestionStatusStore(
        queue_depth_reader=lambda: {"ingestion": None, "matching": None},
        now=lambda: timestamp,
    )

    status_store.record_failure(
        source_path=Path("/ingestion/bad.flac"),
        error=RuntimeError("ffmpeg failed"),
    )

    assert status_store.snapshot() == {
        "queue_depths": {"ingestion": None, "matching": None},
        "recent_results": [
            {
                "timestamp": "2026-05-01T12:30:00+00:00",
                "status": "error",
                "source_path": "/ingestion/bad.flac",
                "library_path": None,
                "fingerprint": None,
                "local_track_id": None,
                "matching_job_id": None,
                "error": "ffmpeg failed",
            }
        ],
    }
