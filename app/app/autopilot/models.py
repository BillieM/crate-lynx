from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

AUTOPILOT_TRIGGER_STARTUP = "startup"
AUTOPILOT_TRIGGER_SCHEDULED = "scheduled"
AUTOPILOT_TRIGGER_MANUAL = "manual"
AUTOPILOT_TRIGGERS = (
    AUTOPILOT_TRIGGER_STARTUP,
    AUTOPILOT_TRIGGER_SCHEDULED,
    AUTOPILOT_TRIGGER_MANUAL,
)

AUTOPILOT_RUN_STATUS_PLANNING = "planning"
AUTOPILOT_RUN_STATUS_RUNNING = "running"
AUTOPILOT_RUN_STATUS_SUCCEEDED = "succeeded"
AUTOPILOT_RUN_STATUS_PARTIAL = "partial"
AUTOPILOT_RUN_STATUS_FAILED = "failed"
AUTOPILOT_RUN_STATUS_PAUSED = "paused"
AUTOPILOT_RUN_STATUS_SKIPPED = "skipped"
AUTOPILOT_RUN_STATUSES = (
    AUTOPILOT_RUN_STATUS_PLANNING,
    AUTOPILOT_RUN_STATUS_RUNNING,
    AUTOPILOT_RUN_STATUS_SUCCEEDED,
    AUTOPILOT_RUN_STATUS_PARTIAL,
    AUTOPILOT_RUN_STATUS_FAILED,
    AUTOPILOT_RUN_STATUS_PAUSED,
    AUTOPILOT_RUN_STATUS_SKIPPED,
)

AUTOPILOT_ITEM_STATUS_PLANNED = "planned"
AUTOPILOT_ITEM_STATUS_RUNNING = "running"
AUTOPILOT_ITEM_STATUS_SUCCEEDED = "succeeded"
AUTOPILOT_ITEM_STATUS_SKIPPED = "skipped"
AUTOPILOT_ITEM_STATUS_RETRY_WAIT = "retry_wait"
AUTOPILOT_ITEM_STATUS_REVIEW = "review"
AUTOPILOT_ITEM_STATUS_FAILED = "failed"
AUTOPILOT_ITEM_STATUSES = (
    AUTOPILOT_ITEM_STATUS_PLANNED,
    AUTOPILOT_ITEM_STATUS_RUNNING,
    AUTOPILOT_ITEM_STATUS_SUCCEEDED,
    AUTOPILOT_ITEM_STATUS_SKIPPED,
    AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
    AUTOPILOT_ITEM_STATUS_REVIEW,
    AUTOPILOT_ITEM_STATUS_FAILED,
)

AUTOPILOT_SETTINGS_ID = 1
DEFAULT_SCHEDULE_MINUTES = 60
DEFAULT_QUIET_PERIOD_SECONDS = 15 * 60
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 2
DEFAULT_MAX_DOWNLOADS_PER_RUN = 10
DEFAULT_MAX_SEARCHES_PER_RUN = 25
DEFAULT_MAX_STORAGE_BYTES_PER_RUN = 10 * 1024 * 1024 * 1024
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_SECONDS = 60
DEFAULT_RETRY_MAX_SECONDS = 60 * 60

metadata = MetaData()

autopilot_settings_table = Table(
    "autopilot_settings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("paused", Boolean, nullable=False, server_default=text("false")),
    Column(
        "schedule_minutes",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_SCHEDULE_MINUTES)),
    ),
    Column(
        "quiet_period_seconds",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_QUIET_PERIOD_SECONDS)),
    ),
    Column(
        "max_concurrent_downloads",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_MAX_CONCURRENT_DOWNLOADS)),
    ),
    Column(
        "max_downloads_per_run",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_MAX_DOWNLOADS_PER_RUN)),
    ),
    Column(
        "max_searches_per_run",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_MAX_SEARCHES_PER_RUN)),
    ),
    Column(
        "max_storage_bytes_per_run",
        BigInteger,
        nullable=False,
        server_default=text(str(DEFAULT_MAX_STORAGE_BYTES_PER_RUN)),
    ),
    Column(
        "retry_max_attempts",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_RETRY_MAX_ATTEMPTS)),
    ),
    Column(
        "retry_base_seconds",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_RETRY_BASE_SECONDS)),
    ),
    Column(
        "retry_max_seconds",
        Integer,
        nullable=False,
        server_default=text(str(DEFAULT_RETRY_MAX_SECONDS)),
    ),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint("id = 1", name="singleton"),
    CheckConstraint("schedule_minutes > 0", name="schedule_minutes_positive"),
    CheckConstraint("quiet_period_seconds >= 0", name="quiet_period_nonnegative"),
    CheckConstraint(
        "max_concurrent_downloads > 0", name="max_concurrent_downloads_positive"
    ),
    CheckConstraint(
        "max_downloads_per_run >= 0", name="max_downloads_per_run_nonnegative"
    ),
    CheckConstraint(
        "max_searches_per_run >= 0", name="max_searches_per_run_nonnegative"
    ),
    CheckConstraint(
        "max_storage_bytes_per_run >= 0",
        name="max_storage_bytes_per_run_nonnegative",
    ),
    CheckConstraint("retry_max_attempts > 0", name="retry_max_attempts_positive"),
    CheckConstraint("retry_base_seconds > 0", name="retry_base_seconds_positive"),
    CheckConstraint(
        "retry_max_seconds >= retry_base_seconds",
        name="retry_max_not_below_base",
    ),
)

autopilot_runs_table = Table(
    "autopilot_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("idempotency_key", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("dry_run", Boolean, nullable=False, server_default=text("false")),
    Column(
        "status",
        String,
        nullable=False,
        server_default=text(f"'{AUTOPILOT_RUN_STATUS_PLANNING}'"),
    ),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error_detail", Text, nullable=True),
    Column("refreshed_playlists", Integer, nullable=False, server_default=text("0")),
    Column("searched_tracks", Integer, nullable=False, server_default=text("0")),
    Column("queued_downloads", Integer, nullable=False, server_default=text("0")),
    Column("downloaded_tracks", Integer, nullable=False, server_default=text("0")),
    Column("ingested_tracks", Integer, nullable=False, server_default=text("0")),
    Column("analyzed_tracks", Integer, nullable=False, server_default=text("0")),
    Column("regenerated_recipes", Integer, nullable=False, server_default=text("0")),
    Column("refreshed_exports", Integer, nullable=False, server_default=text("0")),
    Column("review_items", Integer, nullable=False, server_default=text("0")),
    Column("failed_items", Integer, nullable=False, server_default=text("0")),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    CheckConstraint(
        "trigger IN ('startup', 'scheduled', 'manual')",
        name="trigger",
    ),
    CheckConstraint(
        "status IN "
        "('planning', 'running', 'succeeded', 'partial', 'failed', 'paused', "
        "'skipped')",
        name="status",
    ),
    UniqueConstraint("idempotency_key", name="uq_autopilot_runs_idempotency_key"),
    Index("ix_autopilot_runs_status", "status"),
    Index("ix_autopilot_runs_started_at", "started_at"),
)

autopilot_run_items_table = Table(
    "autopilot_run_items",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("stage", String, nullable=False),
    Column("action", String, nullable=False),
    Column(
        "status",
        String,
        nullable=False,
        server_default=text(f"'{AUTOPILOT_ITEM_STATUS_PLANNED}'"),
    ),
    Column("playlist_id", Integer, nullable=True),
    Column("streaming_track_id", Integer, nullable=True),
    Column("acquisition_id", String, nullable=True),
    Column("recipe_id", Integer, nullable=True),
    Column("candidate_id", String, nullable=True),
    Column("attempt_count", Integer, nullable=False, server_default=text("0")),
    Column("next_attempt_at", DateTime(timezone=True), nullable=True),
    Column("identity_confidence", Float, nullable=True),
    Column("version_confidence", Float, nullable=True),
    Column("quality_score", Float, nullable=True),
    Column("runner_up_margin", Float, nullable=True),
    Column("expected_duration_ms", Integer, nullable=True),
    Column("candidate_duration_ms", Integer, nullable=True),
    Column("reason_code", String, nullable=True),
    Column("detail", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column(
        "updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "status IN "
        "('planned', 'running', 'succeeded', 'skipped', 'retry_wait', 'review', "
        "'failed')",
        name="status",
    ),
    CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
    UniqueConstraint("idempotency_key", name="uq_autopilot_run_items_idempotency_key"),
    Index("ix_autopilot_run_items_run_id", "run_id"),
    Index("ix_autopilot_run_items_status", "status"),
    Index("ix_autopilot_run_items_next_attempt_at", "next_attempt_at"),
    Index("ix_autopilot_run_items_playlist_id", "playlist_id"),
    Index("ix_autopilot_run_items_streaming_track_id", "streaming_track_id"),
)


@dataclass(frozen=True, slots=True)
class AutopilotSettingsRecord:
    id: int
    paused: bool
    schedule_minutes: int
    quiet_period_seconds: int
    max_concurrent_downloads: int
    max_downloads_per_run: int
    max_searches_per_run: int
    max_storage_bytes_per_run: int
    retry_max_attempts: int
    retry_base_seconds: int
    retry_max_seconds: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AutopilotRunRecord:
    id: str
    idempotency_key: str
    trigger: str
    dry_run: bool
    status: str
    started_at: datetime
    heartbeat_at: datetime | None
    finished_at: datetime | None
    error_detail: str | None
    refreshed_playlists: int
    searched_tracks: int
    queued_downloads: int
    downloaded_tracks: int
    ingested_tracks: int
    analyzed_tracks: int
    regenerated_recipes: int
    refreshed_exports: int
    review_items: int
    failed_items: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AutopilotRunItemRecord:
    id: str
    run_id: str
    idempotency_key: str
    stage: str
    action: str
    status: str
    playlist_id: int | None
    streaming_track_id: int | None
    acquisition_id: str | None
    recipe_id: int | None
    candidate_id: str | None
    attempt_count: int
    next_attempt_at: datetime | None
    identity_confidence: float | None
    version_confidence: float | None
    quality_score: float | None
    runner_up_margin: float | None
    expected_duration_ms: int | None
    candidate_duration_ms: int | None
    reason_code: str | None
    detail: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
