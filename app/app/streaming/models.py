from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, func


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
    browser_headers: dict[str, object]


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
