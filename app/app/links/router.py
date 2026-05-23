from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement

from app.core.cursors import decode_score_id_cursor, encode_score_id_cursor
from app.core.db import create_database_engine, get_engine
from app.ingestion.beets_mirror import beets_items_table
from app.links.models import (
    CreateFinalLinkRequest,
    CreateFinalLinkResponse,
    ProposalListResponse,
    ProposalResponse,
)
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
    affected_full_sync_playlist_ids_for_streaming_tracks,
)
from app.relationships.resolver import StreamingRelationshipResolver
from app.streaming.models import streaming_tracks_table


logger = logging.getLogger(__name__)
DEFAULT_PROPOSAL_LIST_LIMIT = 50


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
        cursor: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = DEFAULT_PROPOSAL_LIST_LIMIT,
        engine: Engine = Depends(get_engine),
    ) -> ProposalListResponse:
        engine = _engine(engine)
        base_from = (
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
        filters = [
            suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
            final_links_table.c.id.is_(None),
        ]
        if band is not None:
            filters.append(_confidence_band_clause(band))

        query = (
            select(
                suggested_links_table.c.id,
                suggested_links_table.c.local_track_id,
                local_tracks_table.c.file_path.label("local_file_path"),
                beets_items_table.c.title.label("local_title"),
                beets_items_table.c.artist.label("local_artist"),
                beets_items_table.c.album.label("local_album"),
                suggested_links_table.c.streaming_track_id,
                streaming_tracks_table.c.provider_track_id.label(
                    "streaming_provider_track_id"
                ),
                streaming_tracks_table.c.title.label("streaming_title"),
                streaming_tracks_table.c.artist.label("streaming_artist"),
                streaming_tracks_table.c.album.label("streaming_album"),
                suggested_links_table.c.match_method,
                suggested_links_table.c.score,
                suggested_links_table.c.status,
                suggested_links_table.c.rejected_at,
            )
            .select_from(base_from)
            .where(*filters)
            .order_by(
                suggested_links_table.c.score.desc(),
                suggested_links_table.c.id.asc(),
            )
            .limit(limit + 1)
        )
        if cursor is not None:
            try:
                decoded_cursor = decode_score_id_cursor(cursor)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            query = query.where(
                or_(
                    suggested_links_table.c.score < decoded_cursor.score,
                    and_(
                        suggested_links_table.c.score == decoded_cursor.score,
                        suggested_links_table.c.id > decoded_cursor.row_id,
                    ),
                )
            )

        with engine.connect() as connection:
            total_count = int(
                connection.execute(
                    select(func.count()).select_from(base_from).where(*filters)
                ).scalar_one()
            )
            rows = connection.execute(query).mappings().all()
            page_rows = rows[:limit]
            proposals = [
                ProposalResponse(
                    id=row["id"],
                    local_track_id=row["local_track_id"],
                    local_file_path=row["local_file_path"],
                    local_title=row["local_title"],
                    local_artist=row["local_artist"],
                    local_album=row["local_album"],
                    streaming_track_id=row["streaming_track_id"],
                    streaming_provider_track_id=row["streaming_provider_track_id"],
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
                for row in page_rows
            ]

        next_cursor = (
            encode_score_id_cursor(
                score=float(page_rows[-1]["score"]),
                row_id=int(page_rows[-1]["id"]),
            )
            if len(rows) > limit and page_rows
            else None
        )

        return ProposalListResponse(
            proposals=proposals,
            total_count=total_count,
            returned_count=len(proposals),
            limit=limit,
            next_cursor=next_cursor,
        )

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

    @router.post(
        "/final-links",
        status_code=201,
        response_model=CreateFinalLinkResponse,
    )
    def create_final_link(
        payload: CreateFinalLinkRequest,
        engine: Engine = Depends(get_engine),
    ) -> CreateFinalLinkResponse:
        engine = _engine(engine)
        detach_ids = tuple(sorted(set(payload.detach_conflicting_final_link_ids)))

        with engine.begin() as connection:
            if not _local_track_exists(connection, payload.local_track_id):
                raise HTTPException(status_code=404, detail="Local track not found")
            if not _streaming_track_exists(connection, payload.streaming_track_id):
                raise HTTPException(status_code=404, detail="Streaming track not found")

            existing_local_link = _final_link_for_local_track(
                connection,
                payload.local_track_id,
            )
            if existing_local_link is not None:
                is_same_target = (
                    existing_local_link["streaming_track_id"]
                    == payload.streaming_track_id
                )
                if (
                    payload.replace_final_link_id is not None
                    and payload.replace_final_link_id != existing_local_link["id"]
                ) or (not is_same_target and payload.replace_final_link_id is None):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "reason": "local_track_already_linked",
                            "final_link_id": existing_local_link["id"],
                            "streaming_track_id": existing_local_link[
                                "streaming_track_id"
                            ],
                        },
                    )
            elif payload.replace_final_link_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="replace_final_link_id does not match the local track",
                )

            resolver = StreamingRelationshipResolver(connection)
            target_group_ids = resolver.equivalent_group_track_ids(
                payload.streaming_track_id
            )
            conflicting_links = _conflicting_group_final_links(
                connection,
                target_group_ids,
                local_track_id=payload.local_track_id,
                replacing_final_link_id=payload.replace_final_link_id,
            )
            conflict_ids = {int(row["id"]) for row in conflicting_links}
            unknown_detach_ids = set(detach_ids) - conflict_ids
            if unknown_detach_ids:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "reason": "invalid_detach_conflicts",
                        "final_link_ids": sorted(unknown_detach_ids),
                    },
                )
            missing_detach_ids = conflict_ids - set(detach_ids)
            if missing_detach_ids:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "reason": "streaming_group_already_linked",
                        "conflicting_final_links": [
                            {
                                "final_link_id": row["id"],
                                "local_track_id": row["local_track_id"],
                                "streaming_track_id": row["streaming_track_id"],
                            }
                            for row in conflicting_links
                            if int(row["id"]) in missing_detach_ids
                        ],
                    },
                )
            if (
                existing_local_link is not None
                and existing_local_link["streaming_track_id"]
                == payload.streaming_track_id
                and not detach_ids
            ):
                return CreateFinalLinkResponse(
                    final_link_id=existing_local_link["id"],
                    local_track_id=payload.local_track_id,
                    streaming_track_id=payload.streaming_track_id,
                    approved_at=_isoformat(existing_local_link["approved_at"]),
                    status=SUGGESTED_LINK_STATUS_APPROVED,
                    replaced_final_link_id=None,
                    detached_final_link_ids=[],
                )

            affected_track_ids = set(target_group_ids)
            replaced_final_link_id = None
            if existing_local_link is not None:
                replaced_final_link_id = int(existing_local_link["id"])
                affected_track_ids.update(
                    resolver.equivalent_group_track_ids(
                        int(existing_local_link["streaming_track_id"])
                    )
                )
                connection.execute(
                    delete(final_links_table).where(
                        final_links_table.c.id == existing_local_link["id"]
                    )
                )
            if detach_ids:
                detached_rows = (
                    connection.execute(
                        select(final_links_table.c.streaming_track_id).where(
                            final_links_table.c.id.in_(detach_ids)
                        )
                    )
                    .mappings()
                    .all()
                )
                for row in detached_rows:
                    affected_track_ids.update(
                        resolver.equivalent_group_track_ids(
                            int(row["streaming_track_id"])
                        )
                    )
                connection.execute(
                    delete(final_links_table).where(
                        final_links_table.c.id.in_(detach_ids)
                    )
                )

            result = connection.execute(
                insert(final_links_table).values(
                    local_track_id=payload.local_track_id,
                    streaming_track_id=payload.streaming_track_id,
                )
            )
            final_link_id = result.inserted_primary_key[0]
            if not isinstance(final_link_id, int):
                raise ValueError("Failed to persist final link")

            approved_at = (
                connection.execute(
                    select(final_links_table.c.approved_at).where(
                        final_links_table.c.id == final_link_id
                    )
                )
                .scalars()
                .one()
            )
            connection.execute(
                insert(suggested_links_table).values(
                    local_track_id=payload.local_track_id,
                    streaming_track_id=payload.streaming_track_id,
                    match_method="manual",
                    score=1.0,
                    status=SUGGESTED_LINK_STATUS_APPROVED,
                )
            )
            connection.execute(
                delete(suggested_links_table).where(
                    suggested_links_table.c.local_track_id == payload.local_track_id,
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                )
            )
            affected_playlist_ids = (
                affected_full_sync_playlist_ids_for_streaming_tracks(
                    connection,
                    affected_track_ids,
                )
            )
            m3u_redis_url = _m3u_redis_url(affected_playlist_ids)

        _enqueue_m3u_regeneration(affected_playlist_ids, m3u_redis_url)

        return CreateFinalLinkResponse(
            final_link_id=final_link_id,
            local_track_id=payload.local_track_id,
            streaming_track_id=payload.streaming_track_id,
            approved_at=_isoformat(approved_at),
            status=SUGGESTED_LINK_STATUS_APPROVED,
            replaced_final_link_id=replaced_final_link_id,
            detached_final_link_ids=list(detach_ids),
        )

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


def _local_track_exists(connection, local_track_id: int) -> bool:
    return (
        connection.execute(
            select(local_tracks_table.c.id).where(
                local_tracks_table.c.id == local_track_id
            )
        ).scalar_one_or_none()
        is not None
    )


def _streaming_track_exists(connection, streaming_track_id: int) -> bool:
    return (
        connection.execute(
            select(streaming_tracks_table.c.id).where(
                streaming_tracks_table.c.id == streaming_track_id
            )
        ).scalar_one_or_none()
        is not None
    )


def _final_link_for_local_track(connection, local_track_id: int):
    return (
        connection.execute(
            select(
                final_links_table.c.id,
                final_links_table.c.local_track_id,
                final_links_table.c.streaming_track_id,
                final_links_table.c.approved_at,
            ).where(final_links_table.c.local_track_id == local_track_id)
        )
        .mappings()
        .one_or_none()
    )


def _conflicting_group_final_links(
    connection,
    streaming_track_ids: tuple[int, ...],
    *,
    local_track_id: int,
    replacing_final_link_id: int | None,
):
    rows = (
        connection.execute(
            select(
                final_links_table.c.id,
                final_links_table.c.local_track_id,
                final_links_table.c.streaming_track_id,
            )
            .where(final_links_table.c.streaming_track_id.in_(streaming_track_ids))
            .order_by(final_links_table.c.id.asc())
        )
        .mappings()
        .all()
    )
    return [
        row
        for row in rows
        if row["local_track_id"] != local_track_id
        and row["id"] != replacing_final_link_id
    ]


def _isoformat(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
