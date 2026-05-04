from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select, update
from ytmusicapi.exceptions import YTMusicUserError

from app.streaming.jobs import (
    run_youtube_music_playlist_metadata_refresh_job,
    run_youtube_music_playlist_sync_job,
    run_youtube_music_sync_job,
)
from app.streaming.models import (
    YOUTUBE_MUSIC_PROVIDER,
    metadata,
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.store import StreamingAccountStore
from app.streaming.adapters.youtube_music import (
    MalformedPlaylistPayloadError,
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


def test_streaming_account_store_updates_playlist_selected_for_sync(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlist-selection.db'}"
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

    assert playlist.selected_for_sync is False

    selected = store.set_playlist_selected_for_sync(
        playlist_id=playlist.id,
        selected_for_sync=True,
    )
    assert selected is not None
    assert selected.selected_for_sync is True

    updated = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(
                provider_playlist_id="PL1",
                title="Morning Mix Updated",
            )
        ],
    )[0]

    assert updated.selected_for_sync is True
    assert (
        store.set_playlist_selected_for_sync(
            playlist_id=999,
            selected_for_sync=True,
        )
        is None
    )


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
    playlist = store.upsert_playlists(
        account_id=account.id,
        playlists=[YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")],
    )[0]
    store.set_playlist_selected_for_sync(
        playlist_id=playlist.id,
        selected_for_sync=True,
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
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
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


def test_streaming_account_store_persists_playlist_sync_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-playlist-failures.db'}"
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
    failed_at = datetime(2026, 5, 2, 11, 45, tzinfo=UTC)

    store.mark_playlist_sync_failure(
        playlist_id=playlist.id,
        error="invalid tracks payload",
        failed_at=failed_at,
    )

    failed_playlist = store.list_playlists()[0]
    assert failed_playlist.last_sync_error == "invalid tracks payload"
    assert failed_playlist.last_sync_error_at == failed_at.replace(tzinfo=None)

    store.clear_playlist_sync_failure(playlist_id=playlist.id)

    recovered_playlist = store.list_playlists()[0]
    assert recovered_playlist.last_sync_error is None
    assert recovered_playlist.last_sync_error_at is None


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

    fingerprinted_at = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            update(streaming_tracks_table)
            .where(streaming_tracks_table.c.provider_track_id == "track-2")
            .values(
                fingerprint="stream-fp-2",
                fingerprint_duration_seconds=200.5,
                fingerprinted_at=fingerprinted_at,
            )
        )

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
    assert stored_tracks[1]["fingerprint"] == "stream-fp-2"
    assert stored_tracks[1]["fingerprint_duration_seconds"] == 200.5
    assert stored_tracks[1]["fingerprinted_at"] == fingerprinted_at.replace(tzinfo=None)
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
    playlist = store.upsert_playlists(
        account_id=account.id,
        playlists=[YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")],
    )[0]
    store.set_playlist_selected_for_sync(
        playlist_id=playlist.id,
        selected_for_sync=True,
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
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
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


def test_streaming_account_store_syncs_only_selected_playlist_tracks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-selected-sync.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlists = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Selected Mix"),
            YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Skipped Mix"),
        ],
    )
    store.set_playlist_selected_for_sync(
        playlist_id=playlists[0].id,
        selected_for_sync=True,
    )

    seen: dict[str, list[str]] = {"playlist_ids": []}

    class FakeAdapter:
        def list_library_playlists(self):
            return [
                YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Selected Mix"),
                YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Skipped Mix"),
            ]

        def list_playlist_tracks(self, playlist_id):
            seen["playlist_ids"].append(playlist_id)
            return [
                YouTubeMusicTrack(
                    provider_track_id=f"{playlist_id}-track",
                    title="Synced Track",
                    artist="Artist",
                    album=None,
                    year=None,
                    isrc=None,
                    duration_ms=120000,
                )
            ]

    monkeypatch.setattr(
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
        lambda auth, *, user=None, language="en", location="": FakeAdapter(),
    )

    synced = store.sync_youtube_music_playlist_tracks(account_id=account.id)

    with engine.connect() as connection:
        stored_memberships = list(
            connection.execute(select(playlist_membership_table)).mappings()
        )

    assert seen["playlist_ids"] == ["PL1"]
    assert [membership.playlist_id for membership in synced] == [playlists[0].id]
    assert [membership["playlist_id"] for membership in stored_memberships] == [
        playlists[0].id
    ]


def test_streaming_account_store_syncs_single_playlist_ignoring_selected_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-single-playlist-sync.db'}"
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
        playlists=[YouTubeMusicPlaylist(provider_playlist_id="PL9", title="Gym")],
    )[0]

    seen: dict[str, object] = {}

    class FakeAdapter:
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

    monkeypatch.setattr(
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
        lambda auth, *, user=None, language="en", location="": FakeAdapter(),
    )

    synced = store.sync_youtube_music_playlist(playlist_id=playlist.id)

    with engine.connect() as connection:
        stored_memberships = list(
            connection.execute(select(playlist_membership_table)).mappings()
        )

    assert seen["playlist_id"] == "PL9"
    assert [membership.playlist_id for membership in synced] == [playlist.id]
    assert [membership["playlist_id"] for membership in stored_memberships] == [
        playlist.id
    ]
    assert store.list_playlists()[0].selected_for_sync is False


def test_streaming_account_store_preserves_membership_for_malformed_playlist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-malformed-playlist.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlists = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Saved Mix"),
            YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Fresh Mix"),
        ],
    )
    for playlist in playlists:
        store.set_playlist_selected_for_sync(
            playlist_id=playlist.id,
            selected_for_sync=True,
        )
    store.replace_playlist_membership(
        playlist_id=playlists[0].id,
        tracks=[
            YouTubeMusicTrack(
                provider_track_id="old-track",
                title="Old Track",
                artist="Old Artist",
                album=None,
                year=None,
                isrc=None,
                duration_ms=90000,
            )
        ],
    )

    class FakeAdapter:
        def list_library_playlists(self):
            return [
                YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Saved Mix"),
                YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Fresh Mix"),
            ]

        def list_playlist_tracks(self, playlist_id):
            if playlist_id == "PL1":
                raise MalformedPlaylistPayloadError("invalid tracks payload")
            return [
                YouTubeMusicTrack(
                    provider_track_id="new-track",
                    title="New Track",
                    artist="New Artist",
                    album=None,
                    year=None,
                    isrc=None,
                    duration_ms=120000,
                )
            ]

    monkeypatch.setattr(
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
        lambda auth, *, user=None, language="en", location="": FakeAdapter(),
    )

    synced = store.sync_youtube_music_playlist_tracks(account_id=account.id)

    with engine.connect() as connection:
        stored_memberships = list(
            connection.execute(
                select(
                    playlist_membership_table.c.playlist_id,
                    playlist_membership_table.c.position,
                    streaming_tracks_table.c.provider_track_id,
                )
                .select_from(
                    playlist_membership_table.join(
                        streaming_tracks_table,
                        streaming_tracks_table.c.id
                        == playlist_membership_table.c.streaming_track_id,
                    )
                )
                .order_by(
                    playlist_membership_table.c.playlist_id.asc(),
                    playlist_membership_table.c.position.asc(),
                )
            ).mappings()
        )

    assert [membership.playlist_id for membership in synced] == [playlists[1].id]
    assert [
        (membership["playlist_id"], membership["provider_track_id"])
        for membership in stored_memberships
    ] == [
        (playlists[0].id, "old-track"),
        (playlists[1].id, "new-track"),
    ]

    persisted = store.list_playlists()
    assert persisted[0].last_sync_error == "invalid tracks payload"
    assert persisted[0].last_sync_error_at is not None
    assert persisted[1].last_sync_error is None
    assert persisted[1].last_sync_error_at is None


def test_streaming_account_store_empty_playlist_clears_membership_and_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-empty-playlist.db'}"
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
        playlists=[YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Saved Mix")],
    )[0]
    store.set_playlist_selected_for_sync(
        playlist_id=playlist.id,
        selected_for_sync=True,
    )
    store.replace_playlist_membership(
        playlist_id=playlist.id,
        tracks=[
            YouTubeMusicTrack(
                provider_track_id="old-track",
                title="Old Track",
                artist="Old Artist",
                album=None,
                year=None,
                isrc=None,
                duration_ms=90000,
            )
        ],
    )
    store.mark_playlist_sync_failure(
        playlist_id=playlist.id,
        error="previous sync failed",
        failed_at=datetime(2026, 5, 2, 11, 45, tzinfo=UTC),
    )

    class FakeAdapter:
        def list_library_playlists(self):
            return [YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Saved Mix")]

        def list_playlist_tracks(self, playlist_id):
            return []

    monkeypatch.setattr(
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
        lambda auth, *, user=None, language="en", location="": FakeAdapter(),
    )

    synced = store.sync_youtube_music_playlist_tracks(account_id=account.id)

    with engine.connect() as connection:
        stored_memberships = list(
            connection.execute(select(playlist_membership_table)).mappings()
        )

    assert synced == []
    assert stored_memberships == []
    persisted = store.list_playlists()[0]
    assert persisted.last_sync_error is None
    assert persisted.last_sync_error_at is None


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
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
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
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
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

    monkeypatch.setattr("app.streaming.jobs.StreamingAccountStore", FakeStore)

    run_youtube_music_sync_job(7)

    assert seen["database_url"] == "sqlite:///worker.db"
    assert seen["account_id"] == 7


def test_run_youtube_music_playlist_metadata_refresh_job_uses_database(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///worker.db")
    seen: dict[str, object] = {}

    class FakeStore:
        def __init__(self, database_url: str) -> None:
            seen["database_url"] = database_url

        def sync_youtube_music_playlists(self, *, account_id) -> list[object]:
            seen["account_id"] = account_id
            return []

    monkeypatch.setattr("app.streaming.jobs.StreamingAccountStore", FakeStore)

    run_youtube_music_playlist_metadata_refresh_job(7)

    assert seen["database_url"] == "sqlite:///worker.db"
    assert seen["account_id"] == 7


def test_run_youtube_music_playlist_sync_job_uses_database(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///worker.db")
    seen: dict[str, object] = {}

    class FakeStore:
        def __init__(self, database_url: str) -> None:
            seen["database_url"] = database_url

        def sync_youtube_music_playlist(self, *, playlist_id) -> list[object]:
            seen["playlist_id"] = playlist_id
            return []

    monkeypatch.setattr("app.streaming.jobs.StreamingAccountStore", FakeStore)

    run_youtube_music_playlist_sync_job(11)

    assert seen["database_url"] == "sqlite:///worker.db"
    assert seen["playlist_id"] == 11


def _decrypt_token(auth_token_blob: str) -> str:
    key = os.environ["TOKEN_ENCRYPTION_KEY"]
    return (
        Fernet(key.encode("utf-8"))
        .decrypt(auth_token_blob.encode("utf-8"))
        .decode("utf-8")
    )
