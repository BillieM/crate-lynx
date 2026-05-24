from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)


SONIC_ANALYZER_LIBROSA_V1 = "librosa_v1"
SONIC_FEATURE_STATUS_PENDING = "pending"
SONIC_FEATURE_STATUS_READY = "ready"
SONIC_FEATURE_STATUS_FAILED = "failed"
SONIC_FEATURE_STATUSES = (
    SONIC_FEATURE_STATUS_PENDING,
    SONIC_FEATURE_STATUS_READY,
    SONIC_FEATURE_STATUS_FAILED,
)

PLAYLIST_GENERATION_STATUS_PENDING = "pending"
PLAYLIST_GENERATION_STATUS_RUNNING = "running"
PLAYLIST_GENERATION_STATUS_COMPLETED = "completed"
PLAYLIST_GENERATION_STATUS_FAILED = "failed"
PLAYLIST_GENERATION_STATUSES = (
    PLAYLIST_GENERATION_STATUS_PENDING,
    PLAYLIST_GENERATION_STATUS_RUNNING,
    PLAYLIST_GENERATION_STATUS_COMPLETED,
    PLAYLIST_GENERATION_STATUS_FAILED,
)

PLAYLIST_GENERATION_METHOD_KMEANS = "kmeans"
PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE = "agglomerative"
PLAYLIST_GENERATION_METHODS = (
    PLAYLIST_GENERATION_METHOD_KMEANS,
    PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
)

SONIC_SOURCE_ALL_LOCAL = "all_local"
SONIC_SOURCE_STREAMING_PLAYLISTS = "streaming_playlists"
SONIC_SOURCE_TYPES = (SONIC_SOURCE_ALL_LOCAL, SONIC_SOURCE_STREAMING_PLAYLISTS)

SONIC_TAG_FILTER_ITEM_FIELD = "item_field"
SONIC_TAG_FILTER_ITEM_ATTRIBUTE = "item_attribute"
SONIC_TAG_FILTER_SCOPES = (
    SONIC_TAG_FILTER_ITEM_FIELD,
    SONIC_TAG_FILTER_ITEM_ATTRIBUTE,
)
SONIC_TAG_FILTER_MATCH_EQUALS = "equals"
SONIC_TAG_FILTER_MATCH_CONTAINS = "contains"
SONIC_TAG_FILTER_MATCHES = (
    SONIC_TAG_FILTER_MATCH_EQUALS,
    SONIC_TAG_FILTER_MATCH_CONTAINS,
)

metadata = MetaData()

sonic_track_features_table = Table(
    "sonic_track_features",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("local_track_id", Integer, nullable=False),
    Column("analyzer_key", String, nullable=False),
    Column("analyzer_version", String, nullable=False),
    Column("status", String, nullable=False),
    Column("descriptor_json", JSON, nullable=True),
    Column("vector_json", JSON, nullable=True),
    Column("failure_detail", Text, nullable=True),
    Column("extracted_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint("local_track_id", name="uq_sonic_track_features_local_track_id"),
    Index("ix_sonic_track_features_status", "status"),
    Index("ix_sonic_track_features_analyzer_key", "analyzer_key"),
)

playlist_generation_runs_table = Table(
    "playlist_generation_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("status", String, nullable=False),
    Column("source_filter_json", JSON, nullable=False),
    Column("generation_config_json", JSON, nullable=False),
    Column("playlist_count", Integer, nullable=False, server_default="0"),
    Column("track_count", Integer, nullable=False, server_default="0"),
    Column("error_detail", Text, nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Index("ix_playlist_generation_runs_status", "status"),
    Index("ix_playlist_generation_runs_created_at", "created_at"),
)

generated_playlists_table = Table(
    "generated_playlists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, nullable=False),
    Column("parent_playlist_id", Integer, nullable=True),
    Column("depth", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Column("name", String, nullable=False),
    Column("summary_json", JSON, nullable=False),
    Column("track_count", Integer, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Index("ix_generated_playlists_run_id", "run_id"),
    Index("ix_generated_playlists_parent_playlist_id", "parent_playlist_id"),
)

generated_playlist_tracks_table = Table(
    "generated_playlist_tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("generated_playlist_id", Integer, nullable=False),
    Column("local_track_id", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    UniqueConstraint(
        "generated_playlist_id",
        "local_track_id",
        name="uq_generated_playlist_tracks_playlist_track",
    ),
    Index(
        "ix_generated_playlist_tracks_playlist_position",
        "generated_playlist_id",
        "position",
    ),
    Index("ix_generated_playlist_tracks_local_track_id", "local_track_id"),
)


@dataclass(frozen=True, slots=True)
class SonicTrackFeatureRecord:
    id: int
    local_track_id: int
    analyzer_key: str
    analyzer_version: str
    status: str
    descriptor_json: dict[str, Any] | None
    vector_json: list[float] | None
    failure_detail: str | None
    extracted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SonicFeatureSummaryRecord:
    total_tracks: int
    ready_tracks: int
    pending_tracks: int
    failed_tracks: int
    missing_tracks: int


@dataclass(frozen=True, slots=True)
class PlaylistGenerationRunRecord:
    id: int
    status: str
    source_filter_json: dict[str, Any]
    generation_config_json: dict[str, Any]
    playlist_count: int
    track_count: int
    error_detail: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GeneratedPlaylistRecord:
    id: int
    run_id: int
    parent_playlist_id: int | None
    depth: int
    position: int
    name: str
    summary_json: dict[str, Any]
    track_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GeneratedPlaylistTrackRecord:
    id: int
    local_track_id: int
    position: int
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None
    file_path: str
    library_root_rel_path: str
