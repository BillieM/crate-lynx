from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.local_dedupe.models import (
    LOCAL_DEDUPE_ACTION_DISMISSED,
    LOCAL_DEDUPE_ACTION_RESOLVED,
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT,
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR,
    LOCAL_DEDUPE_SOURCE_ISRC,
    LOCAL_DEDUPE_SOURCE_METADATA,
)


LocalDedupeSource = Literal[
    "fingerprint_exact",
    "fingerprint_similar",
    "isrc",
    "metadata",
]
LocalDedupeLinkStatus = Literal["linked", "pending", "unlinked"]


class LocalDedupeTrackResponse(BaseModel):
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
    link_status: LocalDedupeLinkStatus
    samplerate: int | None
    title: str | None


class LocalDedupeGroupResponse(BaseModel):
    group_key: str
    source: LocalDedupeSource
    match_score: float = Field(ge=0, le=1)
    tracks: list[LocalDedupeTrackResponse]


class LocalDedupeQueueResponse(BaseModel):
    groups: list[LocalDedupeGroupResponse]
    total_count: int


class ResolveLocalDedupeGroupRequest(BaseModel):
    keeper_local_track_id: int


class LocalDedupeDecisionResponse(BaseModel):
    action: Literal["resolved", "dismissed"]
    created_at: datetime
    group_key: str
    id: int
    keeper_local_track_id: int | None
    match_score: float | None
    quarantine_paths: list[str]
    quarantined_local_track_ids: list[int]
    source: LocalDedupeSource
    track_ids: list[int]


class LocalDedupeResolveResponse(BaseModel):
    decision: LocalDedupeDecisionResponse
    affected_playlist_ids: list[int]


def local_dedupe_source_values() -> tuple[str, ...]:
    return (
        LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT,
        LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR,
        LOCAL_DEDUPE_SOURCE_ISRC,
        LOCAL_DEDUPE_SOURCE_METADATA,
    )


def local_dedupe_action_values() -> tuple[str, ...]:
    return (
        LOCAL_DEDUPE_ACTION_RESOLVED,
        LOCAL_DEDUPE_ACTION_DISMISSED,
    )
