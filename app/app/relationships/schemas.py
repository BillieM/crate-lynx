from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


StreamingRelationshipType = Literal["equivalent", "related"]
StreamingRelationshipSuggestionStatus = Literal["pending", "accepted", "rejected"]
StreamingRelationshipConflictState = Literal["none", "different_local_links"]
StreamingRelationshipResolutionSource = Literal["direct", "equivalent"]


class StreamingRelationshipTrackResponse(BaseModel):
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


class StreamingRelationshipLocalLinkResponse(BaseModel):
    final_link_id: int
    local_track_id: int
    local_file_path: str | None
    local_title: str | None
    local_artist: str | None
    local_album: str | None
    streaming_track_id: int
    source_streaming_track_id: int
    resolution_source: StreamingRelationshipResolutionSource
    approved_at: str


class StreamingRelationshipConflictResponse(BaseModel):
    first_group_track_ids: list[int]
    second_group_track_ids: list[int]
    local_track_ids: list[int]
    final_links: list[StreamingRelationshipLocalLinkResponse]


class StreamingRelationshipSuggestionResponse(BaseModel):
    id: int
    relationship_type: StreamingRelationshipType
    match_method: str
    score: float
    confidence: str
    status: StreamingRelationshipSuggestionStatus
    created_at: str
    first_track: StreamingRelationshipTrackResponse
    second_track: StreamingRelationshipTrackResponse
    first_link: StreamingRelationshipLocalLinkResponse | None
    second_link: StreamingRelationshipLocalLinkResponse | None
    conflict_state: StreamingRelationshipConflictState
    conflict: StreamingRelationshipConflictResponse | None


class StreamingRelationshipSuggestionListResponse(BaseModel):
    suggestions: list[StreamingRelationshipSuggestionResponse]
    total_count: int
    returned_count: int
    limit: int


class AcceptStreamingRelationshipSuggestionRequest(BaseModel):
    relationship_type: StreamingRelationshipType | None = None
    winning_final_link_id: int | None = None


class AcceptStreamingRelationshipSuggestionResponse(BaseModel):
    suggestion_id: int
    relationship_id: int
    relationship_type: StreamingRelationshipType
    status: Literal["accepted"]
    accepted_at: str
    detached_final_link_ids: list[int]


class RejectStreamingRelationshipSuggestionResponse(BaseModel):
    suggestion_id: int
    status: Literal["rejected"]
    rejected_at: str


class GenerateStreamingRelationshipSuggestionsResponse(BaseModel):
    created_count: int
    pruned_count: int


class CreateStreamingRelationshipRequest(BaseModel):
    first_track_id: int
    second_track_id: int
    relationship_type: StreamingRelationshipType
    winning_final_link_id: int | None = None


class UpdateStreamingRelationshipRequest(BaseModel):
    relationship_type: StreamingRelationshipType
    winning_final_link_id: int | None = None


class StreamingRelationshipMutationResponse(BaseModel):
    relationship_id: int
    relationship_type: StreamingRelationshipType
    status: Literal["created", "updated", "deleted"]
    accepted_at: str | None
    detached_final_link_ids: list[int]
