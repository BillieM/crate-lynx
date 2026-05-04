from collections.abc import Callable

from fastapi import APIRouter

from app.library.schemas import LibraryTrackResponse, LibraryTracksResponse
from app.library.store import LibraryStore


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/library/tracks", response_model=LibraryTracksResponse)
    async def list_library_tracks() -> LibraryTracksResponse:
        tracks = LibraryStore(require_database_url()).list_tracks()
        return LibraryTracksResponse(
            tracks=[
                LibraryTrackResponse(
                    id=track.id,
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
                for track in tracks
            ]
        )

    return router
