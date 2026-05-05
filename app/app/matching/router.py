from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.local_tracks.store import local_tracks_table
from app.matching.jobs import MatchingJobEnqueuer
from app.matching.pipeline import SuggestedLinkStore


def create_router(
    *,
    require_database_url: Callable[[], str],
    require_database_engine: Callable[[], Engine] | None = None,
    require_redis_url: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: Engine | None) -> Engine:
        if isinstance(engine, Engine):
            return engine
        if require_database_engine is not None:
            return require_database_engine()
        from sqlalchemy import create_engine

        return create_engine(require_database_url())

    @router.post("/local-tracks/{local_track_id}/rematch", status_code=202)
    def rematch_local_track(
        local_track_id: int,
        engine: object = Depends(require_database_engine)
        if require_database_engine is not None
        else None,
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

    return router
