from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, select

from app.local_tracks.store import local_tracks_table
from app.matching.jobs import MatchingJobEnqueuer
from app.matching.pipeline import SuggestedLinkStore


def create_router(
    *,
    require_database_url: Callable[[], str],
    require_redis_url: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    @router.post("/local-tracks/{local_track_id}/rematch", status_code=202)
    async def rematch_local_track(local_track_id: int) -> dict[str, object]:
        database_url = require_database_url()
        engine = create_engine(database_url)
        with engine.connect() as connection:
            local_track = connection.execute(
                select(local_tracks_table.c.id).where(
                    local_tracks_table.c.id == local_track_id
                )
            ).scalar_one_or_none()

        if local_track is None:
            raise HTTPException(status_code=404, detail="Local track not found")

        SuggestedLinkStore(database_url).clear_non_approved_for_track(local_track_id)
        job_id = MatchingJobEnqueuer(require_redis_url()).enqueue(local_track_id)
        return {
            "local_track_id": local_track_id,
            "job_id": job_id,
        }

    return router
