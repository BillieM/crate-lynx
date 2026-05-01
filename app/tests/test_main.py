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
from app.streaming_accounts import (
    StreamingAccountStore,
    metadata,
    streaming_accounts_table,
)
from app.youtube_music import YouTubeMusicPlaylist, YouTubeMusicTrack
from sqlalchemy import create_engine, insert
from starlette.requests import Request
from starlette.responses import Response


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
                auth_state="connected",
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
    assert account.auth_state == "connected"
    assert account.auth_error is None
    assert account.auth_error_at is None
    assert account.created_at
    assert account.updated_at


def test_streaming_playlists_endpoint_lists_synced_playlists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlists.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    with engine.begin() as connection:
        account_id = connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Main Account",
                auth_token_blob="encrypted-token",
                auth_state="connected",
            )
        ).inserted_primary_key[0]

    store = StreamingAccountStore(database_url)
    playlists = store.upsert_playlists(
        account_id=account_id,
        playlists=[
            YouTubeMusicPlaylist(
                provider_playlist_id="PL1",
                title="Morning Mix",
            ),
            YouTubeMusicPlaylist(
                provider_playlist_id="PL2",
                title="Empty Playlist",
            ),
        ],
        synced_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
    )
    store.replace_playlist_membership(
        playlist_id=playlists[0].id,
        tracks=[
            YouTubeMusicTrack(
                provider_track_id="track-1",
                title="Track 1",
                artist="Artist 1",
                album=None,
                year=None,
                isrc=None,
                duration_ms=180000,
            ),
            YouTubeMusicTrack(
                provider_track_id="track-2",
                title="Track 2",
                artist="Artist 2",
                album=None,
                year=None,
                isrc=None,
                duration_ms=200000,
            ),
        ],
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/streaming/playlists"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint())

    assert len(response["playlists"]) == 2
    playlist = response["playlists"][0]
    assert playlist.account_id == 1
    assert playlist.provider_playlist_id == "PL1"
    assert playlist.title == "Morning Mix"
    assert playlist.track_count == 2
    assert playlist.synced_at == "2026-05-01T09:00:00"
    assert response["playlists"][1].provider_playlist_id == "PL2"
    assert response["playlists"][1].track_count == 0


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

    def fake_begin_oauth(credentials):
        seen["credentials"] = credentials
        return {
            "device_code": "device-code",
            "user_code": "ABC-DEF-GHIJ",
            "verification_url": "https://example.com/device",
            "expires_in": 1800,
            "interval": 5,
        }

    monkeypatch.setattr(
        "app.main.begin_youtube_music_account_oauth",
        fake_begin_oauth,
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

    http_response = Response()
    response = asyncio.run(route.endpoint(payload, http_response))

    assert response.device_code == "device-code"
    assert response.user_code == "ABC-DEF-GHIJ"
    assert response.verification_url == "https://example.com/device"
    assert response.expires_in == 1800
    assert response.interval == 5
    assert http_response.status_code == 202
    assert seen["credentials"].client_id == "client-id"
    assert seen["credentials"].client_secret == "client-secret"


def test_streaming_accounts_endpoint_completes_youtube_music_account(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-create-complete.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    seen: dict[str, object] = {}

    def fake_complete_oauth(
        *,
        database_url: str,
        display_name: str,
        credentials,
        device_code: str,
    ):
        seen["database_url"] = database_url
        seen["display_name"] = display_name
        seen["credentials"] = credentials
        seen["device_code"] = device_code
        return StreamingAccountStore(database_url).create_youtube_music_account(
            display_name=display_name,
            oauth_token={"refresh_token": "refresh-token"},
        )

    monkeypatch.setattr(
        "app.main.complete_youtube_music_account_oauth",
        fake_complete_oauth,
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
        device_code="device-code",
    )

    http_response = Response()
    response = asyncio.run(route.endpoint(payload, http_response))

    assert response.id == 1
    assert response.provider == "youtube_music"
    assert response.display_name == "Billie"
    assert response.auth_state == "connected"
    assert response.auth_error is None
    assert response.auth_error_at is None
    assert response.created_at
    assert response.updated_at
    assert http_response.status_code == 200
    assert seen["database_url"] == database_url
    assert seen["display_name"] == "Billie"
    assert seen["device_code"] == "device-code"
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
                auth_state="connected",
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
