from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MetadataFieldResponse(BaseModel):
    key: str
    value: str | None


class StreamingTrackSummaryResponse(BaseModel):
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


class LocalTrackSearchResultResponse(BaseModel):
    id: int
    title: str | None
    artist: str | None
    album: str | None
    file_path: str
    library_root_rel_path: str
    link_status: str
    final_link_id: int | None


class LocalTrackSearchResponse(BaseModel):
    tracks: list[LocalTrackSearchResultResponse]


class RematchUnresolvedLocalTracksResponse(BaseModel):
    job_id: str
    statuses: list[Literal["unlinked", "pending"]]


class LocalTrackFinalLinkResponse(BaseModel):
    id: int
    streaming_track_id: int
    approved_at: datetime
    streaming_track: StreamingTrackSummaryResponse


class LocalTrackSuggestionResponse(BaseModel):
    id: int
    streaming_track_id: int
    match_method: str
    score: float
    status: str
    created_at: datetime
    streaming_track: StreamingTrackSummaryResponse


class LocalTrackFailedIngestionResponse(BaseModel):
    id: int
    source_path: str
    filename: str
    failure_reason: str
    failed_at: datetime


class BeetsItemDetailResponse(BaseModel):
    beets_id: int
    fields: list[MetadataFieldResponse]
    attributes: list[MetadataFieldResponse]


class BeetsAlbumDetailResponse(BaseModel):
    beets_album_id: int
    fields: list[MetadataFieldResponse]
    attributes: list[MetadataFieldResponse]


class LocalTrackDetailResponse(BaseModel):
    id: int
    file_path: str
    library_root_rel_path: str
    fingerprint: str | None
    beets_id: int | None
    created_at: datetime
    updated_at: datetime
    link_status: str
    title: str | None
    artist: str | None
    album: str | None
    duration_ms: int | None
    final_link: LocalTrackFinalLinkResponse | None
    pending_suggestions: list[LocalTrackSuggestionResponse]
    beets_item: BeetsItemDetailResponse | None
    beets_album: BeetsAlbumDetailResponse | None
    failed_ingestion_attempts: list[LocalTrackFailedIngestionResponse]
