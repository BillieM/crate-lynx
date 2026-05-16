from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)


YOUTUBE_MUSIC_PROVIDER = "youtube_music"
STREAMING_ACCOUNT_AUTH_STATE_CONNECTED = "connected"
STREAMING_ACCOUNT_AUTH_STATE_ERROR = "error"
PLAYLIST_SYNC_MODE_OFF = "off"
PLAYLIST_SYNC_MODE_MATCH_ONLY = "match_only"
PLAYLIST_SYNC_MODE_FULL = "full"
PLAYLIST_SYNC_MODES = (
    PLAYLIST_SYNC_MODE_OFF,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_FULL,
)

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
    Column(
        "sync_mode",
        String,
        nullable=False,
        server_default=text(f"'{PLAYLIST_SYNC_MODE_OFF}'"),
    ),
    Column("provider_track_count", Integer, nullable=True),
    Column("metadata_synced_at", DateTime(timezone=True), nullable=True),
    Column("tracks_synced_at", DateTime(timezone=True), nullable=True),
    Column("last_sync_error", String, nullable=True),
    Column("last_sync_error_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "sync_mode IN ('off', 'match_only', 'full')",
        name="ck_streaming_playlists_sync_mode",
    ),
    UniqueConstraint(
        "account_id",
        "provider_playlist_id",
        name="uq_streaming_playlists_account_id_provider_playlist_id",
    ),
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
    UniqueConstraint(
        "provider_track_id",
        name="uq_streaming_tracks_provider_track_id",
    ),
    Index("ix_streaming_tracks_isrc", "isrc"),
    Index(
        "ix_streaming_tracks_title_trgm",
        "title",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    ),
)

playlist_membership_table = Table(
    "playlist_membership",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("playlist_id", Integer, nullable=False),
    Column("streaming_track_id", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Index("ix_playlist_membership_playlist_id", "playlist_id"),
    Index("ix_playlist_membership_streaming_track_id", "streaming_track_id"),
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
    sync_mode: str
    provider_track_count: int | None
    metadata_synced_at: datetime | None
    tracks_synced_at: datetime | None
    last_sync_error: str | None
    last_sync_error_at: datetime | None

    @property
    def selected_for_sync(self) -> bool:
        return self.sync_mode == PLAYLIST_SYNC_MODE_FULL

    @property
    def synced_at(self) -> datetime | None:
        return self.tracks_synced_at or self.metadata_synced_at


@dataclass(frozen=True, slots=True)
class StreamingPlaylistSummary:
    id: int
    account_id: int
    provider_playlist_id: str
    title: str
    sync_mode: str
    provider_track_count: int | None
    imported_track_count: int
    metadata_synced_at: datetime | None
    tracks_synced_at: datetime | None
    last_sync_error: str | None
    last_sync_error_at: datetime | None

    @property
    def selected_for_sync(self) -> bool:
        return self.sync_mode == PLAYLIST_SYNC_MODE_FULL

    @property
    def synced_at(self) -> datetime | None:
        return self.tracks_synced_at or self.metadata_synced_at


@dataclass(frozen=True, slots=True)
class StreamingPlaylistDetail(StreamingPlaylistSummary):
    cover_art_url: str | None
    linked_count: int
    pending_count: int
    unlinked_count: int


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


@dataclass(frozen=True, slots=True)
class StreamingPlaylistTrack:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    position: int
    status: str
    final_link_id: int | None
    local_track_id: int | None
    proposal_id: int | None
