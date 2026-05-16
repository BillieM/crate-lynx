from __future__ import annotations

import asyncio
import inspect
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from app.ingestion.failures import (
    failed_ingestion_attempts_table,
    metadata as failed_ingestion_attempts_metadata,
)
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
from app.settings.models import metadata as settings_metadata
from app.settings.schemas import CreateIngestFolderRequest
from app.settings.store import GeneralSettingsStore
from app.streaming.crypto import TokenEncryptionKeyError
from app.streaming.schemas import (
    CreateStreamingAccountRequest,
    UpdateStreamingAccountAuthRequest,
    UpdateStreamingPlaylistRequest,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_OFF,
    metadata,
    streaming_accounts_table,
)
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
from sqlalchemy import create_engine, event, insert, select
from starlette.exceptions import HTTPException as StarletteHTTPException


class StubIngestionWatcher:
    instances: list["StubIngestionWatcher"] = []

    def __init__(self, root, on_new_file, recursive=False) -> None:
        self.root = root
        self.on_new_file = on_new_file
        self.recursive = recursive
        self.added_roots: list[str] = []
        self.removed_roots: list[str] = []
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def add_root(self, path: str) -> None:
        self.added_roots.append(path)

    def remove_root(self, path: str) -> None:
        self.removed_roots.append(path)


def test_links_routes_are_mounted_under_api_prefix() -> None:
    app = create_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/proposals" in route_paths
    assert "/api/proposals/{proposal_id}/approve" in route_paths
    assert "/api/proposals/{proposal_id}/reject" in route_paths
    assert "/api/final-links/{final_link_id}" in route_paths
    assert "/api/local-tracks/{local_track_id}/rescue" in route_paths
    assert "/local-tracks/{local_track_id}/rescue" not in route_paths
    assert "/api/playlists/{playlist_id}" in route_paths
    assert "/api/playlists/{playlist_id}/tracks" in route_paths
    assert "/api/playlists/{playlist_id}/m3u" in route_paths
    assert "/api/library/tracks" in route_paths
    assert "/api/local-tracks/{local_track_id}" in route_paths
    assert "/api/maintenance/missing-locally" in route_paths
    assert "/api/maintenance/unidentified" in route_paths
    assert "/api/streaming/accounts/{account_id}/auth" in route_paths
    assert "/api/streaming/accounts/{account_id}/sync" in route_paths
    assert "/api/streaming/accounts/{account_id}/refresh-metadata" in route_paths
    assert "/api/streaming/playlists/config" in route_paths
    assert "/api/streaming/playlists/{playlist_id}" in route_paths
    assert "/api/streaming/playlists/{playlist_id}/sync" in route_paths
    assert "/api/local-tracks/{local_track_id}/rematch" in route_paths
    assert "/api/settings/general" in route_paths
    assert "/api/settings/ingest-folders" in route_paths
    assert "/api/settings/ingest-folders/{folder_id}" in route_paths
    assert "/healthz" in route_paths
    assert "/ingest/status" not in route_paths


def test_healthz_pings_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'health.db'}"
    engine = create_engine(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    app = create_app()
    app.state.database_engine = engine
    route = _route("GET", "/healthz", app)

    response = _call_endpoint(route.endpoint)

    assert response.ok is True
    assert response.database == "ok"


def test_healthz_allows_unconfigured_database(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()
    route = _route("GET", "/healthz", app)

    response = _call_endpoint(route.endpoint)

    assert response.ok is True
    assert response.database == "not_configured"


def test_startup_seeds_persisted_ingest_folders_and_watches_them(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    settings_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr("app.main.IngestionWatcher", StubIngestionWatcher)
    StubIngestionWatcher.instances = []
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            watcher = StubIngestionWatcher.instances[-1]
            assert watcher.started is True
            assert watcher.root == [
                Path("/nas/cratelynx/music-in"),
                Path("/nas/soulseek/downloads"),
            ]
            assert watcher.recursive is True

    asyncio.run(run_lifespan())

    watcher = StubIngestionWatcher.instances[-1]
    assert watcher.stopped is True
    assert [
        folder.path
        for folder in GeneralSettingsStore(database_url).list_ingest_folders()
    ] == ["/nas/cratelynx/music-in", "/nas/soulseek/downloads"]


def test_startup_falls_back_to_env_ingestion_root_without_database_url(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("INGESTION_ROOT", "/tmp/local-ingestion")
    monkeypatch.setattr("app.main.IngestionWatcher", StubIngestionWatcher)
    StubIngestionWatcher.instances = []
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            watcher = StubIngestionWatcher.instances[-1]
            assert watcher.root == [Path("/tmp/local-ingestion")]

    asyncio.run(run_lifespan())


def test_startup_uses_configured_staging_base(
    monkeypatch,
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    class StubIngestionProcessor:
        def __init__(self, **kwargs) -> None:
            seen["processor_kwargs"] = kwargs

        def process(self, path: Path):
            raise AssertionError(f"unexpected process call for {path}")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("CRATE_LYNX_STAGING_DIR", str(tmp_path / "stage"))
    monkeypatch.setenv("INGESTION_ROOT", str(tmp_path / "incoming"))
    monkeypatch.setattr("app.main.IngestionProcessor", StubIngestionProcessor)
    monkeypatch.setattr("app.main.IngestionWatcher", StubIngestionWatcher)
    StubIngestionWatcher.instances = []
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run_lifespan())

    assert seen["processor_kwargs"]["staging_root"] == (
        tmp_path / "stage" / "ingestion-staging"
    )


def test_startup_allows_missing_token_encryption_key_without_database_url(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("INGESTION_ROOT", "/tmp/local-ingestion")
    monkeypatch.setattr("app.main.IngestionWatcher", StubIngestionWatcher)
    StubIngestionWatcher.instances = []
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            watcher = StubIngestionWatcher.instances[-1]
            assert watcher.started is True

    asyncio.run(run_lifespan())


def test_startup_requires_token_encryption_key_with_database_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    settings_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            raise AssertionError("startup should fail before yielding")

    with pytest.raises(
        TokenEncryptionKeyError,
        match="TOKEN_ENCRYPTION_KEY is required",
    ):
        asyncio.run(run_lifespan())


def test_startup_rejects_malformed_token_encryption_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    settings_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            raise AssertionError("startup should fail before yielding")

    with pytest.raises(TokenEncryptionKeyError, match="valid Fernet key"):
        asyncio.run(run_lifespan())


def test_startup_defaults_beets_imports_to_music_and_data(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    settings_metadata.create_all(engine)
    seen: dict[str, object] = {}

    class StubBeetsImporter:
        def __init__(self, beet_binary, library_root, library_database) -> None:
            self.beet_binary = beet_binary
            self.library_root = library_root
            self.library_database = library_database
            seen["beets_importer"] = self

    class StubIngestionProcessor:
        def __init__(self, **kwargs) -> None:
            seen["processor_kwargs"] = kwargs

        def process(self, path: Path):
            raise AssertionError(f"unexpected process call for {path}")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.delenv("LIBRARY_ROOT", raising=False)
    monkeypatch.delenv("BEETS_LIBRARY", raising=False)
    monkeypatch.setattr("app.main.BeetsImporter", StubBeetsImporter)
    monkeypatch.setattr("app.main.IngestionProcessor", StubIngestionProcessor)
    monkeypatch.setattr("app.main.IngestionWatcher", StubIngestionWatcher)
    StubIngestionWatcher.instances = []
    app = create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(run_lifespan())

    beets_importer = seen["beets_importer"]
    assert beets_importer.library_root == Path("/nas/media/music")
    assert beets_importer.library_database == "/data/beets/library.db"
    assert seen["processor_kwargs"]["beets_importer"] is beets_importer


def test_settings_ingest_folder_mutations_synchronize_active_watcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    settings_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setattr("app.main.IngestionWatcher", StubIngestionWatcher)
    StubIngestionWatcher.instances = []
    app = create_app()
    create_route = _route("POST", "/api/settings/ingest-folders", app)
    delete_route = _route("DELETE", "/api/settings/ingest-folders/{folder_id}", app)

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            watcher = StubIngestionWatcher.instances[-1]
            created = _call_endpoint(
                create_route.endpoint, CreateIngestFolderRequest(path="/incoming")
            )
            response = _call_endpoint(delete_route.endpoint, created.id)

            assert response.status_code == 204
            assert watcher.added_roots == ["/incoming"]
            assert watcher.removed_roots == ["/incoming"]

    asyncio.run(run_lifespan())


def _route(method: str, path: str, app):
    return next(
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def _call_endpoint(endpoint, *args):
    signature = inspect.signature(endpoint)
    bound = signature.bind_partial(*args)
    if "engine" in signature.parameters and "engine" not in bound.arguments:
        database_url = os.environ.get("DATABASE_URL")
        if database_url is not None:
            bound.arguments["engine"] = create_engine(database_url)

    result = endpoint(*bound.args, **bound.kwargs)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def test_streaming_accounts_endpoint_lists_persisted_accounts(
    monkeypatch,
    migrated_database,
    test_data,
) -> None:
    database_url, _ = migrated_database
    monkeypatch.setenv("DATABASE_URL", database_url)
    test_data.streaming_account(
        provider="youtube_music",
        display_name="Main Account",
        auth_token_blob="encrypted-token",
        auth_state="connected",
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/accounts"
        and "GET" in getattr(route, "methods", set())
    )
    response = _call_endpoint(route.endpoint)

    assert len(response.accounts) == 1
    account = response.accounts[0]
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

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlists = store.upsert_playlists(
        account_id=account.id,
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
    store.set_playlist_sync_mode(
        playlist_id=playlists[0].id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists"
        and "GET" in getattr(route, "methods", set())
    )
    response = _call_endpoint(route.endpoint)

    assert len(response.playlists) == 1
    playlist = response.playlists[0]
    assert playlist.account_id == account.id
    assert playlist.provider_playlist_id == "PL1"
    assert playlist.title == "Morning Mix"
    assert playlist.model_dump(mode="json") == {
        "id": playlists[0].id,
        "account_id": account.id,
        "provider_playlist_id": "PL1",
        "title": "Morning Mix",
        "sync_mode": PLAYLIST_SYNC_MODE_FULL,
        "provider_track_count": None,
        "imported_track_count": 2,
        "metadata_synced_at": "2026-05-01T09:00:00",
        "tracks_synced_at": None,
        "last_sync_error": None,
        "last_sync_error_at": None,
    }


def test_streaming_playlists_config_endpoint_lists_all_discovered_playlists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlists-config.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlists = store.upsert_playlists(
        account_id=account.id,
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
    store.set_playlist_sync_mode(
        playlist_id=playlists[0].id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists/config"
        and "GET" in getattr(route, "methods", set())
    )
    response = _call_endpoint(route.endpoint)

    assert [playlist.provider_playlist_id for playlist in response.playlists] == [
        "PL1",
        "PL2",
    ]
    selected, unselected = response.playlists
    assert selected.model_dump(mode="json") == {
        "id": playlists[0].id,
        "account_id": account.id,
        "provider_playlist_id": "PL1",
        "title": "Morning Mix",
        "sync_mode": PLAYLIST_SYNC_MODE_FULL,
        "provider_track_count": None,
        "imported_track_count": 1,
        "metadata_synced_at": "2026-05-01T09:00:00",
        "tracks_synced_at": None,
        "last_sync_error": None,
        "last_sync_error_at": None,
    }
    assert unselected.model_dump(mode="json") == {
        "id": playlists[1].id,
        "account_id": account.id,
        "provider_playlist_id": "PL2",
        "title": "Empty Playlist",
        "sync_mode": PLAYLIST_SYNC_MODE_OFF,
        "provider_track_count": None,
        "imported_track_count": 0,
        "metadata_synced_at": "2026-05-01T09:00:00",
        "tracks_synced_at": None,
        "last_sync_error": None,
        "last_sync_error_at": None,
    }


def test_streaming_playlist_patch_endpoint_updates_sync_mode(
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
    store.set_playlist_sync_mode(
        playlist_id=playlist.id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/playlists/{playlist_id}"
        and "PATCH" in getattr(route, "methods", set())
    )
    response = _call_endpoint(
        route.endpoint,
        playlist.id,
        UpdateStreamingPlaylistRequest(sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY),
    )

    assert response.id == playlist.id
    assert response.sync_mode == PLAYLIST_SYNC_MODE_MATCH_ONLY
    assert response.imported_track_count == 1
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
        _call_endpoint(
            route.endpoint,
            999,
            UpdateStreamingPlaylistRequest(sync_mode=PLAYLIST_SYNC_MODE_FULL),
        )
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Playlist not found"
    else:
        raise AssertionError("Expected playlist update to return 404")


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
            "Authorization": "SAPISIDHASH token",
            "Cookie": "__Secure-3PAPISID=cookie-value; SID=session",
            "Origin": "https://music.youtube.com",
            "X-Goog-AuthUser": "0",
        },
    )

    response = _call_endpoint(route.endpoint, payload)

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
        "Authorization": "SAPISIDHASH token",
        "Cookie": "__Secure-3PAPISID=cookie-value; SID=session",
        "Origin": "https://music.youtube.com",
        "X-Goog-AuthUser": "0",
    }


def test_streaming_accounts_endpoint_rejects_incomplete_youtube_music_auth(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-create-invalid-auth.db'}"
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
            "Authorization": "SAPISIDHASH token",
            "X-Goog-AuthUser": "0",
            "X-Origin": "https://music.youtube.com",
        },
    )

    try:
        _call_endpoint(route.endpoint, payload)
    except StarletteHTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "YouTube Music browser auth is missing the cookie header."
    else:
        raise AssertionError("Expected streaming account create to reject invalid auth")

    with engine.connect() as connection:
        assert list(connection.execute(select(streaming_accounts_table))) == []


def test_streaming_accounts_auth_endpoint_updates_youtube_music_account(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-auth-patch.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Billie",
        browser_headers={"Authorization": "Bearer old-token"},
    )
    store.mark_account_auth_error(
        account_id=account.id,
        error=ValueError("expired browser headers"),
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/accounts/{account_id}/auth"
        and "PATCH" in getattr(route, "methods", set())
    )
    payload = UpdateStreamingAccountAuthRequest(
        browser_headers={
            "Authorization": "SAPISIDHASH sentinel-secret-token",
            "Cookie": "__Secure-3PAPISID=fresh-cookie; SID=fresh-session",
            "Origin": "https://music.youtube.com",
            "X-Goog-AuthUser": "0",
        },
    )

    response = _call_endpoint(route.endpoint, account.id, payload)

    assert response.id == account.id
    assert response.provider == "youtube_music"
    assert response.display_name == "Billie"
    assert response.auth_state == "connected"
    assert response.auth_error is None
    assert response.auth_error_at is None
    assert response.created_at
    assert response.updated_at

    response_payload = response.model_dump(mode="json")
    assert "auth_token_blob" not in response_payload
    assert "browser_headers" not in response_payload
    assert "sentinel-secret-token" not in str(response_payload)
    assert store.get_account(account.id).browser_headers == {
        "Authorization": "SAPISIDHASH sentinel-secret-token",
        "Cookie": "__Secure-3PAPISID=fresh-cookie; SID=fresh-session",
        "Origin": "https://music.youtube.com",
        "X-Goog-AuthUser": "0",
    }


def test_streaming_accounts_auth_endpoint_rejects_invalid_auth_without_overwriting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-auth-patch-invalid.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    original_headers = {
        "Authorization": "SAPISIDHASH old-token",
        "Cookie": "__Secure-3PAPISID=old-cookie; SID=old-session",
        "X-Goog-AuthUser": "0",
        "X-Origin": "https://music.youtube.com",
    }
    account = store.create_youtube_music_account(
        display_name="Billie",
        browser_headers=original_headers,
    )
    store.mark_account_auth_error(
        account_id=account.id,
        error=ValueError("expired browser headers"),
    )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/accounts/{account_id}/auth"
        and "PATCH" in getattr(route, "methods", set())
    )
    payload = UpdateStreamingAccountAuthRequest(
        browser_headers={
            "Authorization": "SAPISIDHASH token-without-cookie",
            "X-Goog-AuthUser": "0",
            "X-Origin": "https://music.youtube.com",
        },
    )

    try:
        _call_endpoint(route.endpoint, account.id, payload)
    except StarletteHTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail == "YouTube Music browser auth is missing the cookie header."
    else:
        raise AssertionError(
            "Expected streaming account auth refresh to reject invalid auth"
        )

    persisted = store.list_accounts()[0]
    assert persisted.auth_state == "error"
    assert (
        persisted.auth_error
        == "YouTube Music authentication failed: expired browser headers"
    )
    assert store.get_account(account.id).browser_headers == original_headers


def test_streaming_accounts_auth_endpoint_missing_account_returns_404(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-auth-patch-missing.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/streaming/accounts/{account_id}/auth"
        and "PATCH" in getattr(route, "methods", set())
    )
    payload = UpdateStreamingAccountAuthRequest(
        browser_headers={"Authorization": "Bearer token"},
    )

    try:
        _call_endpoint(route.endpoint, 404, payload)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Streaming account not found"
    else:
        raise AssertionError("Expected streaming account auth refresh to return 404")


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
                metadata_synced_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
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

    response = _call_endpoint(route.endpoint, 7)

    assert response.playlist.id == 7
    assert response.playlist.name == "Road Trip Mix"
    assert response.playlist.cover_art_url is None
    assert response.playlist.sync_mode == PLAYLIST_SYNC_MODE_OFF
    assert response.playlist.provider_track_count is None
    assert response.playlist.imported_track_count == 3
    assert response.playlist.linked_count == 1
    assert response.playlist.pending_count == 1
    assert response.playlist.unlinked_count == 1
    assert response.playlist.metadata_synced_at == "2026-05-01T09:00:00"
    assert response.playlist.tracks_synced_at is None


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

    playlist_membership_statement_count = 0

    def count_playlist_membership_statement(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        nonlocal playlist_membership_statement_count
        if "playlist_membership" in statement:
            playlist_membership_statement_count += 1

    event.listen(engine, "before_cursor_execute", count_playlist_membership_statement)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/playlists/{playlist_id}/tracks"
        and "GET" in getattr(route, "methods", set())
    )

    try:
        response = _call_endpoint(route.endpoint, 7, engine)
    finally:
        event.remove(
            engine, "before_cursor_execute", count_playlist_membership_statement
        )

    assert [track.title for track in response.tracks] == [
        "Linked Song",
        "Pending Song",
        "Unlinked Song",
    ]
    assert playlist_membership_statement_count == 1
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

    response = _call_endpoint(route.endpoint)

    assert [track.id for track in response.tracks] == [5, 6, 7, 8]
    assert response.stats.model_dump(mode="json") == {
        "total": len(response.tracks),
        "linked": sum(1 for track in response.tracks if track.link_status == "linked"),
        "pending": sum(
            1 for track in response.tracks if track.link_status == "pending"
        ),
        "unlinked": sum(
            1 for track in response.tracks if track.link_status == "unlinked"
        ),
    }
    assert response.model_dump(mode="json") == {
        "stats": {
            "total": 4,
            "linked": 1,
            "pending": 1,
            "unlinked": 2,
        },
        "tracks": [
            {
                "id": 5,
                "final_link_id": 3,
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
                "final_link_id": None,
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
                "final_link_id": None,
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
                "final_link_id": None,
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
        ],
        "next_cursor": None,
    }


def test_library_tracks_endpoint_returns_empty_page(
    monkeypatch, tmp_path: Path
) -> None:
    database_url = f"sqlite:///{tmp_path / 'library-empty.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/library/tracks"
        and "GET" in getattr(route, "methods", set())
    )

    response = _call_endpoint(route.endpoint)

    assert response.model_dump(mode="json") == {
        "stats": {
            "total": 0,
            "linked": 0,
            "pending": 0,
            "unlinked": 0,
        },
        "tracks": [],
        "next_cursor": None,
    }


def test_library_tracks_endpoint_paginates_by_local_track_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'library-pages.db'}"
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
                    "file_path": "Artist/first.mp3",
                    "library_root_rel_path": "Artist/first.mp3",
                },
                {
                    "id": 6,
                    "file_path": "Artist/second.mp3",
                    "library_root_rel_path": "Artist/second.mp3",
                },
                {
                    "id": 7,
                    "file_path": "Artist/third.mp3",
                    "library_root_rel_path": "Artist/third.mp3",
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

    first_page = _call_endpoint(route.endpoint, None, 2)
    second_page = _call_endpoint(route.endpoint, first_page.next_cursor, 2)
    end_page = _call_endpoint(route.endpoint, 7, 2)

    assert [track.id for track in first_page.tracks] == [5, 6]
    assert first_page.next_cursor == 6
    assert first_page.stats.total == 3
    assert [track.id for track in second_page.tracks] == [7]
    assert second_page.next_cursor is None
    assert second_page.stats.total == 3
    assert end_page.tracks == []
    assert end_page.next_cursor is None
    assert end_page.stats.total == 3


def test_missing_locally_endpoint_aggregates_playlist_usage_and_excludes_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing-locally.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_playlists_table),
            [
                {
                    "id": 1,
                    "account_id": 1,
                    "provider_playlist_id": "PL1",
                    "title": "Morning Mix",
                    "sync_mode": PLAYLIST_SYNC_MODE_FULL,
                },
                {
                    "id": 2,
                    "account_id": 1,
                    "provider_playlist_id": "PL2",
                    "title": "Road Trip",
                    "sync_mode": PLAYLIST_SYNC_MODE_OFF,
                },
            ],
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 10,
                    "provider_track_id": "ytm-10",
                    "title": "Single Playlist Song",
                    "artist": "Artist A",
                    "album": "Album A",
                    "duration_ms": 181000,
                },
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "Multi Playlist Song",
                    "artist": "Artist B",
                    "album": None,
                    "duration_ms": None,
                },
                {
                    "id": 12,
                    "provider_track_id": "ytm-12",
                    "title": "Deselected Playlist Song",
                    "artist": "Artist C",
                    "album": "Album C",
                    "duration_ms": 200000,
                },
                {
                    "id": 13,
                    "provider_track_id": "ytm-13",
                    "title": "Linked Song",
                    "artist": "Artist D",
                    "album": "Album D",
                    "duration_ms": 220000,
                },
            ],
        )
        connection.execute(
            insert(playlist_membership_table),
            [
                {"playlist_id": 1, "streaming_track_id": 10, "position": 1},
                {"playlist_id": 1, "streaming_track_id": 11, "position": 2},
                {"playlist_id": 2, "streaming_track_id": 11, "position": 1},
                {"playlist_id": 2, "streaming_track_id": 12, "position": 2},
                {"playlist_id": 1, "streaming_track_id": 13, "position": 3},
            ],
        )
        connection.execute(
            insert(local_tracks_table).values(
                id=5,
                file_path="Artist/linked.mp3",
                library_root_rel_path="Artist/linked.mp3",
                fingerprint="fp-linked",
                beets_id=5,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                id=3,
                local_track_id=5,
                streaming_track_id=13,
            )
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/maintenance/missing-locally"
        and "GET" in getattr(route, "methods", set())
    )

    response = _call_endpoint(route.endpoint)

    assert response.model_dump(mode="json") == {
        "tracks": [
            {
                "id": 10,
                "provider_track_id": "ytm-10",
                "title": "Single Playlist Song",
                "artist": "Artist A",
                "album": "Album A",
                "duration_ms": 181000,
                "playlist_count": 1,
                "playlist_ids": [1],
                "playlist_titles": ["Morning Mix"],
            },
            {
                "id": 11,
                "provider_track_id": "ytm-11",
                "title": "Multi Playlist Song",
                "artist": "Artist B",
                "album": None,
                "duration_ms": None,
                "playlist_count": 1,
                "playlist_ids": [1],
                "playlist_titles": ["Morning Mix"],
            },
        ]
    }


def test_unidentified_endpoint_lists_durable_failed_ingestion_attempts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'unidentified.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    failed_ingestion_attempts_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=91,
                file_path="Imported/rescue.mp3",
                library_root_rel_path="Imported/rescue.mp3",
                fingerprint="fp-linked",
                beets_id=91,
            )
        )
        connection.execute(
            insert(failed_ingestion_attempts_table),
            [
                {
                    "id": 1,
                    "source_path": "/ingestion/old.flac",
                    "filename": "old.flac",
                    "fingerprint": None,
                    "failure_reason": "Unsupported audio format",
                    "failed_at": datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
                    "local_track_id": None,
                },
                {
                    "id": 2,
                    "source_path": "/ingestion/unknown-import-9a4f.mp3",
                    "filename": "unknown-import-9a4f.mp3",
                    "fingerprint": "fp_7d91c2a8e4b0",
                    "failure_reason": "Beets could not identify metadata",
                    "failed_at": datetime(2026, 5, 2, 21, 44, tzinfo=UTC),
                    "local_track_id": 91,
                },
                {
                    "id": 3,
                    "source_path": "/ingestion/.DS_Store",
                    "filename": ".DS_Store",
                    "fingerprint": None,
                    "failure_reason": "Unsupported audio format",
                    "failed_at": datetime(2026, 5, 3, 8, 12, tzinfo=UTC),
                    "local_track_id": None,
                },
                {
                    "id": 4,
                    "source_path": "/soulseek/2f940acf775f48998bf67a0866d66d56",
                    "filename": "2f940acf775f48998bf67a0866d66d56",
                    "fingerprint": None,
                    "failure_reason": "Unsupported audio format",
                    "failed_at": datetime(2026, 5, 3, 9, 15, tzinfo=UTC),
                    "local_track_id": None,
                },
            ],
        )

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/maintenance/unidentified"
        and "GET" in getattr(route, "methods", set())
    )

    response = _call_endpoint(route.endpoint)

    assert response.model_dump(mode="json") == {
        "tracks": [
            {
                "id": 2,
                "failed_at": "2026-05-02T21:44:00",
                "failure_reason": "Beets could not identify metadata",
                "filename": "unknown-import-9a4f.mp3",
                "local_track_id": 91,
                "source_path": "/ingestion/unknown-import-9a4f.mp3",
            },
            {
                "id": 1,
                "failed_at": "2026-05-01T10:00:00",
                "failure_reason": "Unsupported audio format",
                "filename": "old.flac",
                "local_track_id": None,
                "source_path": "/ingestion/old.flac",
            },
        ]
    }


def test_playlist_m3u_export_endpoint_returns_attachment(
    library_root: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'playlist-export.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
                metadata_synced_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
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

    response = _call_endpoint(route.endpoint, 7)

    assert response.media_type == "audio/x-mpegurl"
    assert response.headers["content-disposition"] == (
        'attachment; filename="Road-Trip-Mix.m3u"'
    )
    assert response.body.decode("utf-8").splitlines() == [
        "#EXTM3U",
        "#EXTINF:181,Artist - Song",
        str((library_root / "Artist/song.mp3").resolve()),
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
    response = _call_endpoint(route.endpoint, 1)

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
    response = _call_endpoint(route.endpoint, 1)

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
    response = _call_endpoint(route.endpoint, playlist.id)

    assert response.playlist_id == playlist.id
    assert response.job_id == "playlist-sync-job-999"
    assert seen == {
        "redis_url": "redis://redis:6379/3",
        "playlist_id": playlist.id,
    }


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
    response = _call_endpoint(route.endpoint, 15)

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
        _call_endpoint(route.endpoint, 999)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Local track not found"
    else:
        raise AssertionError("Expected HTTPException for missing local track")


def test_local_track_detail_endpoint_returns_combined_track_context(
    monkeypatch,
    migrated_database,
    test_data,
) -> None:
    database_url, engine = migrated_database
    monkeypatch.setenv("DATABASE_URL", database_url)

    local_track_id = test_data.local_track(
        file_path="OnlyL/Memories.mp3",
        library_root_rel_path="OnlyL/Memories.mp3",
    )
    streaming_track_id = test_data.streaming_track(
        artist="OnlyL",
        title="Memories",
        provider_track_id="ytm-onlyl",
    )
    final_link_id = test_data.final_link(
        approved_at=datetime(2026, 5, 2, 8, 30, tzinfo=UTC),
        local_track_id=local_track_id,
        streaming_track_id=streaming_track_id,
    )
    low_score_suggestion_id = test_data.suggested_link(
        local_track_id=local_track_id,
        match_method="tags",
        score=0.61,
        streaming_track_id=test_data.streaming_track(provider_track_id="ytm-low"),
    )
    high_score_suggestion_id = test_data.suggested_link(
        local_track_id=local_track_id,
        match_method="isrc",
        score=0.98,
        streaming_track_id=test_data.streaming_track(provider_track_id="ytm-high"),
    )
    with engine.begin() as connection:
        connection.execute(
            insert(failed_ingestion_attempts_table).values(
                source_path="/imports/OnlyL/Memories.flac",
                filename="Memories.flac",
                fingerprint="fp-detail",
                failure_reason="beets import failed",
                failed_at=datetime(2026, 5, 3, 9, 15, tzinfo=UTC),
                local_track_id=local_track_id,
            )
        )

    app = create_app()
    route = _route("GET", "/api/local-tracks/{local_track_id}", app)
    response = _call_endpoint(route.endpoint, local_track_id)

    assert response.id == local_track_id
    assert response.file_path == "OnlyL/Memories.mp3"
    assert response.library_root_rel_path == "OnlyL/Memories.mp3"
    assert response.link_status == "linked"
    assert response.final_link is not None
    assert response.final_link.id == final_link_id
    assert response.final_link.streaming_track_id == streaming_track_id
    assert response.final_link.approved_at == datetime(2026, 5, 2, 8, 30)
    assert [suggestion.id for suggestion in response.pending_suggestions] == [
        high_score_suggestion_id,
        low_score_suggestion_id,
    ]
    assert response.pending_suggestions[0].match_method == "isrc"
    assert response.pending_suggestions[0].score == 0.98
    assert len(response.failed_ingestion_attempts) == 1
    assert response.failed_ingestion_attempts[0].source_path == (
        "/imports/OnlyL/Memories.flac"
    )
    assert response.failed_ingestion_attempts[0].failure_reason == (
        "beets import failed"
    )


def test_local_track_detail_endpoint_returns_404_for_unknown_track(
    monkeypatch,
    migrated_database,
) -> None:
    database_url, _ = migrated_database
    monkeypatch.setenv("DATABASE_URL", database_url)

    app = create_app()
    route = _route("GET", "/api/local-tracks/{local_track_id}", app)

    try:
        _call_endpoint(route.endpoint, 404)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Local track not found"
    else:
        raise AssertionError("Expected HTTPException for missing local track")


def test_local_track_rescue_endpoint_returns_updated_track_record(
    library_root: Path,
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-track-rescue.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

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
        engine=None,
        library_root: Path | str | None = None,
    ) -> None:
        seen["local_track_id"] = local_track_id
        seen["database_url"] = database_url
        seen["engine"] = engine
        seen["library_root"] = str(library_root) if library_root is not None else None

    monkeypatch.setattr("app.rescue.router.rescue_metadata", fake_rescue_metadata)

    app = create_app()
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/local-tracks/{local_track_id}/rescue"
        and "POST" in getattr(route, "methods", set())
    )
    response = _call_endpoint(route.endpoint, 21)

    assert response == {
        "id": 21,
        "file_path": "Artist/rescue.mp3",
        "library_root_rel_path": "Artist/rescue.mp3",
        "beets_id": 21,
    }
    assert seen["engine"] is not None
    assert seen == {
        "local_track_id": 21,
        "database_url": None,
        "engine": seen["engine"],
        "library_root": str(library_root),
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
        if getattr(route, "path", None) == "/api/local-tracks/{local_track_id}/rescue"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        _call_endpoint(route.endpoint, 22)
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "No final link exists for local track 22"
    else:
        raise AssertionError("Expected HTTPException when final link is missing")
