from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.soulseek.models import SOULSEEK_BULK_SEARCH_LIMIT

SoulseekQueueFilter = Literal[
    "all",
    "needs_search",
    "review",
    "active",
    "downloading",
    "failed",
    "linked",
]


class SoulseekStatusResponse(BaseModel):
    configured: bool
    ok: bool
    detail: str | None = None


class SoulseekAcquisitionSummaryResponse(BaseModel):
    id: str
    status: str
    candidate_count: int
    selected_candidate_id: str | None
    slskd_batch_id: str | None
    slskd_transfer_id: str | None = None
    completed_source_path: str | None = None
    slskd_completed_event_id: str | None = None
    job_id: str | None
    enqueue_job_id: str | None
    refresh_job_id: str | None
    local_track_id: int | None = None
    final_link_id: int | None = None
    error_detail: str | None
    link_error_detail: str | None = None


class SoulseekCandidateResponse(BaseModel):
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
    created_at: str


class SoulseekCandidatesResponse(BaseModel):
    acquisition: SoulseekAcquisitionSummaryResponse
    candidates: list[SoulseekCandidateResponse]


class SoulseekSearchResponse(BaseModel):
    acquisition: SoulseekAcquisitionSummaryResponse
    job_id: str


class SoulseekBulkSearchRequest(BaseModel):
    streaming_track_ids: list[int] = Field(
        min_length=1,
        max_length=SOULSEEK_BULK_SEARCH_LIMIT,
    )


class SoulseekBulkSearchItemResponse(BaseModel):
    acquisition: SoulseekAcquisitionSummaryResponse
    job_id: str
    streaming_track_id: int


class SoulseekBulkSearchResponse(BaseModel):
    jobs: list[SoulseekBulkSearchItemResponse]


class SoulseekEnqueueResponse(BaseModel):
    acquisition: SoulseekAcquisitionSummaryResponse
    job_id: str | None = None


class SoulseekRefreshResponse(BaseModel):
    acquisition: SoulseekAcquisitionSummaryResponse
    job_id: str


class SoulseekStreamingTrackResponse(BaseModel):
    id: int
    title: str
    artist: str
    album: str | None
    duration_ms: int | None


class SoulseekAcquisitionDetailResponse(SoulseekAcquisitionSummaryResponse):
    streaming_track_id: int
    search_text: str | None
    fallback_search_text: str | None
    slskd_search_id: str | None
    slskd_fallback_search_id: str | None
    destination: str | None
    searched_at: str | None
    queued_at: str | None
    completed_at: str | None
    ingested_at: str | None
    proposal_available_at: str | None
    linked_at: str | None
    failed_at: str | None
    created_at: str
    updated_at: str


class SoulseekQueueItemResponse(BaseModel):
    acquisition: SoulseekAcquisitionDetailResponse | None
    candidates: list[SoulseekCandidateResponse]
    playlist_count: int
    playlist_ids: list[int]
    playlist_titles: list[str]
    selected_candidate: SoulseekCandidateResponse | None
    streaming_track: SoulseekStreamingTrackResponse


class SoulseekQueueResponse(BaseModel):
    filter: SoulseekQueueFilter
    items: list[SoulseekQueueItemResponse]
    total_count: int


class SlskdTransferEventPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    username: str | None = None
    filename: str | None = None
    size: int | None = None
    state: str | list[str] | None = None


class SlskdDownloadCompleteWebhook(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: str
    version: int | None = None
    local_filename: str = Field(alias="localFilename")
    remote_filename: str | None = Field(default=None, alias="remoteFilename")
    transfer: SlskdTransferEventPayload


class SoulseekWebhookResponse(BaseModel):
    matched: bool
    acquisition: SoulseekAcquisitionSummaryResponse | None = None
