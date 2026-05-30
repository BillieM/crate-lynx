from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)


SOULSEEK_STATUS_SEARCHING = "searching"
SOULSEEK_STATUS_CANDIDATES_FOUND = "candidates_found"
SOULSEEK_STATUS_NO_CANDIDATES = "no_candidates"
SOULSEEK_STATUS_QUEUED = "queued"
SOULSEEK_STATUS_DOWNLOADING = "downloading"
SOULSEEK_STATUS_COMPLETED = "completed"
SOULSEEK_STATUS_INGESTED = "ingested"
SOULSEEK_STATUS_PROPOSAL_AVAILABLE = "proposal_available"
SOULSEEK_STATUS_LINKED = "linked"
SOULSEEK_STATUS_LINK_FAILED = "link_failed"
SOULSEEK_STATUS_FAILED = "failed"
SOULSEEK_STATUSES = (
    SOULSEEK_STATUS_SEARCHING,
    SOULSEEK_STATUS_CANDIDATES_FOUND,
    SOULSEEK_STATUS_NO_CANDIDATES,
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_STATUS_DOWNLOADING,
    SOULSEEK_STATUS_COMPLETED,
    SOULSEEK_STATUS_INGESTED,
    SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
    SOULSEEK_STATUS_LINKED,
    SOULSEEK_STATUS_LINK_FAILED,
    SOULSEEK_STATUS_FAILED,
)

SOULSEEK_QUEUE_NAME = "soulseek"
SOULSEEK_SEARCH_TIMEOUT_SECONDS = 15
SOULSEEK_BULK_SEARCH_LIMIT = 25

metadata = MetaData()

soulseek_acquisitions_table = Table(
    "soulseek_acquisitions",
    metadata,
    Column("id", String, primary_key=True),
    Column("streaming_track_id", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("search_text", String, nullable=True),
    Column("fallback_search_text", String, nullable=True),
    Column("slskd_search_id", String, nullable=True),
    Column("slskd_fallback_search_id", String, nullable=True),
    Column("candidate_count", Integer, server_default="0", nullable=False),
    Column("selected_candidate_id", String, nullable=True),
    Column("slskd_batch_id", String, nullable=True),
    Column("destination", String, nullable=True),
    Column("completed_source_path", Text, nullable=True),
    Column("slskd_completed_event_id", String, nullable=True),
    Column("local_track_id", Integer, nullable=True),
    Column("final_link_id", Integer, nullable=True),
    Column("job_id", String, nullable=True),
    Column("enqueue_job_id", String, nullable=True),
    Column("refresh_job_id", String, nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("link_error_detail", Text, nullable=True),
    Column("searched_at", DateTime(timezone=True), nullable=True),
    Column("queued_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("ingested_at", DateTime(timezone=True), nullable=True),
    Column("proposal_available_at", DateTime(timezone=True), nullable=True),
    Column("linked_at", DateTime(timezone=True), nullable=True),
    Column("failed_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Index("ix_soulseek_acquisitions_streaming_track_id", "streaming_track_id"),
    Index("ix_soulseek_acquisitions_status", "status"),
    Index("ix_soulseek_acquisitions_local_track_id", "local_track_id"),
    Index("ix_soulseek_acquisitions_completed_source_path", "completed_source_path"),
)

soulseek_candidates_table = Table(
    "soulseek_candidates",
    metadata,
    Column("id", String, primary_key=True),
    Column("acquisition_id", String, nullable=False),
    Column("slskd_search_id", String, nullable=False),
    Column("username", String, nullable=False),
    Column("filename", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("extension", String, nullable=True),
    Column("duration_seconds", Integer, nullable=True),
    Column("bit_rate", Integer, nullable=True),
    Column("bit_depth", Integer, nullable=True),
    Column("sample_rate", Integer, nullable=True),
    Column("is_variable_bit_rate", Boolean, nullable=True),
    Column("has_free_upload_slot", Boolean, nullable=False),
    Column("queue_length", BigInteger, nullable=True),
    Column("upload_speed", Integer, nullable=True),
    Column("score", Float, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Index("ix_soulseek_candidates_acquisition_id", "acquisition_id"),
    Index(
        "ix_soulseek_candidates_acquisition_score",
        "acquisition_id",
        "score",
    ),
)


@dataclass(frozen=True, slots=True)
class StreamingTrackForSoulseek:
    id: int
    title: str
    artist: str
    album: str | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class SoulseekAcquisitionRecord:
    id: str
    streaming_track_id: int
    status: str
    search_text: str | None
    fallback_search_text: str | None
    slskd_search_id: str | None
    slskd_fallback_search_id: str | None
    candidate_count: int
    selected_candidate_id: str | None
    slskd_batch_id: str | None
    destination: str | None
    completed_source_path: str | None
    slskd_completed_event_id: str | None
    local_track_id: int | None
    final_link_id: int | None
    job_id: str | None
    enqueue_job_id: str | None
    refresh_job_id: str | None
    error_detail: str | None
    link_error_detail: str | None
    searched_at: datetime | None
    queued_at: datetime | None
    completed_at: datetime | None
    ingested_at: datetime | None
    proposal_available_at: datetime | None
    linked_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SoulseekCandidateRecord:
    id: str
    acquisition_id: str
    slskd_search_id: str
    username: str
    filename: str
    size: int
    extension: str | None
    duration_seconds: int | None
    bit_rate: int | None
    bit_depth: int | None
    sample_rate: int | None
    is_variable_bit_rate: bool | None
    has_free_upload_slot: bool
    queue_length: int | None
    upload_speed: int | None
    score: float
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MissingTrackSoulseekSummary:
    id: str
    status: str
    candidate_count: int
    selected_candidate_id: str | None
    slskd_batch_id: str | None
    completed_source_path: str | None
    slskd_completed_event_id: str | None
    job_id: str | None
    enqueue_job_id: str | None
    refresh_job_id: str | None
    local_track_id: int | None
    final_link_id: int | None
    error_detail: str | None
    link_error_detail: str | None


@dataclass(frozen=True, slots=True)
class SoulseekQueueItemRecord:
    streaming_track: StreamingTrackForSoulseek
    playlist_count: int
    playlist_ids: list[int]
    playlist_titles: list[str]
    acquisition: SoulseekAcquisitionRecord | None
    candidates: list[SoulseekCandidateRecord]
    selected_candidate: SoulseekCandidateRecord | None


@dataclass(frozen=True, slots=True)
class SoulseekAutoLinkResult:
    acquisition: SoulseekAcquisitionRecord
    affected_playlist_ids: tuple[int, ...]
