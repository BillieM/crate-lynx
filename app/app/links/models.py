from pydantic import BaseModel

from app.matching.models import ConfidenceBand


class ProposalResponse(BaseModel):
    id: int
    local_track_id: int
    local_file_path: str
    local_title: str | None
    local_artist: str | None
    local_album: str | None
    streaming_track_id: int
    streaming_provider_track_id: str
    streaming_title: str
    streaming_artist: str
    streaming_album: str | None
    match_method: str
    score: float
    status: str
    confidence_band: ConfidenceBand
    rejected_at: str | None


class ProposalListResponse(BaseModel):
    proposals: list[ProposalResponse]
    total_count: int
    returned_count: int
    limit: int
    next_cursor: str | None


class ApproveProposalRequest(BaseModel):
    pass


class RejectProposalRequest(BaseModel):
    pass


class CreateFinalLinkRequest(BaseModel):
    local_track_id: int
    streaming_track_id: int
    replace_final_link_id: int | None = None
    detach_conflicting_final_link_ids: list[int] = []


class CreateFinalLinkResponse(BaseModel):
    final_link_id: int
    local_track_id: int
    streaming_track_id: int
    approved_at: str
    status: str
    replaced_final_link_id: int | None
    detached_final_link_ids: list[int]
