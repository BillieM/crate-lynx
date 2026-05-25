from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine, get_engine
from app.local_tracks.schemas import RematchUnresolvedLocalTracksResponse
from app.local_tracks.store import local_tracks_table
from app.matching.jobs import (
    LocalTrackRematchBackfillJobEnqueuer,
    MatchingJobEnqueuer,
    UNRESOLVED_LOCAL_TRACK_STATUSES,
)
from app.matching.pipeline import SuggestedLinkStore


def create_router(
    *,
    require_redis_url: Callable[[], str],
    require_database_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: object) -> Engine:
        if isinstance(engine, Engine):
            return engine
        return create_database_engine(
            require_database_url() if require_database_url is not None else None
        )

    @router.post("/local-tracks/{local_track_id}/rematch", status_code=202)
    def rematch_local_track(
        local_track_id: int,
        engine: Engine = Depends(get_engine),
    ) -> dict[str, object]:
        engine = _engine(engine)
        with engine.connect() as connection:
            local_track = connection.execute(
                select(local_tracks_table.c.id).where(
                    local_tracks_table.c.id == local_track_id
                )
            ).scalar_one_or_none()

        if local_track is None:
            raise HTTPException(status_code=404, detail="Local track not found")

        SuggestedLinkStore(engine=engine).clear_non_approved_for_track(local_track_id)
        job_id = MatchingJobEnqueuer(require_redis_url()).enqueue(local_track_id)
        return {
            "local_track_id": local_track_id,
            "job_id": job_id,
        }

    @router.post(
        "/local-tracks/rematch-unresolved",
        response_model=RematchUnresolvedLocalTracksResponse,
        status_code=202,
    )
    def rematch_unresolved_local_tracks() -> RematchUnresolvedLocalTracksResponse:
        job_id = LocalTrackRematchBackfillJobEnqueuer(require_redis_url()).enqueue()
        return RematchUnresolvedLocalTracksResponse(
            job_id=job_id,
            statuses=list(UNRESOLVED_LOCAL_TRACK_STATUSES),
        )

    return router
