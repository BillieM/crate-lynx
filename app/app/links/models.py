from pydantic import BaseModel

from app.matching.models import ConfidenceBand


class ProposalResponse(BaseModel):
    id: int
    local_track_id: int
    local_file_path: str
    streaming_track_id: int
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


class ApproveProposalRequest(BaseModel):
    pass


class RejectProposalRequest(BaseModel):
    pass
