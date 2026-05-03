from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from app.ingestion.pipeline import PreparedTrack
from app.ingestion.status import IngestionStatusStore
from app.local_tracks.store import (
    local_tracks_table,
    metadata as local_tracks_metadata,
)
from app.main import create_app
from app.matching.pipeline import (
    metadata as suggested_links_metadata,
    suggested_links_table,
)
from app.streaming.schemas import CreateStreamingAccountRequest
from app.streaming.models import metadata, streaming_accounts_table
from app.streaming.store import StreamingAccountStore
from app.streaming.adapters.youtube_music import (
    YouTubeMusicPlaylist,
    YouTubeMusicTrack,
)
from sqlalchemy import create_engine, insert, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request


def test_links_routes_are_mounted_under_api_prefix() -> None:
    app = create_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/proposals" in route_paths
    assert "/api/proposals/{proposal_id}/approve" in route_paths
    assert "/api/proposals/{proposal_id}/reject" in route_paths
    assert "/api/final-links/{final_link_id}" in route_paths


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

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/streaming/accounts"
        and "POST" in getattr(route, "methods", set())
    )
    payload = CreateStreamingAccountRequest(
        display_name="Billie",
        browser_headers={
            "Authorization": "Bearer token",
            "X-Goog-AuthUser": "0",
        },
    )

    response = asyncio.run(route.endpoint(payload))

    assert response.id == 1
    assert response.provider == "youtube_music"
    assert response.display_name == "Billie"
    assert response.auth_state == "connected"
    assert response.auth_error is None
    assert response.auth_error_at is None
    assert response.created_at
    assert response.updated_at

    stored_account = StreamingAccountStore(database_url).get_account(response.id)
    assert stored_account.browser_headers == {
        "Authorization": "Bearer token",
        "X-Goog-AuthUser": "0",
    }


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
        ) -> str:
            seen["account_id"] = account_id
            return "sync-job-999"

    monkeypatch.setattr(
        "app.streaming.router.StreamingSyncJobEnqueuer", FakeSyncEnqueuer
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/streaming/accounts/{account_id}/sync"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(1))

    assert response.account_id == 1
    assert response.job_id == "sync-job-999"
    assert seen == {
        "redis_url": "redis://redis:6379/3",
        "account_id": 1,
    }


def test_matching_status_endpoint_lists_suggestions_with_confidence_bands(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'matching-status.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=7,
                file_path="Artist/track.mp3",
                library_root_rel_path="Artist/track.mp3",
                fingerprint="fp-7",
                beets_id=7,
            )
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "local_track_id": 7,
                    "streaming_track_id": 14,
                    "match_method": "isrc",
                    "score": 1.0,
                    "status": "pending",
                },
                {
                    "local_track_id": 7,
                    "streaming_track_id": 15,
                    "match_method": "tags",
                    "score": 0.62,
                    "status": "approved",
                },
            ],
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/matching/status"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint())

    assert response == {
        "status": "ok",
        "suggestions": [
            {
                "local_track_id": 7,
                "streaming_track_id": 14,
                "match_method": "isrc",
                "score": 1.0,
                "status": "pending",
                "confidence_band": "high",
            },
            {
                "local_track_id": 7,
                "streaming_track_id": 15,
                "match_method": "tags",
                "score": 0.62,
                "status": "approved",
                "confidence_band": "medium",
            },
        ],
    }


def test_matching_run_endpoint_enqueues_job_for_existing_local_track(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'matching-run.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/5")

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=11,
                file_path="Artist/run.mp3",
                library_root_rel_path="Artist/run.mp3",
                fingerprint="fp-11",
                beets_id=11,
            )
        )

    seen: dict[str, object] = {}

    class FakeMatchingEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue(self, local_track_id: int) -> str:
            seen["local_track_id"] = local_track_id
            return "match-job-123"

    monkeypatch.setattr("app.matching.router.MatchingJobEnqueuer", FakeMatchingEnqueuer)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/matching/tracks/{local_track_id}/run"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(11))

    assert response == {
        "local_track_id": 11,
        "job_id": "match-job-123",
    }
    assert seen == {
        "redis_url": "redis://redis:6379/5",
        "local_track_id": 11,
    }


def test_matching_run_endpoint_returns_404_for_unknown_local_track(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'matching-run-missing.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/6")

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/matching/tracks/{local_track_id}/run"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(route.endpoint(999))
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Local track not found"
    else:
        raise AssertionError("Expected HTTPException for missing local track")


def test_local_track_rematch_endpoint_clears_non_final_suggestions_and_enqueues_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-track-rematch.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/7")

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=15,
                file_path="Artist/rematch.mp3",
                library_root_rel_path="Artist/rematch.mp3",
                fingerprint="fp-15",
                beets_id=15,
            )
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "local_track_id": 15,
                    "streaming_track_id": 101,
                    "match_method": "tags",
                    "score": 0.2,
                    "status": "pending",
                },
                {
                    "local_track_id": 15,
                    "streaming_track_id": 102,
                    "match_method": "manual_break",
                    "score": 0.0,
                    "status": "rejected",
                },
                {
                    "local_track_id": 15,
                    "streaming_track_id": 103,
                    "match_method": "isrc",
                    "score": 1.0,
                    "status": "approved",
                },
            ],
        )

    seen: dict[str, object] = {}

    class FakeMatchingEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue(self, local_track_id: int) -> str:
            seen["local_track_id"] = local_track_id
            return "rematch-job-123"

    monkeypatch.setattr("app.matching.router.MatchingJobEnqueuer", FakeMatchingEnqueuer)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/local-tracks/{local_track_id}/rematch"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(15))

    assert response == {
        "local_track_id": 15,
        "job_id": "rematch-job-123",
    }
    assert seen == {
        "redis_url": "redis://redis:6379/7",
        "local_track_id": 15,
    }

    with engine.connect() as connection:
        suggestions = (
            connection.execute(
                select(suggested_links_table).order_by(suggested_links_table.c.id.asc())
            )
            .mappings()
            .all()
        )

    assert len(suggestions) == 2
    assert suggestions[0]["local_track_id"] == 15
    assert suggestions[0]["streaming_track_id"] == 102
    assert suggestions[0]["match_method"] == "manual_break"
    assert suggestions[0]["score"] == 0.0
    assert suggestions[0]["status"] == "rejected"
    assert suggestions[0]["rejected_at"] is None

    assert suggestions[1]["local_track_id"] == 15
    assert suggestions[1]["streaming_track_id"] == 103
    assert suggestions[1]["match_method"] == "isrc"
    assert suggestions[1]["score"] == 1.0
    assert suggestions[1]["status"] == "approved"
    assert suggestions[1]["rejected_at"] is None


def test_local_track_rematch_endpoint_returns_404_for_unknown_track(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-track-rematch-missing.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/8")

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/local-tracks/{local_track_id}/rematch"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(route.endpoint(999))
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Local track not found"
    else:
        raise AssertionError("Expected HTTPException for missing local track")
