from collections.abc import Callable

from fastapi import APIRouter

from app.library.schemas import (
    LibraryStatsResponse,
    LibraryTrackResponse,
    LibraryTracksResponse,
)
from app.library.store import LibraryStore


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/library/tracks", response_model=LibraryTracksResponse)
    async def list_library_tracks() -> LibraryTracksResponse:
        result = LibraryStore(require_database_url()).list_tracks()
        return LibraryTracksResponse(
            stats=LibraryStatsResponse(
                total=result.stats.total,
                linked=result.stats.linked,
                pending=result.stats.pending,
                unlinked=result.stats.unlinked,
            ),
            tracks=[
                LibraryTrackResponse(
                    id=track.id,
                    final_link_id=track.final_link_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_ms=track.duration_ms,
                    file_path=track.file_path,
                    library_root_rel_path=track.library_root_rel_path,
                    link_status=track.link_status,
                    match_method=track.match_method,
                    file_status=track.file_status,
                )
                for track in result.tracks
            ],
        )

    return router
