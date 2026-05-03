from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, select

from app.local_tracks.store import local_tracks_table
from app.matching.jobs import MatchingJobEnqueuer
from app.matching.models import ConfidenceBand
from app.matching.pipeline import suggested_links_table


def create_router(
    *,
    require_database_url: Callable[[], str],
    require_redis_url: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/matching/status")
    async def matching_status() -> dict[str, object]:
        engine = create_engine(require_database_url())
        with engine.connect() as connection:
            suggestions = connection.execute(
                select(
                    suggested_links_table.c.local_track_id,
                    suggested_links_table.c.streaming_track_id,
                    suggested_links_table.c.match_method,
                    suggested_links_table.c.score,
                    suggested_links_table.c.status,
                ).order_by(suggested_links_table.c.id.asc())
            ).mappings()

            return {
                "status": "ok",
                "suggestions": [
                    {
                        **dict(row),
                        "confidence_band": ConfidenceBand.from_score(
                            float(row["score"])
                        ),
                    }
                    for row in suggestions
                ],
            }

    @router.post("/matching/tracks/{local_track_id}/run", status_code=202)
    async def run_matching_for_track(local_track_id: int) -> dict[str, object]:
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

        job_id = MatchingJobEnqueuer(require_redis_url()).enqueue(local_track_id)
        return {
            "local_track_id": local_track_id,
            "job_id": job_id,
        }

    return router
