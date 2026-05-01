from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from app.ingest_status import IngestionStatusStore
from app.ingestion import PreparedTrack
from app.main import (
    CreateStreamingAccountRequest,
    SyncStreamingAccountRequest,
    create_app,
)
from app.streaming_accounts import metadata, streaming_accounts_table
from sqlalchemy import create_engine, insert
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


def test_streaming_accounts_endpoint_lists_persisted_accounts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Main Account",
                auth_token_blob="encrypted-token",
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/streaming/accounts"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint())

    assert len(response["accounts"]) == 1
    account = response["accounts"][0]
    assert account.id == 1
    assert account.provider == "youtube_music"
    assert account.display_name == "Main Account"
    assert account.created_at
    assert account.updated_at


def test_streaming_accounts_endpoint_creates_youtube_music_account(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-create.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    seen: dict[str, object] = {}

    def fake_setup_oauth(credentials, *, filepath=None, open_browser=False):
        seen["credentials"] = credentials
        seen["filepath"] = filepath
        seen["open_browser"] = open_browser
        return {"refresh_token": "refresh-token"}

    monkeypatch.setattr(
        "app.streaming_accounts.YouTubeMusicAdapter.setup_oauth",
        fake_setup_oauth,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/streaming/accounts"
        and "POST" in getattr(route, "methods", set())
    )
    payload = CreateStreamingAccountRequest(
        display_name="Billie",
        client_id="client-id",
        client_secret="client-secret",
        open_browser=True,
    )

    response = asyncio.run(route.endpoint(payload))

    assert response.id == 1
    assert response.provider == "youtube_music"
    assert response.display_name == "Billie"
    assert response.created_at
    assert response.updated_at
    assert seen["filepath"] is None
    assert seen["open_browser"] is True
    assert seen["credentials"].client_id == "client-id"
    assert seen["credentials"].client_secret == "client-secret"


def test_streaming_account_sync_endpoint_enqueues_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-sync.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/3")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Syncable Account",
                auth_token_blob="encrypted-token",
            )
        )

    seen: dict[str, object] = {}

    class FakeSyncEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue(
            self,
            *,
            account_id: int,
            client_id: str,
            client_secret: str,
        ) -> str:
            seen["account_id"] = account_id
            seen["client_id"] = client_id
            seen["client_secret"] = client_secret
            return "sync-job-999"

    monkeypatch.setattr("app.main.StreamingSyncJobEnqueuer", FakeSyncEnqueuer)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/streaming/accounts/{account_id}/sync"
        and "POST" in getattr(route, "methods", set())
    )
    payload = SyncStreamingAccountRequest(
        client_id="client-id",
        client_secret="client-secret",
    )

    response = asyncio.run(route.endpoint(1, payload))

    assert response.account_id == 1
    assert response.job_id == "sync-job-999"
    assert seen == {
        "redis_url": "redis://redis:6379/3",
        "account_id": 1,
        "client_id": "client-id",
        "client_secret": "client-secret",
    }
