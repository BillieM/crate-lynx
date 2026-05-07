from collections.abc import Callable

from fastapi import APIRouter

from app.maintenance.schemas import (
    MissingLocallyResponse,
    MissingLocallyTrackResponse,
    UnidentifiedResponse,
    UnidentifiedTrackResponse,
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
                    playlist_ids=track.playlist_ids,
                    playlist_titles=track.playlist_titles,
                )
                for track in tracks
            ]
        )

    @router.get("/maintenance/unidentified", response_model=UnidentifiedResponse)
    async def list_unidentified() -> UnidentifiedResponse:
        tracks = MaintenanceStore(require_database_url()).list_unidentified()
        return UnidentifiedResponse(
            tracks=[
                UnidentifiedTrackResponse(
                    id=track.id,
                    failed_at=track.failed_at,
                    failure_reason=track.failure_reason,
                    filename=track.filename,
                    local_track_id=track.local_track_id,
                    source_path=track.source_path,
                )
                for track in tracks
            ]
        )

    return router
