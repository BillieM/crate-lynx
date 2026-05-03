"""Link proposal and approval API package."""

from app.links.models import (
    ApproveProposalRequest,
    ProposalListResponse,
    ProposalResponse,
    RejectProposalRequest,
)

__all__ = [
    "ApproveProposalRequest",
    "ProposalListResponse",
    "ProposalResponse",
    "RejectProposalRequest",
]
