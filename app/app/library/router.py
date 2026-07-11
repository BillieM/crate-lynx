from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.library.schemas import (
    LibraryStatsResponse,
    LibraryTrackResponse,
    LibraryTracksResponse,
)
from app.library.store import (
    LibraryLinkStatus,
    LibrarySortField,
    LibraryStore,
    SortDirection,
)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/library/tracks", response_model=LibraryTracksResponse)
    def list_library_tracks(
        cursor: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        q: Annotated[str | None, Query(max_length=200)] = None,
        link_status: Annotated[LibraryLinkStatus | None, Query()] = None,
        sort: Annotated[LibrarySortField, Query()] = "id",
        direction: Annotated[SortDirection, Query()] = "asc",
        engine: Engine = Depends(get_engine),
    ) -> LibraryTracksResponse:
        store = LibraryStore(engine=engine)
        stats = store.compute_stats()
        try:
            page = store.list_tracks_page(
                cursor=cursor,
                limit=limit,
                query_text=q,
                link_status=link_status,
                sort=sort,
                direction=direction,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
            filtered_total=page.filtered_total,
            returned_count=len(page.tracks),
            limit=limit,
            next_cursor=page.next_cursor,
        )

    return router
