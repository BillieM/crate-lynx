from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)


LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT = "fingerprint_exact"
LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR = "fingerprint_similar"
LOCAL_DEDUPE_SOURCE_ISRC = "isrc"
LOCAL_DEDUPE_SOURCE_METADATA = "metadata"
LOCAL_DEDUPE_SOURCES = (
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT,
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR,
    LOCAL_DEDUPE_SOURCE_ISRC,
    LOCAL_DEDUPE_SOURCE_METADATA,
)

LOCAL_DEDUPE_ACTION_RESOLVED = "resolved"
LOCAL_DEDUPE_ACTION_DISMISSED = "dismissed"
LOCAL_DEDUPE_ACTIONS = (
    LOCAL_DEDUPE_ACTION_RESOLVED,
    LOCAL_DEDUPE_ACTION_DISMISSED,
)

LOCAL_DEDUPE_SIMILAR_FINGERPRINT_THRESHOLD = 0.80
LOCAL_DEDUPE_DURATION_BUCKET_MS = 10_000
LOCAL_DEDUPE_METADATA_DURATION_TOLERANCE_MS = 10_000

metadata = MetaData()

local_dedupe_decisions_table = Table(
    "local_dedupe_decisions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("group_key", String, nullable=False),
    Column("action", String, nullable=False),
    Column("source", String, nullable=False),
    Column("match_score", Float, nullable=True),
    Column("keeper_local_track_id", Integer, nullable=True),
    Column("track_ids_json", JSON, nullable=False),
    Column("quarantined_track_ids_json", JSON, nullable=True),
    Column("quarantine_paths_json", JSON, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint("group_key", name="uq_local_dedupe_decisions_group_key"),
    Index("ix_local_dedupe_decisions_action", "action"),
    Index("ix_local_dedupe_decisions_source", "source"),
)


@dataclass(frozen=True, slots=True)
class LocalDedupeTrackRecord:
    id: int
    album: str | None
    artist: str | None
    beets_id: int | None
    bitdepth: int | None
    bitrate: int | None
    duration_ms: int | None
    file_path: str
    final_link_id: int | None
    fingerprint: str | None
    format: str | None
    isrc: str | None
    library_root_rel_path: str
    link_status: str
    samplerate: int | None
    title: str | None


@dataclass(frozen=True, slots=True)
class LocalDedupeGroupRecord:
    group_key: str
    source: str
    match_score: float
    tracks: list[LocalDedupeTrackRecord]


@dataclass(frozen=True, slots=True)
class LocalDedupeDecisionRecord:
    action: str
    created_at: datetime
    group_key: str
    id: int
    keeper_local_track_id: int | None
    match_score: float | None
    quarantine_paths_json: Any
    quarantined_track_ids_json: Any
    source: str
    track_ids_json: Any
