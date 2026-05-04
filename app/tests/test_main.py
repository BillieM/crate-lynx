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
from app.links.store import final_links_table, metadata as links_metadata
from app.main import create_app
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_PENDING,
    metadata as suggested_links_metadata,
    suggested_links_table,
)
from app.streaming.schemas import (
    CreateStreamingAccountRequest,
    UpdateStreamingPlaylistRequest,
)
from app.streaming.models import metadata, streaming_accounts_table
from app.streaming.models import (
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
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
    assert "/api/search" in route_paths
    assert "/api/proposals/{proposal_id}/approve" in route_paths
    assert "/api/proposals/{proposal_id}/reject" in route_paths
    assert "/api/final-links/{final_link_id}" in route_paths
    assert "/local-tracks/{local_track_id}/rescue" in route_paths
    assert "/api/playlists/{playlist_id}" in route_paths
    assert "/api/playlists/{playlist_id}/tracks" in route_paths
    assert "/api/playlists/{playlist_id}/m3u" in route_paths
    assert "/api/library/tracks" in route_paths
    assert "/api/streaming/accounts/{account_id}/sync" in route_paths
    assert "/api/streaming/accounts/{account_id}/refresh-metadata" in route_paths
    assert "/api/streaming/playlists/config" in route_paths
    assert "/api/streaming/playlists/{playlist_id}" in route_paths
    assert "/api/streaming/playlists/{playlist_id}/sync" in route_paths
    assert "/api/local-tracks/{local_track_id}/rematch" in route_paths


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
        if getattr(route, "path", None) == "/api/streaming/accounts"
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
    store.set_playlist_selected_for_sync(
        playlist_id=playlists[0].id,
        selected_for_sync=True,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint())

    assert len(response["playlists"]) == 1
    playlist = response["playlists"][0]
    assert playlist.account_id == 1
    assert playlist.provider_playlist_id == "PL1"
    assert playlist.title == "Morning Mix"
    assert playlist.track_count == 2
    assert playlist.synced_at == "2026-05-01T09:00:00"


def test_streaming_playlists_config_endpoint_lists_all_discovered_playlists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlists-config.db'}"
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
            )
        ],
    )
    store.set_playlist_selected_for_sync(
        playlist_id=playlists[0].id,
        selected_for_sync=True,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists/config"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint())

    assert [playlist.provider_playlist_id for playlist in response["playlists"]] == [
        "PL1",
        "PL2",
    ]
    selected, unselected = response["playlists"]
    assert selected.selected_for_sync is True
    assert selected.track_count == 1
    assert selected.synced_at == "2026-05-01T09:00:00"
    assert selected.last_sync_error is None
    assert selected.last_sync_error_at is None
    assert unselected.selected_for_sync is False
    assert unselected.track_count == 0


def test_streaming_playlist_patch_endpoint_toggles_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlist-patch.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    m3u_path = tmp_path / "m3u" / "Morning-Mix.m3u"
    m3u_path.parent.mkdir()
    m3u_path.write_text("existing m3u", encoding="utf-8")

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlist = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(
                provider_playlist_id="PL1",
                title="Morning Mix",
            )
        ],
        synced_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
    )[0]
    store.replace_playlist_membership(
        playlist_id=playlist.id,
        tracks=[
            YouTubeMusicTrack(
                provider_track_id="track-1",
                title="Track 1",
                artist="Artist 1",
                album=None,
                year=None,
                isrc=None,
                duration_ms=180000,
            )
        ],
    )
    store.set_playlist_selected_for_sync(
        playlist_id=playlist.id,
        selected_for_sync=True,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists/{playlist_id}"
        and "PATCH" in getattr(route, "methods", set())
    )
    response = asyncio.run(
        route.endpoint(
            playlist.id,
            UpdateStreamingPlaylistRequest(selected_for_sync=False),
        )
    )

    assert response.id == playlist.id
    assert response.selected_for_sync is False
    assert response.track_count == 1
    with engine.connect() as connection:
        memberships = connection.execute(select(playlist_membership_table)).all()
    assert len(memberships) == 1
    assert m3u_path.read_text(encoding="utf-8") == "existing m3u"


def test_streaming_playlist_patch_endpoint_returns_404_for_missing_playlist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlist-patch-missing.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists/{playlist_id}"
        and "PATCH" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(
            route.endpoint(
                999,
                UpdateStreamingPlaylistRequest(selected_for_sync=True),
            )
        )
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Playlist not found"
    else:
        raise AssertionError("Expected playlist update to return 404")


def test_search_endpoint_returns_playlist_streaming_and_local_matches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'search.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
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
        playlist_id = connection.execute(
            insert(streaming_playlists_table).values(
                account_id=account_id,
                provider_playlist_id="mix-1",
                title="Morning Mix",
            )
        ).inserted_primary_key[0]
        streaming_track_id = connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="track-1",
                title="Mix Tape",
                artist="DJ Example",
                album="Morning Blend",
                year=2026,
                isrc=None,
                duration_ms=180000,
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=playlist_id,
                streaming_track_id=streaming_track_id,
                position=0,
            )
        )
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Mixdown.mp3",
                library_root_rel_path="Artist/Mixdown.mp3",
                fingerprint=None,
                beets_id=None,
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/search"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(q="mix"))

    assert response.query == "mix"
    assert [result.kind for result in response.results] == [
        "playlist",
        "streaming_track",
        "local_track",
    ]
    assert response.results[0].title == "Morning Mix"
    assert response.results[0].subtitle == "Playlist • 1 tracks"
    assert response.results[1].subtitle == "DJ Example • Morning Blend"
    assert response.results[2].route_path == "/local-library"


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
        if getattr(route, "path", None) == "/api/streaming/accounts"
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


def test_playlist_detail_endpoint_returns_real_link_counts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'playlist-detail.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
                synced_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
            )
        )
        connection.execute(
            insert(local_tracks_table),
            [
                {
                    "id": 5,
                    "file_path": "Artist/linked.mp3",
                    "library_root_rel_path": "Artist/linked.mp3",
                },
                {
                    "id": 6,
                    "file_path": "Artist/pending.mp3",
                    "library_root_rel_path": "Artist/pending.mp3",
                },
            ],
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 9,
                    "provider_track_id": "ytm-9",
                    "title": "Linked Song",
                    "artist": "Artist",
                },
                {
                    "id": 10,
                    "provider_track_id": "ytm-10",
                    "title": "Pending Song",
                    "artist": "Artist",
                },
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "Unlinked Song",
                    "artist": "Artist",
                },
            ],
        )
        connection.execute(
            insert(playlist_membership_table),
            [
                {"playlist_id": 7, "streaming_track_id": 9, "position": 1},
                {"playlist_id": 7, "streaming_track_id": 10, "position": 2},
                {"playlist_id": 7, "streaming_track_id": 11, "position": 3},
            ],
        )
        connection.execute(
            insert(final_links_table).values(
                id=3,
                local_track_id=5,
                streaming_track_id=9,
            )
        )
        connection.execute(
            insert(suggested_links_table).values(
                id=4,
                local_track_id=6,
                streaming_track_id=10,
                match_method="tag",
                score=0.82,
                status=SUGGESTED_LINK_STATUS_PENDING,
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/playlists/{playlist_id}"
        and "GET" in getattr(route, "methods", set())
    )

    response = asyncio.run(route.endpoint(7))

    assert response.playlist.id == 7
    assert response.playlist.name == "Road Trip Mix"
    assert response.playlist.cover_art_url is None
    assert response.playlist.track_count == 3
    assert response.playlist.linked_count == 1
    assert response.playlist.pending_count == 1
    assert response.playlist.unlinked_count == 1
    assert response.playlist.synced_at == "2026-05-01T09:00:00"


def test_playlist_tracks_endpoint_returns_rows_with_link_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'playlist-tracks.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
            )
        )
        connection.execute(
            insert(local_tracks_table),
            [
                {
                    "id": 5,
                    "file_path": "Artist/linked.mp3",
                    "library_root_rel_path": "Artist/linked.mp3",
                },
                {
                    "id": 6,
                    "file_path": "Artist/pending.mp3",
                    "library_root_rel_path": "Artist/pending.mp3",
                },
            ],
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 9,
                    "provider_track_id": "ytm-9",
                    "title": "Linked Song",
                    "artist": "Artist A",
                    "album": "Album A",
                    "duration_ms": 181000,
                },
                {
                    "id": 10,
                    "provider_track_id": "ytm-10",
                    "title": "Pending Song",
                    "artist": "Artist B",
                    "album": None,
                    "duration_ms": None,
                },
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "Unlinked Song",
                    "artist": "Artist C",
                    "album": "Album C",
                    "duration_ms": 200000,
                },
            ],
        )
        connection.execute(
            insert(playlist_membership_table),
            [
                {"playlist_id": 7, "streaming_track_id": 9, "position": 1},
                {"playlist_id": 7, "streaming_track_id": 10, "position": 2},
                {"playlist_id": 7, "streaming_track_id": 11, "position": 3},
            ],
        )
        connection.execute(
            insert(final_links_table).values(
                id=3,
                local_track_id=5,
                streaming_track_id=9,
            )
        )
        connection.execute(
            insert(suggested_links_table).values(
                id=4,
                local_track_id=6,
                streaming_track_id=10,
                match_method="tag",
                score=0.82,
                status=SUGGESTED_LINK_STATUS_PENDING,
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/playlists/{playlist_id}/tracks"
        and "GET" in getattr(route, "methods", set())
    )

    response = asyncio.run(route.endpoint(7))

    assert [track.title for track in response.tracks] == [
        "Linked Song",
        "Pending Song",
        "Unlinked Song",
    ]
    assert [track.position for track in response.tracks] == [1, 2, 3]
    assert response.tracks[0].status == "linked"
    assert response.tracks[0].final_link_id == 3
    assert response.tracks[0].local_track_id == 5
    assert response.tracks[0].proposal_id is None
    assert response.tracks[1].status == "pending"
    assert response.tracks[1].final_link_id is None
    assert response.tracks[1].local_track_id == 6
    assert response.tracks[1].proposal_id == 4
    assert response.tracks[2].status == "unlinked"
    assert response.tracks[2].local_track_id is None


def test_library_tracks_endpoint_returns_linked_pending_unlinked_and_no_match_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'library-tracks.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table),
            [
                {
                    "id": 5,
                    "file_path": "Artist/linked.mp3",
                    "library_root_rel_path": "Artist/linked.mp3",
                    "fingerprint": "fp-linked",
                    "beets_id": 5,
                },
                {
                    "id": 6,
                    "file_path": "Artist/pending.mp3",
                    "library_root_rel_path": "Artist/pending.mp3",
                    "fingerprint": "fp-pending",
                    "beets_id": 6,
                },
                {
                    "id": 7,
                    "file_path": "Artist/rejected-only.mp3",
                    "library_root_rel_path": "Artist/rejected-only.mp3",
                    "fingerprint": "fp-rejected",
                    "beets_id": 7,
                },
                {
                    "id": 8,
                    "file_path": "Loose/no-match.flac",
                    "library_root_rel_path": "Loose/no-match.flac",
                    "fingerprint": None,
                    "beets_id": None,
                },
            ],
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 9,
                    "provider_track_id": "ytm-9",
                    "title": "Linked Song",
                    "artist": "Artist A",
                    "album": "Album A",
                    "duration_ms": 181000,
                },
                {
                    "id": 10,
                    "provider_track_id": "ytm-10",
                    "title": "Pending Song",
                    "artist": "Artist B",
                    "album": None,
                    "duration_ms": None,
                },
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "Rejected Song",
                    "artist": "Artist C",
                    "album": "Album C",
                    "duration_ms": 200000,
                },
            ],
        )
        connection.execute(
            insert(final_links_table).values(
                id=3,
                local_track_id=5,
                streaming_track_id=9,
            )
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "id": 4,
                    "local_track_id": 5,
                    "streaming_track_id": 9,
                    "match_method": "isrc",
                    "score": 0.99,
                    "status": SUGGESTED_LINK_STATUS_APPROVED,
                },
                {
                    "id": 5,
                    "local_track_id": 6,
                    "streaming_track_id": 10,
                    "match_method": "tags",
                    "score": 0.82,
                    "status": SUGGESTED_LINK_STATUS_PENDING,
                },
                {
                    "id": 6,
                    "local_track_id": 7,
                    "streaming_track_id": 11,
                    "match_method": "tags",
                    "score": 0.42,
                    "status": "rejected",
                },
            ],
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/library/tracks"
        and "GET" in getattr(route, "methods", set())
    )

    response = asyncio.run(route.endpoint())

    assert [track.id for track in response.tracks] == [5, 6, 7, 8]
    assert response.model_dump(mode="json") == {
        "tracks": [
            {
                "id": 5,
                "title": "Linked Song",
                "artist": "Artist A",
                "album": "Album A",
                "duration_ms": 181000,
                "file_path": "Artist/linked.mp3",
                "library_root_rel_path": "Artist/linked.mp3",
                "link_status": "linked",
                "match_method": "isrc",
                "file_status": "available",
            },
            {
                "id": 6,
                "title": "Pending Song",
                "artist": "Artist B",
                "album": None,
                "duration_ms": None,
                "file_path": "Artist/pending.mp3",
                "library_root_rel_path": "Artist/pending.mp3",
                "link_status": "pending",
                "match_method": "tags",
                "file_status": "available",
            },
            {
                "id": 7,
                "title": "rejected-only.mp3",
                "artist": None,
                "album": None,
                "duration_ms": None,
                "file_path": "Artist/rejected-only.mp3",
                "library_root_rel_path": "Artist/rejected-only.mp3",
                "link_status": "unlinked",
                "match_method": None,
                "file_status": "available",
            },
            {
                "id": 8,
                "title": "no-match.flac",
                "artist": None,
                "album": None,
                "duration_ms": None,
                "file_path": "Loose/no-match.flac",
                "library_root_rel_path": "Loose/no-match.flac",
                "link_status": "unlinked",
                "match_method": None,
                "file_status": "available",
            },
        ]
    }


def test_playlist_m3u_export_endpoint_returns_attachment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'playlist-export.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIBRARY_ROOT", str(tmp_path / "library"))

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
                synced_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
            )
        )
        connection.execute(
            insert(local_tracks_table).values(
                id=5,
                file_path="Artist/song.mp3",
                library_root_rel_path="Artist/song.mp3",
                fingerprint="fp-5",
                beets_id=5,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Song",
                artist="Artist",
                album=None,
                year=None,
                isrc=None,
                duration_ms=181000,
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=9,
                position=1,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=5,
                streaming_track_id=9,
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/playlists/{playlist_id}/m3u"
        and "GET" in getattr(route, "methods", set())
    )

    response = asyncio.run(route.endpoint(7))

    assert response.media_type == "audio/x-mpegurl"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Road-Trip-Mix.m3u"'
    )
    assert response.body.decode("utf-8").splitlines() == [
        "#EXTM3U",
        "#EXTINF:181,Artist - Song",
        str((tmp_path / "library" / "Artist/song.mp3").resolve()),
    ]


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
        if getattr(route, "path", None) == "/api/streaming/accounts/{account_id}/sync"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(1))

    assert response.account_id == 1
    assert response.job_id == "sync-job-999"
    assert seen == {
        "redis_url": "redis://redis:6379/3",
        "account_id": 1,
    }


def test_streaming_refresh_metadata_endpoint_enqueues_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-refresh.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/3")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Refreshable Account",
                auth_token_blob="encrypted-token",
                auth_state="connected",
            )
        )

    seen: dict[str, object] = {}

    class FakeSyncEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue_metadata_refresh(
            self,
            *,
            account_id: int,
        ) -> str:
            seen["account_id"] = account_id
            return "metadata-refresh-job-999"

    monkeypatch.setattr(
        "app.streaming.router.StreamingSyncJobEnqueuer", FakeSyncEnqueuer
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/streaming/accounts/{account_id}/refresh-metadata"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(1))

    assert response.account_id == 1
    assert response.job_id == "metadata-refresh-job-999"
    assert seen == {
        "redis_url": "redis://redis:6379/3",
        "account_id": 1,
    }


def test_streaming_playlist_sync_endpoint_enqueues_job(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlist-sync.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/3")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlist = store.upsert_playlists(
        account_id=account.id,
        playlists=[YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")],
    )[0]

    seen: dict[str, object] = {}

    class FakeSyncEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue_playlist_sync(
            self,
            *,
            playlist_id: int,
        ) -> str:
            seen["playlist_id"] = playlist_id
            return "playlist-sync-job-999"

    monkeypatch.setattr(
        "app.streaming.router.StreamingSyncJobEnqueuer", FakeSyncEnqueuer
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists/{playlist_id}/sync"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(playlist.id))

    assert response.playlist_id == playlist.id
    assert response.job_id == "playlist-sync-job-999"
    assert seen == {
        "redis_url": "redis://redis:6379/3",
        "playlist_id": playlist.id,
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
        if getattr(route, "path", None) == "/api/matching/status"
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
        if getattr(route, "path", None) == "/api/matching/tracks/{local_track_id}/run"
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
        if getattr(route, "path", None) == "/api/matching/tracks/{local_track_id}/run"
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
        if getattr(route, "path", None) == "/api/local-tracks/{local_track_id}/rematch"
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
        if getattr(route, "path", None) == "/api/local-tracks/{local_track_id}/rematch"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(route.endpoint(999))
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Local track not found"
    else:
        raise AssertionError("Expected HTTPException for missing local track")


def test_local_track_rescue_endpoint_returns_updated_track_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-track-rescue.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIBRARY_ROOT", str(tmp_path / "library"))

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=21,
                file_path="Artist/rescue.mp3",
                library_root_rel_path="Artist/rescue.mp3",
                fingerprint="fp-21",
                beets_id=21,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=21,
                streaming_track_id=121,
            )
        )

    seen: dict[str, object] = {}

    def fake_rescue_metadata(
        local_track_id: int,
        *,
        database_url: str | None = None,
        library_root: Path | str | None = None,
    ) -> None:
        seen["local_track_id"] = local_track_id
        seen["database_url"] = database_url
        seen["library_root"] = str(library_root) if library_root is not None else None

    monkeypatch.setattr("app.rescue.router.rescue_metadata", fake_rescue_metadata)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/local-tracks/{local_track_id}/rescue"
        and "POST" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint(21))

    assert response == {
        "id": 21,
        "file_path": "Artist/rescue.mp3",
        "library_root_rel_path": "Artist/rescue.mp3",
        "fingerprint": "fp-21",
        "beets_id": 21,
    }
    assert seen == {
        "local_track_id": 21,
        "database_url": database_url,
        "library_root": str(tmp_path / "library"),
    }


def test_local_track_rescue_endpoint_returns_409_without_final_link(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-track-rescue-no-link.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=22,
                file_path="Artist/unlinked.mp3",
                library_root_rel_path="Artist/unlinked.mp3",
                fingerprint="fp-22",
                beets_id=22,
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/local-tracks/{local_track_id}/rescue"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(route.endpoint(22))
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "No final link exists for local track 22"
    else:
        raise AssertionError("Expected HTTPException when final link is missing")
