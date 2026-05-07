from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LocalTrackFinalLinkResponse(BaseModel):
    id: int
    streaming_track_id: int
    approved_at: datetime


class LocalTrackSuggestionResponse(BaseModel):
    id: int
    streaming_track_id: int
    match_method: str
    score: float
    status: str
    created_at: datetime


class LocalTrackFailedIngestionResponse(BaseModel):
    id: int
    source_path: str
    filename: str
    failure_reason: str
    failed_at: datetime


class LocalTrackDetailResponse(BaseModel):
    id: int
    file_path: str
    library_root_rel_path: str
    link_status: str
    final_link: LocalTrackFinalLinkResponse | None
    pending_suggestions: list[LocalTrackSuggestionResponse]
    failed_ingestion_attempts: list[LocalTrackFailedIngestionResponse]
