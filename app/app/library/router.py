from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.library.schemas import (
    LibraryStatsResponse,
    LibraryTrackResponse,
    LibraryTracksResponse,
)
from app.library.store import LibraryStore


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/library/tracks", response_model=LibraryTracksResponse)
    def list_library_tracks(
        cursor: Annotated[int | None, Query(ge=0)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        engine: Engine = Depends(get_engine),
    ) -> LibraryTracksResponse:
        store = LibraryStore(engine=engine)
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
