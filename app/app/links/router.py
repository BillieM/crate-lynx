from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, create_engine, insert, select, update
from sqlalchemy.sql.elements import ColumnElement

from app.links.models import ProposalListResponse, ProposalResponse
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_REJECTED,
    suggested_links_table,
)
from app.streaming.models import streaming_tracks_table


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/proposals", response_model=ProposalListResponse)
    async def list_proposals(
        band: ConfidenceBand | None = None,
    ) -> ProposalListResponse:
        engine = create_engine(require_database_url())
        query = (
            select(
                suggested_links_table.c.id,
                suggested_links_table.c.local_track_id,
                local_tracks_table.c.file_path.label("local_file_path"),
                suggested_links_table.c.streaming_track_id,
                streaming_tracks_table.c.title.label("streaming_title"),
                streaming_tracks_table.c.artist.label("streaming_artist"),
                streaming_tracks_table.c.album.label("streaming_album"),
                suggested_links_table.c.match_method,
                suggested_links_table.c.score,
                suggested_links_table.c.status,
                suggested_links_table.c.rejected_at,
            )
            .select_from(
                suggested_links_table.join(
                    local_tracks_table,
                    local_tracks_table.c.id == suggested_links_table.c.local_track_id,
                ).join(
                    streaming_tracks_table,
                    streaming_tracks_table.c.id
                    == suggested_links_table.c.streaming_track_id,
                )
            )
            .order_by(suggested_links_table.c.id.asc())
        )
        if band is not None:
            query = query.where(_confidence_band_clause(band))

        with engine.connect() as connection:
            rows = connection.execute(query).mappings()
            proposals = [
                ProposalResponse(
                    id=row["id"],
                    local_track_id=row["local_track_id"],
                    local_file_path=row["local_file_path"],
                    streaming_track_id=row["streaming_track_id"],
                    streaming_title=row["streaming_title"],
                    streaming_artist=row["streaming_artist"],
                    streaming_album=row["streaming_album"],
                    match_method=row["match_method"],
                    score=float(row["score"]),
                    status=row["status"],
                    confidence_band=ConfidenceBand.from_score(float(row["score"])),
                    rejected_at=(
                        row["rejected_at"].isoformat()
                        if row["rejected_at"] is not None
                        else None
                    ),
                )
                for row in rows
            ]

        return ProposalListResponse(proposals=proposals)

    @router.post("/proposals/{proposal_id}/approve", status_code=201)
    async def approve_proposal(proposal_id: int) -> dict[str, object]:
        engine = create_engine(require_database_url())

        with engine.begin() as connection:
            proposal = (
                connection.execute(
                    select(
                        suggested_links_table.c.id,
                        suggested_links_table.c.local_track_id,
                        suggested_links_table.c.streaming_track_id,
                    ).where(suggested_links_table.c.id == proposal_id)
                )
                .mappings()
                .one_or_none()
            )

            if proposal is None:
                raise HTTPException(status_code=404, detail="Proposal not found")

            result = connection.execute(
                insert(final_links_table).values(
                    local_track_id=proposal["local_track_id"],
                    streaming_track_id=proposal["streaming_track_id"],
                )
            )
            connection.execute(
                update(suggested_links_table)
                .where(suggested_links_table.c.id == proposal_id)
                .values(status=SUGGESTED_LINK_STATUS_APPROVED)
            )

        final_link_id = result.inserted_primary_key[0]
        if not isinstance(final_link_id, int):
            raise ValueError("Failed to persist final link")

        return {
            "proposal_id": proposal_id,
            "final_link_id": final_link_id,
            "status": SUGGESTED_LINK_STATUS_APPROVED,
        }

    @router.post("/proposals/{proposal_id}/reject")
    async def reject_proposal(proposal_id: int) -> dict[str, object]:
        engine = create_engine(require_database_url())
        rejected_at = datetime.now(UTC)

        with engine.begin() as connection:
            proposal = (
                connection.execute(
                    select(suggested_links_table.c.id).where(
                        suggested_links_table.c.id == proposal_id
                    )
                )
                .mappings()
                .one_or_none()
            )

            if proposal is None:
                raise HTTPException(status_code=404, detail="Proposal not found")

            connection.execute(
                update(suggested_links_table)
                .where(suggested_links_table.c.id == proposal_id)
                .values(
                    status=SUGGESTED_LINK_STATUS_REJECTED,
                    rejected_at=rejected_at,
                )
            )

        return {
            "proposal_id": proposal_id,
            "status": SUGGESTED_LINK_STATUS_REJECTED,
            "rejected_at": rejected_at.isoformat(),
        }

    return router


def _confidence_band_clause(band: ConfidenceBand) -> ColumnElement[bool]:
    if band is ConfidenceBand.HIGH:
        return suggested_links_table.c.score > 0.85
    if band is ConfidenceBand.MEDIUM:
        return and_(
            suggested_links_table.c.score >= 0.5,
            suggested_links_table.c.score <= 0.85,
        )
    return suggested_links_table.c.score < 0.5
