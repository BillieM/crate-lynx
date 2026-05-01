from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import (
    Column,
    DateTime,
    delete,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
    select,
    update,
)
from ytmusicapi.exceptions import YTMusicError

from app.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicOAuthCredentials,
    YouTubeMusicPlaylist,
    YouTubeMusicTrack,
    sync_library_playlists,
    sync_library_playlist_tracks,
)


YOUTUBE_MUSIC_PROVIDER = "youtube_music"
STREAMING_ACCOUNT_AUTH_STATE_CONNECTED = "connected"
STREAMING_ACCOUNT_AUTH_STATE_ERROR = "error"

metadata = MetaData()

streaming_accounts_table = Table(
    "streaming_accounts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("provider", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("auth_token_blob", String, nullable=False),
    Column("auth_state", String, nullable=False),
    Column("auth_error", String, nullable=True),
    Column("auth_error_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
)

streaming_playlists_table = Table(
    "streaming_playlists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("account_id", Integer, nullable=False),
    Column("provider_playlist_id", String, nullable=False),
    Column("title", String, nullable=False),
    Column("synced_at", DateTime(timezone=True), nullable=True),
)

streaming_tracks_table = Table(
    "streaming_tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("provider_track_id", String, nullable=False),
    Column("title", String, nullable=False),
    Column("artist", String, nullable=False),
    Column("album", String, nullable=True),
    Column("year", Integer, nullable=True),
    Column("isrc", String, nullable=True),
    Column("duration_ms", Integer, nullable=True),
)

playlist_membership_table = Table(
    "playlist_membership",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("playlist_id", Integer, nullable=False),
    Column("streaming_track_id", Integer, nullable=False),
    Column("position", Integer, nullable=False),
)


@dataclass(frozen=True, slots=True)
class PersistedStreamingAccount:
    id: int
    provider: str
    display_name: str


@dataclass(frozen=True, slots=True)
class StreamingAccountRecord(PersistedStreamingAccount):
    auth_state: str
    auth_error: str | None
    auth_error_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredStreamingAccount:
    id: int
    provider: str
    display_name: str
    auth_state: str
    auth_error: str | None
    auth_error_at: datetime | None
    oauth_token: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StreamingPlaylistRecord:
    id: int
    account_id: int
    provider_playlist_id: str
    title: str
    synced_at: datetime | None


@dataclass(frozen=True, slots=True)
class StreamingPlaylistSummary:
    id: int
    account_id: int
    provider_playlist_id: str
    title: str
    track_count: int
    synced_at: datetime | None


@dataclass(frozen=True, slots=True)
class StreamingTrackRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class PlaylistMembershipRecord:
    id: int
    playlist_id: int
    streaming_track_id: int
    position: int


class StreamingAccountStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def create_youtube_music_account(
        self,
        *,
        display_name: str,
        oauth_token: dict[str, Any],
    ) -> PersistedStreamingAccount:
        encrypted_token = encrypt_token(json.dumps(oauth_token, sort_keys=True))

        with self._engine.begin() as connection:
            result = connection.execute(
                insert(streaming_accounts_table).values(
                    provider=YOUTUBE_MUSIC_PROVIDER,
                    display_name=display_name,
                    auth_token_blob=encrypted_token,
                    auth_state=STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
                    auth_error=None,
                    auth_error_at=None,
                )
            )

        inserted_id = result.inserted_primary_key[0]
        if not isinstance(inserted_id, int):
            raise ValueError("Failed to persist streaming account")

        return PersistedStreamingAccount(
            id=inserted_id,
            provider=YOUTUBE_MUSIC_PROVIDER,
            display_name=display_name,
        )

    def list_accounts(self) -> list[StreamingAccountRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    streaming_accounts_table.c.id,
                    streaming_accounts_table.c.provider,
                    streaming_accounts_table.c.display_name,
                    streaming_accounts_table.c.auth_state,
                    streaming_accounts_table.c.auth_error,
                    streaming_accounts_table.c.auth_error_at,
                    streaming_accounts_table.c.created_at,
                    streaming_accounts_table.c.updated_at,
                ).order_by(streaming_accounts_table.c.id.asc())
            ).mappings()

            return [
                StreamingAccountRecord(
                    id=row["id"],
                    provider=row["provider"],
                    display_name=row["display_name"],
                    auth_state=row["auth_state"],
                    auth_error=row["auth_error"],
                    auth_error_at=row["auth_error_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    def get_account(self, account_id: int) -> StoredStreamingAccount:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        streaming_accounts_table.c.id,
                        streaming_accounts_table.c.provider,
                        streaming_accounts_table.c.display_name,
                        streaming_accounts_table.c.auth_state,
                        streaming_accounts_table.c.auth_error,
                        streaming_accounts_table.c.auth_error_at,
                        streaming_accounts_table.c.auth_token_blob,
                    ).where(streaming_accounts_table.c.id == account_id)
                )
                .mappings()
                .one()
            )

        return StoredStreamingAccount(
            id=row["id"],
            provider=row["provider"],
            display_name=row["display_name"],
            auth_state=row["auth_state"],
            auth_error=row["auth_error"],
            auth_error_at=row["auth_error_at"],
            oauth_token=json.loads(decrypt_token(row["auth_token_blob"])),
        )

    def clear_account_auth_error(self, *, account_id: int) -> None:
        self._set_account_auth_state(
            account_id=account_id,
            auth_state=STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
            auth_error=None,
        )

    def mark_account_auth_error(self, *, account_id: int, error: Exception) -> None:
        self._set_account_auth_state(
            account_id=account_id,
            auth_state=STREAMING_ACCOUNT_AUTH_STATE_ERROR,
            auth_error=_format_auth_error(error),
        )

    def _set_account_auth_state(
        self,
        *,
        account_id: int,
        auth_state: str,
        auth_error: str | None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(streaming_accounts_table)
                .where(streaming_accounts_table.c.id == account_id)
                .values(
                    auth_state=auth_state,
                    auth_error=auth_error,
                    auth_error_at=(None if auth_error is None else datetime.now(UTC)),
                    updated_at=datetime.now(UTC),
                )
            )

    def upsert_playlists(
        self,
        *,
        account_id: int,
        playlists: list[YouTubeMusicPlaylist],
        synced_at: datetime | None = None,
    ) -> list[StreamingPlaylistRecord]:
        playlist_rows: list[StreamingPlaylistRecord] = []
        sync_timestamp = synced_at or datetime.now(UTC)

        with self._engine.begin() as connection:
            for playlist in playlists:
                existing = (
                    connection.execute(
                        select(
                            streaming_playlists_table.c.id,
                            streaming_playlists_table.c.account_id,
                            streaming_playlists_table.c.provider_playlist_id,
                            streaming_playlists_table.c.title,
                            streaming_playlists_table.c.synced_at,
                        ).where(
                            streaming_playlists_table.c.account_id == account_id,
                            streaming_playlists_table.c.provider_playlist_id
                            == playlist.provider_playlist_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )

                if existing is None:
                    result = connection.execute(
                        insert(streaming_playlists_table).values(
                            account_id=account_id,
                            provider_playlist_id=playlist.provider_playlist_id,
                            title=playlist.title,
                            synced_at=sync_timestamp,
                        )
                    )
                    playlist_id = result.inserted_primary_key[0]
                    if not isinstance(playlist_id, int):
                        raise ValueError("Failed to persist streaming playlist")
                    playlist_rows.append(
                        StreamingPlaylistRecord(
                            id=playlist_id,
                            account_id=account_id,
                            provider_playlist_id=playlist.provider_playlist_id,
                            title=playlist.title,
                            synced_at=sync_timestamp,
                        )
                    )
                    continue

                connection.execute(
                    update(streaming_playlists_table)
                    .where(streaming_playlists_table.c.id == existing["id"])
                    .values(
                        title=playlist.title,
                        synced_at=sync_timestamp,
                    )
                )
                playlist_rows.append(
                    StreamingPlaylistRecord(
                        id=existing["id"],
                        account_id=existing["account_id"],
                        provider_playlist_id=existing["provider_playlist_id"],
                        title=playlist.title,
                        synced_at=sync_timestamp,
                    )
                )

        return playlist_rows

    def list_playlists(self) -> list[StreamingPlaylistSummary]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.account_id,
                    streaming_playlists_table.c.provider_playlist_id,
                    streaming_playlists_table.c.title,
                    streaming_playlists_table.c.synced_at,
                    func.count(playlist_membership_table.c.id).label("track_count"),
                )
                .select_from(
                    streaming_playlists_table.outerjoin(
                        playlist_membership_table,
                        playlist_membership_table.c.playlist_id
                        == streaming_playlists_table.c.id,
                    )
                )
                .group_by(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.account_id,
                    streaming_playlists_table.c.provider_playlist_id,
                    streaming_playlists_table.c.title,
                    streaming_playlists_table.c.synced_at,
                )
                .order_by(streaming_playlists_table.c.id.asc())
            ).mappings()

            return [
                StreamingPlaylistSummary(
                    id=row["id"],
                    account_id=row["account_id"],
                    provider_playlist_id=row["provider_playlist_id"],
                    title=row["title"],
                    track_count=row["track_count"],
                    synced_at=row["synced_at"],
                )
                for row in rows
            ]

    def upsert_tracks(
        self,
        *,
        tracks: list[YouTubeMusicTrack],
    ) -> list[StreamingTrackRecord]:
        track_rows: list[StreamingTrackRecord] = []

        with self._engine.begin() as connection:
            for track in tracks:
                existing = (
                    connection.execute(
                        select(
                            streaming_tracks_table.c.id,
                            streaming_tracks_table.c.provider_track_id,
                            streaming_tracks_table.c.title,
                            streaming_tracks_table.c.artist,
                            streaming_tracks_table.c.album,
                            streaming_tracks_table.c.year,
                            streaming_tracks_table.c.isrc,
                            streaming_tracks_table.c.duration_ms,
                        ).where(
                            streaming_tracks_table.c.provider_track_id
                            == track.provider_track_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )

                if existing is None:
                    result = connection.execute(
                        insert(streaming_tracks_table).values(
                            provider_track_id=track.provider_track_id,
                            title=track.title,
                            artist=track.artist,
                            album=track.album,
                            year=track.year,
                            isrc=track.isrc,
                            duration_ms=track.duration_ms,
                        )
                    )
                    track_id = result.inserted_primary_key[0]
                    if not isinstance(track_id, int):
                        raise ValueError("Failed to persist streaming track")
                    track_rows.append(
                        StreamingTrackRecord(
                            id=track_id,
                            provider_track_id=track.provider_track_id,
                            title=track.title,
                            artist=track.artist,
                            album=track.album,
                            year=track.year,
                            isrc=track.isrc,
                            duration_ms=track.duration_ms,
                        )
                    )
                    continue

                isrc = track.isrc if track.isrc is not None else existing["isrc"]
                connection.execute(
                    update(streaming_tracks_table)
                    .where(streaming_tracks_table.c.id == existing["id"])
                    .values(
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        year=track.year,
                        isrc=isrc,
                        duration_ms=track.duration_ms,
                    )
                )
                track_rows.append(
                    StreamingTrackRecord(
                        id=existing["id"],
                        provider_track_id=track.provider_track_id,
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        year=track.year,
                        isrc=isrc,
                        duration_ms=track.duration_ms,
                    )
                )

        return track_rows

    def replace_playlist_membership(
        self,
        *,
        playlist_id: int,
        tracks: list[YouTubeMusicTrack],
    ) -> list[PlaylistMembershipRecord]:
        track_rows = self.upsert_tracks(tracks=tracks)
        membership_rows: list[PlaylistMembershipRecord] = []

        with self._engine.begin() as connection:
            connection.execute(
                delete(playlist_membership_table).where(
                    playlist_membership_table.c.playlist_id == playlist_id
                )
            )

            for position, track in enumerate(track_rows, start=1):
                result = connection.execute(
                    insert(playlist_membership_table).values(
                        playlist_id=playlist_id,
                        streaming_track_id=track.id,
                        position=position,
                    )
                )
                membership_id = result.inserted_primary_key[0]
                if not isinstance(membership_id, int):
                    raise ValueError("Failed to persist playlist membership")
                membership_rows.append(
                    PlaylistMembershipRecord(
                        id=membership_id,
                        playlist_id=playlist_id,
                        streaming_track_id=track.id,
                        position=position,
                    )
                )

        return membership_rows

    def sync_youtube_music_playlists(
        self,
        *,
        account_id: int,
        credentials: YouTubeMusicOAuthCredentials,
    ) -> list[StreamingPlaylistRecord]:
        return self._run_youtube_music_sync(
            account_id=account_id,
            credentials=credentials,
            run_sync=lambda adapter: sync_library_playlists(
                account_id=account_id,
                adapter=adapter,
                playlist_store=self,
            ),
        )

    def sync_youtube_music_playlist_tracks(
        self,
        *,
        account_id: int,
        credentials: YouTubeMusicOAuthCredentials,
    ) -> list[PlaylistMembershipRecord]:
        return self._run_youtube_music_sync(
            account_id=account_id,
            credentials=credentials,
            run_sync=lambda adapter: sync_library_playlist_tracks(
                account_id=account_id,
                adapter=adapter,
                playlist_store=self,
            ),
        )

    def sync_youtube_music_account(
        self,
        *,
        account_id: int,
        credentials: YouTubeMusicOAuthCredentials,
    ) -> list[PlaylistMembershipRecord]:
        return self._run_youtube_music_sync(
            account_id=account_id,
            credentials=credentials,
            run_sync=lambda adapter: sync_library_playlist_tracks(
                account_id=account_id,
                adapter=adapter,
                playlist_store=self,
            ),
        )

    def _run_youtube_music_sync(
        self,
        *,
        account_id: int,
        credentials: YouTubeMusicOAuthCredentials,
        run_sync: Any,
    ) -> list[Any]:
        account = self.get_account(account_id)
        try:
            adapter = YouTubeMusicAdapter.from_oauth_token(
                account.oauth_token,
                credentials=credentials,
            )
            synced = run_sync(adapter)
        except YTMusicError as exc:
            self.mark_account_auth_error(account_id=account_id, error=exc)
            return []

        self.clear_account_auth_error(account_id=account_id)
        return synced


def connect_youtube_music_account(
    *,
    database_url: str,
    display_name: str,
    credentials: YouTubeMusicOAuthCredentials,
    token_filepath: str | Path | None = None,
    open_browser: bool = False,
) -> PersistedStreamingAccount:
    oauth_token = YouTubeMusicAdapter.setup_oauth(
        credentials,
        filepath=token_filepath,
        open_browser=open_browser,
    )

    return StreamingAccountStore(database_url).create_youtube_music_account(
        display_name=display_name,
        oauth_token=oauth_token,
    )


def begin_youtube_music_account_oauth(
    *,
    credentials: YouTubeMusicOAuthCredentials,
) -> dict[str, Any]:
    return YouTubeMusicAdapter.begin_oauth(credentials)


def complete_youtube_music_account_oauth(
    *,
    database_url: str,
    display_name: str,
    credentials: YouTubeMusicOAuthCredentials,
    device_code: str,
) -> PersistedStreamingAccount:
    oauth_token = YouTubeMusicAdapter.complete_oauth(
        credentials,
        device_code=device_code,
    )

    return StreamingAccountStore(database_url).create_youtube_music_account(
        display_name=display_name,
        oauth_token=oauth_token,
    )


def run_youtube_music_sync_job(
    account_id: int,
    client_id: str,
    client_secret: str,
) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL must be configured for YouTube Music sync jobs"
        )

    StreamingAccountStore(database_url).sync_youtube_music_account(
        account_id=account_id,
        credentials=YouTubeMusicOAuthCredentials(
            client_id=client_id,
            client_secret=client_secret,
        ),
    )


def encrypt_token(raw_token: str) -> str:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for token encryption")

    try:
        fernet = Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

    return fernet.encrypt(raw_token.encode("utf-8")).decode("utf-8")


def decrypt_token(auth_token_blob: str) -> str:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for token encryption")

    try:
        fernet = Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

    return fernet.decrypt(auth_token_blob.encode("utf-8")).decode("utf-8")


def _format_auth_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "Authentication with YouTube Music failed."
    return f"YouTube Music authentication failed: {message}"
