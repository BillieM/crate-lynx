"""Link proposal and approval API package."""

from app.links.models import (
    ApproveProposalRequest,
    ProposalListResponse,
    ProposalResponse,
    RejectProposalRequest,
)
from app.links.router import create_router

__all__ = [
    "ApproveProposalRequest",
    "ProposalListResponse",
    "ProposalResponse",
    "RejectProposalRequest",
    "create_router",
]
