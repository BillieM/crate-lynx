from collections.abc import Callable

from fastapi import APIRouter

from app.maintenance.schemas import (
    MissingLocallyResponse,
    MissingLocallyTrackResponse,
)
from app.maintenance.store import MaintenanceStore


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/maintenance/missing-locally", response_model=MissingLocallyResponse)
    async def list_missing_locally() -> MissingLocallyResponse:
        tracks = MaintenanceStore(require_database_url()).list_missing_locally()
        return MissingLocallyResponse(
            tracks=[
                MissingLocallyTrackResponse(
                    id=track.id,
                    provider_track_id=track.provider_track_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_ms=track.duration_ms,
                    playlist_count=track.playlist_count,
                    playlist_titles=track.playlist_titles,
                )
                for track in tracks
            ]
        )

    return router
