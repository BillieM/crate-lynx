from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement

from app.core.db import create_database_engine, get_engine
from app.ingestion.beets_mirror import beets_items_table
from app.links.models import ProposalListResponse, ProposalResponse
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_PENDING,
    SUGGESTED_LINK_STATUS_REJECTED,
    SuggestedLinkStore,
    suggested_links_table,
)
from app.m3u.jobs import (
    M3uRegenerationJobEnqueuer,
    affected_full_sync_playlist_ids_for_streaming_track,
)
from app.streaming.models import streaming_tracks_table


logger = logging.getLogger(__name__)


def create_router(
    *,
    require_redis_url: Callable[[], str] | None = None,
    require_database_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: object) -> Engine:
        if isinstance(engine, Engine):
            return engine
        return create_database_engine(
            require_database_url() if require_database_url is not None else None
        )

    def _m3u_redis_url(playlist_ids: tuple[int, ...]) -> str | None:
        if not playlist_ids:
            return None

        redis_url = (
            require_redis_url()
            if require_redis_url is not None
            else os.environ.get("REDIS_URL")
        )
        if not redis_url:
            logger.warning(
                "REDIS_URL is not configured; skipping M3U regeneration for "
                "playlist_ids=%s",
                playlist_ids,
            )
            return None

        return redis_url

    def _enqueue_m3u_regeneration(
        playlist_ids: tuple[int, ...],
        redis_url: str | None,
    ) -> None:
        if not playlist_ids or redis_url is None:
            return

        M3uRegenerationJobEnqueuer(redis_url).enqueue_playlists(playlist_ids)

    @router.get("/proposals", response_model=ProposalListResponse)
    def list_proposals(
        band: ConfidenceBand | None = None,
        engine: Engine = Depends(get_engine),
    ) -> ProposalListResponse:
        engine = _engine(engine)
        query = (
            select(
                suggested_links_table.c.id,
                suggested_links_table.c.local_track_id,
                local_tracks_table.c.file_path.label("local_file_path"),
                beets_items_table.c.title.label("local_title"),
                beets_items_table.c.artist.label("local_artist"),
                beets_items_table.c.album.label("local_album"),
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
                )
                .outerjoin(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
                .join(
                    streaming_tracks_table,
                    streaming_tracks_table.c.id
                    == suggested_links_table.c.streaming_track_id,
                )
                .outerjoin(
                    final_links_table,
                    final_links_table.c.local_track_id
                    == suggested_links_table.c.local_track_id,
                )
            )
            .where(
                suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                final_links_table.c.id.is_(None),
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
                    local_title=row["local_title"],
                    local_artist=row["local_artist"],
                    local_album=row["local_album"],
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
    def approve_proposal(
        proposal_id: int,
        engine: Engine = Depends(get_engine),
    ) -> dict[str, object]:
        engine = _engine(engine)
        suggestion_store = SuggestedLinkStore(engine=engine)

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

            if suggestion_store.has_rejected_pair(
                proposal["local_track_id"],
                proposal["streaming_track_id"],
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Rejected pair cannot be approved",
                )

            existing_final_link = (
                connection.execute(
                    select(final_links_table.c.id).where(
                        final_links_table.c.local_track_id == proposal["local_track_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing_final_link is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Track already has an approved link",
                )

            affected_playlist_ids = affected_full_sync_playlist_ids_for_streaming_track(
                connection,
                proposal["streaming_track_id"],
            )
            m3u_redis_url = _m3u_redis_url(affected_playlist_ids)

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
            connection.execute(
                delete(suggested_links_table).where(
                    suggested_links_table.c.local_track_id
                    == proposal["local_track_id"],
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                    suggested_links_table.c.id != proposal_id,
                )
            )

        _enqueue_m3u_regeneration(affected_playlist_ids, m3u_redis_url)

        final_link_id = result.inserted_primary_key[0]
        if not isinstance(final_link_id, int):
            raise ValueError("Failed to persist final link")

        return {
            "proposal_id": proposal_id,
            "final_link_id": final_link_id,
            "status": SUGGESTED_LINK_STATUS_APPROVED,
        }

    @router.post("/proposals/{proposal_id}/reject")
    def reject_proposal(
        proposal_id: int,
        engine: Engine = Depends(get_engine),
    ) -> dict[str, object]:
        engine = _engine(engine)
        rejected_at = datetime.now(UTC)

        with engine.begin() as connection:
            proposal = (
                connection.execute(
                    select(
                        suggested_links_table.c.id,
                        suggested_links_table.c.streaming_track_id,
                    ).where(suggested_links_table.c.id == proposal_id)
                )
                .mappings()
                .one_or_none()
            )

            if proposal is None:
                raise HTTPException(status_code=404, detail="Proposal not found")

            affected_playlist_ids = affected_full_sync_playlist_ids_for_streaming_track(
                connection,
                proposal["streaming_track_id"],
            )
            m3u_redis_url = _m3u_redis_url(affected_playlist_ids)

            connection.execute(
                update(suggested_links_table)
                .where(suggested_links_table.c.id == proposal_id)
                .values(
                    status=SUGGESTED_LINK_STATUS_REJECTED,
                    rejected_at=rejected_at,
                )
            )

        _enqueue_m3u_regeneration(affected_playlist_ids, m3u_redis_url)

        return {
            "proposal_id": proposal_id,
            "status": SUGGESTED_LINK_STATUS_REJECTED,
            "rejected_at": rejected_at.isoformat(),
        }

    @router.delete("/final-links/{final_link_id}")
    def break_final_link(
        final_link_id: int,
        engine: Engine = Depends(get_engine),
    ) -> dict[str, object]:
        engine = _engine(engine)
        rejected_at = datetime.now(UTC)

        with engine.begin() as connection:
            final_link = (
                connection.execute(
                    select(
                        final_links_table.c.id,
                        final_links_table.c.local_track_id,
                        final_links_table.c.streaming_track_id,
                    ).where(final_links_table.c.id == final_link_id)
                )
                .mappings()
                .one_or_none()
            )

            if final_link is None:
                raise HTTPException(status_code=404, detail="Final link not found")

            affected_playlist_ids = affected_full_sync_playlist_ids_for_streaming_track(
                connection,
                final_link["streaming_track_id"],
            )
            m3u_redis_url = _m3u_redis_url(affected_playlist_ids)

            connection.execute(
                delete(final_links_table).where(final_links_table.c.id == final_link_id)
            )
            rejected_suggestion = connection.execute(
                insert(suggested_links_table).values(
                    local_track_id=final_link["local_track_id"],
                    streaming_track_id=final_link["streaming_track_id"],
                    match_method="manual_break",
                    score=0.0,
                    status=SUGGESTED_LINK_STATUS_REJECTED,
                    rejected_at=rejected_at,
                )
            )

        _enqueue_m3u_regeneration(affected_playlist_ids, m3u_redis_url)

        rejected_suggestion_id = rejected_suggestion.inserted_primary_key[0]
        if not isinstance(rejected_suggestion_id, int):
            raise ValueError("Failed to persist rejected suggestion")

        return {
            "final_link_id": final_link_id,
            "rejected_suggestion_id": rejected_suggestion_id,
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
