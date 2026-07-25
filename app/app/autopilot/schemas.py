from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AutopilotTrigger = Literal["startup", "scheduled", "manual"]
AutopilotRunStatus = Literal[
    "planning", "running", "succeeded", "partial", "failed", "paused", "skipped"
]
AutopilotItemStatus = Literal[
    "planned", "running", "succeeded", "skipped", "retry_wait", "review", "failed"
]


class AutopilotSettingsResponse(BaseModel):
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
    created_at: str
    updated_at: str


class UpdateAutopilotSettingsRequest(BaseModel):
    paused: bool | None = None
    schedule_minutes: int | None = Field(default=None, gt=0)
    quiet_period_seconds: int | None = Field(default=None, ge=0)
    max_concurrent_downloads: int | None = Field(default=None, gt=0)
    max_downloads_per_run: int | None = Field(default=None, ge=0)
    max_searches_per_run: int | None = Field(default=None, ge=0)
    max_storage_bytes_per_run: int | None = Field(default=None, ge=0)
    retry_max_attempts: int | None = Field(default=None, gt=0)
    retry_base_seconds: int | None = Field(default=None, gt=0)
    retry_max_seconds: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_update(self) -> UpdateAutopilotSettingsRequest:
        if not self.model_fields_set:
            raise ValueError("At least one autopilot setting must be supplied")
        if (
            self.retry_base_seconds is not None
            and self.retry_max_seconds is not None
            and self.retry_max_seconds < self.retry_base_seconds
        ):
            raise ValueError("retry_max_seconds must be at least retry_base_seconds")
        return self


class StartAutopilotRunRequest(BaseModel):
    dry_run: bool = True


class AutopilotRunItemResponse(BaseModel):
    id: str
    run_id: str
    idempotency_key: str
    stage: str
    action: str
    status: AutopilotItemStatus
    playlist_id: int | None
    streaming_track_id: int | None
    acquisition_id: str | None
    recipe_id: int | None
    candidate_id: str | None
    attempt_count: int
    next_attempt_at: str | None
    identity_confidence: float | None
    version_confidence: float | None
    quality_score: float | None
    runner_up_margin: float | None
    expected_duration_ms: int | None
    candidate_duration_ms: int | None
    reason_code: str | None
    detail: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class AutopilotRunResponse(BaseModel):
    id: str
    idempotency_key: str
    trigger: AutopilotTrigger
    dry_run: bool
    status: AutopilotRunStatus
    started_at: str
    heartbeat_at: str | None
    finished_at: str | None
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
    created_at: str
    updated_at: str


class AutopilotRunsResponse(BaseModel):
    runs: list[AutopilotRunResponse]


class AutopilotRunDetailResponse(AutopilotRunResponse):
    items: list[AutopilotRunItemResponse]


class StartAutopilotRunResponse(BaseModel):
    run: AutopilotRunResponse
    job_id: str
