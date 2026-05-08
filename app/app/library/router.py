from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Query

from app.library.schemas import (
    LibraryStatsResponse,
    LibraryTrackResponse,
    LibraryTracksResponse,
)
from app.library.store import LibraryStore


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/library/tracks", response_model=LibraryTracksResponse)
    async def list_library_tracks(
        cursor: Annotated[int | None, Query(ge=0)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> LibraryTracksResponse:
        store = LibraryStore(require_database_url())
        stats = store.compute_stats()
        page = store.list_tracks_page(cursor=cursor, limit=limit)
        return LibraryTracksResponse(
            stats=LibraryStatsResponse(
                total=stats.total,
                linked=stats.linked,
                pending=stats.pending,
                unlinked=stats.unlinked,
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
                for track in page.tracks
            ],
            next_cursor=page.next_cursor,
        )

    return router
