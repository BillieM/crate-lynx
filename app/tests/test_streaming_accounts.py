from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from ytmusicapi.exceptions import YTMusicUserError

from app.streaming_accounts import (
    playlist_membership_table,
    run_youtube_music_sync_job,
    YOUTUBE_MUSIC_PROVIDER,
    StreamingAccountStore,
    metadata,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.adapters.youtube_music import (
    YouTubeMusicPlaylist,
    YouTubeMusicTrack,
)


def test_streaming_account_store_encrypts_and_persists_browser_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    browser_headers = {
        "Authorization": "Bearer token-123",
        "X-Goog-AuthUser": "0",
        "Cookie": "VISITOR_INFO1_LIVE=value",
    }

    account = StreamingAccountStore(database_url).create_youtube_music_account(
        display_name="Billie",
        browser_headers=browser_headers,
    )

    assert account == account.__class__(
        id=1,
        provider=YOUTUBE_MUSIC_PROVIDER,
        display_name="Billie",
    )

    with engine.connect() as connection:
        stored_account = (
            connection.execute(select(streaming_accounts_table)).mappings().one()
        )

    assert stored_account["provider"] == YOUTUBE_MUSIC_PROVIDER
    assert stored_account["display_name"] == "Billie"
    assert stored_account["auth_state"] == "connected"
    assert stored_account["auth_error"] is None
    assert stored_account["auth_error_at"] is None
    assert stored_account["auth_token_blob"] != json.dumps(
        browser_headers, sort_keys=True
    )
    assert (
        json.loads(_decrypt_token(stored_account["auth_token_blob"])) == browser_headers
    )


def test_streaming_account_store_get_account_returns_browser_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-store.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    browser_headers = {
        "Authorization": "Bearer token-456",
        "X-Goog-AuthUser": "1",
    }
    account = StreamingAccountStore(database_url).create_youtube_music_account(
        display_name="Listener",
        browser_headers=browser_headers,
    )

    assert account == account.__class__(
        id=1,
        provider=YOUTUBE_MUSIC_PROVIDER,
        display_name="Listener",
    )

    with engine.connect() as connection:
        stored_account = (
            connection.execute(select(streaming_accounts_table)).mappings().one()
        )

    assert stored_account["auth_state"] == "connected"
    assert stored_account["auth_error"] is None
    assert stored_account["auth_error_at"] is None
    assert (
        json.loads(_decrypt_token(stored_account["auth_token_blob"])) == browser_headers
    )
    assert (
        StreamingAccountStore(database_url).get_account(account.id).browser_headers
        == browser_headers
    )


def test_streaming_account_store_upserts_playlists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlists.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )

    inserted = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(
                provider_playlist_id="PL1",
                title="Morning Mix",
            ),
            YouTubeMusicPlaylist(
                provider_playlist_id="PL2",
                title="Evening Mix",
            ),
        ],
    )

    assert [playlist.provider_playlist_id for playlist in inserted] == ["PL1", "PL2"]

    updated = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(
                provider_playlist_id="PL1",
                title="Morning Mix Updated",
            )
        ],
    )

    assert updated[0].id == inserted[0].id
    assert updated[0].title == "Morning Mix Updated"

    with engine.connect() as connection:
        stored_playlists = connection.execute(
            select(streaming_playlists_table).order_by(
                streaming_playlists_table.c.provider_playlist_id.asc()
            )
        ).mappings()
        stored_playlist_rows = list(stored_playlists)

    assert len(stored_playlist_rows) == 2
    assert stored_playlist_rows[0]["provider_playlist_id"] == "PL1"
    assert stored_playlist_rows[0]["title"] == "Morning Mix Updated"
    assert stored_playlist_rows[0]["synced_at"] is not None
    assert stored_playlist_rows[1]["provider_playlist_id"] == "PL2"
    assert stored_playlist_rows[1]["title"] == "Evening Mix"


def test_streaming_account_store_syncs_youtube_music_playlists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-sync.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )

    seen: dict[str, object] = {}

    class FakeAdapter:
        def list_library_playlists(self):
            return [YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")]

    def fake_from_browser_auth(auth, *, user=None, language="en", location=""):
        seen["auth"] = auth
        seen["user"] = user
        seen["language"] = language
        seen["location"] = location
        return FakeAdapter()

    monkeypatch.setattr(
        "app.streaming_accounts.YouTubeMusicAdapter.from_browser_auth",
        fake_from_browser_auth,
    )

    synced = store.sync_youtube_music_playlists(
        account_id=account.id,
    )

    assert len(synced) == 1
    assert synced[0].provider_playlist_id == "PL9"
    assert synced[0].title == "Gym"
    assert seen["auth"] == {"refresh_token": "refresh-token"}
    assert seen["user"] is None
    assert seen["language"] == "en"
    assert seen["location"] == ""


def test_streaming_account_store_lists_playlists_with_track_counts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlist-list.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    synced_at = datetime(2026, 5, 1, 8, 30, tzinfo=UTC)

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
        synced_at=synced_at,
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
                duration_ms=120000,
            ),
            YouTubeMusicTrack(
                provider_track_id="track-2",
                title="Track 2",
                artist="Artist 2",
                album=None,
                year=None,
                isrc=None,
                duration_ms=180000,
            ),
        ],
    )

    listed = store.list_playlists()

    assert [playlist.provider_playlist_id for playlist in listed] == ["PL1", "PL2"]
    assert listed[0].account_id == account.id
    assert listed[0].title == "Morning Mix"
    assert listed[0].track_count == 2
    assert listed[0].synced_at == synced_at.replace(tzinfo=None)
    assert listed[1].title == "Empty Playlist"
    assert listed[1].track_count == 0
    assert listed[1].synced_at == synced_at.replace(tzinfo=None)


def test_streaming_account_store_upserts_tracks_and_playlist_membership(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-tracks.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

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
    )[0]

    inserted = store.replace_playlist_membership(
        playlist_id=playlist.id,
        tracks=[
            YouTubeMusicTrack(
                provider_track_id="track-1",
                title="Track 1",
                artist="Artist 1",
                album="Album 1",
                year=2021,
                isrc="GBUM72105976",
                duration_ms=180000,
            ),
            YouTubeMusicTrack(
                provider_track_id="track-2",
                title="Track 2",
                artist="Artist 2",
                album=None,
                year=None,
                isrc=None,
                duration_ms=None,
            ),
        ],
    )

    assert [membership.position for membership in inserted] == [1, 2]

    updated = store.replace_playlist_membership(
        playlist_id=playlist.id,
        tracks=[
            YouTubeMusicTrack(
                provider_track_id="track-2",
                title="Track 2 Updated",
                artist="Artist 2",
                album="Album 2",
                year=2024,
                isrc="USQX92200001",
                duration_ms=200000,
            ),
            YouTubeMusicTrack(
                provider_track_id="track-1",
                title="Track 1",
                artist="Artist 1",
                album="Album 1",
                year=2021,
                isrc=None,
                duration_ms=180000,
            ),
        ],
    )

    assert [membership.position for membership in updated] == [1, 2]

    with engine.connect() as connection:
        stored_tracks = list(
            connection.execute(
                select(streaming_tracks_table).order_by(
                    streaming_tracks_table.c.provider_track_id.asc()
                )
            ).mappings()
        )
        stored_memberships = list(
            connection.execute(
                select(playlist_membership_table).order_by(
                    playlist_membership_table.c.position.asc()
                )
            ).mappings()
        )

    assert len(stored_tracks) == 2
    assert stored_tracks[0]["provider_track_id"] == "track-1"
    assert stored_tracks[1]["provider_track_id"] == "track-2"
    assert stored_tracks[1]["title"] == "Track 2 Updated"
    assert stored_tracks[1]["album"] == "Album 2"
    assert stored_tracks[1]["year"] == 2024
    assert stored_tracks[0]["isrc"] == "GBUM72105976"
    assert stored_tracks[1]["isrc"] == "USQX92200001"
    assert stored_tracks[1]["duration_ms"] == 200000
    assert len(stored_memberships) == 2
    assert stored_memberships[0]["playlist_id"] == playlist.id
    assert stored_memberships[0]["position"] == 1
    assert stored_memberships[0]["streaming_track_id"] == stored_tracks[1]["id"]
    assert stored_memberships[1]["playlist_id"] == playlist.id
    assert stored_memberships[1]["position"] == 2
    assert stored_memberships[1]["streaming_track_id"] == stored_tracks[0]["id"]


def test_streaming_account_store_syncs_youtube_music_playlist_tracks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-track-sync.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )

    seen: dict[str, object] = {}

    class FakeAdapter:
        def list_library_playlists(self):
            return [YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")]

        def list_playlist_tracks(self, playlist_id):
            seen["playlist_id"] = playlist_id
            return [
                YouTubeMusicTrack(
                    provider_track_id="track-9",
                    title="Workout",
                    artist="Artist 9",
                    album=None,
                    year=None,
                    isrc=None,
                    duration_ms=120000,
                )
            ]

    def fake_from_browser_auth(auth, *, user=None, language="en", location=""):
        seen["auth"] = auth
        seen["user"] = user
        seen["language"] = language
        seen["location"] = location
        return FakeAdapter()

    monkeypatch.setattr(
        "app.streaming_accounts.YouTubeMusicAdapter.from_browser_auth",
        fake_from_browser_auth,
    )

    synced = store.sync_youtube_music_playlist_tracks(
        account_id=account.id,
    )

    assert len(synced) == 1
    assert synced[0].position == 1
    assert seen["playlist_id"] == "PL9"
    assert seen["auth"] == {"refresh_token": "refresh-token"}
    assert seen["user"] is None
    assert seen["language"] == "en"
    assert seen["location"] == ""

    with engine.connect() as connection:
        stored_tracks = list(
            connection.execute(select(streaming_tracks_table)).mappings()
        )
        stored_memberships = list(
            connection.execute(select(playlist_membership_table)).mappings()
        )

    assert len(stored_tracks) == 1
    assert stored_tracks[0]["provider_track_id"] == "track-9"
    assert len(stored_memberships) == 1


def test_streaming_account_store_marks_auth_errors_without_crashing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-auth-error.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )

    def fake_from_browser_auth(auth, *, user=None, language="en", location=""):
        raise YTMusicUserError("refresh token expired")

    monkeypatch.setattr(
        "app.streaming_accounts.YouTubeMusicAdapter.from_browser_auth",
        fake_from_browser_auth,
    )

    synced = store.sync_youtube_music_account(account_id=account.id)

    assert synced == []

    persisted = store.list_accounts()[0]
    assert persisted.auth_state == "error"
    assert (
        persisted.auth_error
        == "YouTube Music authentication failed: refresh token expired"
    )
    assert persisted.auth_error_at is not None


def test_streaming_account_store_clears_auth_errors_after_successful_sync(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-auth-recovery.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    store.mark_account_auth_error(
        account_id=account.id,
        error=YTMusicUserError("expired credentials"),
    )

    class FakeAdapter:
        def list_library_playlists(self):
            return [YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")]

        def list_playlist_tracks(self, playlist_id):
            return []

    monkeypatch.setattr(
        "app.streaming_accounts.YouTubeMusicAdapter.from_browser_auth",
        lambda auth, *, user=None, language="en", location="": FakeAdapter(),
    )

    synced = store.sync_youtube_music_account(account_id=account.id)

    assert synced == []

    persisted = store.list_accounts()[0]
    assert persisted.auth_state == "connected"
    assert persisted.auth_error is None
    assert persisted.auth_error_at is None


def test_run_youtube_music_sync_job_uses_database(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///worker.db")
    seen: dict[str, object] = {}

    class FakeStore:
        def __init__(self, database_url: str) -> None:
            seen["database_url"] = database_url

        def sync_youtube_music_account(self, *, account_id) -> list[object]:
            seen["account_id"] = account_id
            return []

    monkeypatch.setattr("app.streaming_accounts.StreamingAccountStore", FakeStore)

    run_youtube_music_sync_job(7)

    assert seen["database_url"] == "sqlite:///worker.db"
    assert seen["account_id"] == 7


def _decrypt_token(auth_token_blob: str) -> str:
    key = os.environ["TOKEN_ENCRYPTION_KEY"]
    return (
        Fernet(key.encode("utf-8"))
        .decrypt(auth_token_blob.encode("utf-8"))
        .decode("utf-8")
    )
