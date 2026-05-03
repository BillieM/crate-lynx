from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query
from sqlalchemy import create_engine, func, or_, select

from app.local_tracks.store import local_tracks_table
from app.search.schemas import SearchResponse, SearchResultResponse
from app.streaming.models import (
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/search", response_model=SearchResponse)
    async def search_library(q: str = Query(min_length=1)) -> SearchResponse:
        query = q.strip()
        if not query:
            return SearchResponse(query="", results=[])

        engine = create_engine(require_database_url())
        pattern = f"%{query.lower()}%"
        results: list[SearchResultResponse] = []

        with engine.connect() as connection:
            playlist_rows = connection.execute(
                select(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.title,
                    func.count(playlist_membership_table.c.id).label("track_count"),
                )
                .select_from(
                    streaming_playlists_table.outerjoin(
                        playlist_membership_table,
                        streaming_playlists_table.c.id
                        == playlist_membership_table.c.playlist_id,
                    )
                )
                .where(func.lower(streaming_playlists_table.c.title).like(pattern))
                .group_by(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.title,
                )
                .order_by(streaming_playlists_table.c.title.asc())
                .limit(4)
            ).mappings()
            results.extend(
                SearchResultResponse(
                    kind="playlist",
                    id=row["id"],
                    title=row["title"],
                    subtitle=f"Playlist • {row['track_count']} tracks",
                    route_path="/youtube-music",
                )
                for row in playlist_rows
            )

            streaming_track_rows = connection.execute(
                select(
                    streaming_tracks_table.c.id,
                    streaming_tracks_table.c.title,
                    streaming_tracks_table.c.artist,
                    streaming_tracks_table.c.album,
                )
                .where(
                    or_(
                        func.lower(streaming_tracks_table.c.title).like(pattern),
                        func.lower(streaming_tracks_table.c.artist).like(pattern),
                        func.lower(
                            func.coalesce(streaming_tracks_table.c.album, "")
                        ).like(pattern),
                    )
                )
                .order_by(streaming_tracks_table.c.title.asc())
                .limit(4)
            ).mappings()
            results.extend(
                SearchResultResponse(
                    kind="streaming_track",
                    id=row["id"],
                    title=row["title"],
                    subtitle=" • ".join(
                        part
                        for part in [row["artist"], row["album"] or "YouTube Music"]
                        if part
                    ),
                    route_path="/youtube-music",
                )
                for row in streaming_track_rows
            )

            local_track_rows = connection.execute(
                select(
                    local_tracks_table.c.id,
                    local_tracks_table.c.file_path,
                    local_tracks_table.c.library_root_rel_path,
                )
                .where(
                    or_(
                        func.lower(local_tracks_table.c.file_path).like(pattern),
                        func.lower(local_tracks_table.c.library_root_rel_path).like(
                            pattern
                        ),
                    )
                )
                .order_by(local_tracks_table.c.file_path.asc())
                .limit(4)
            ).mappings()
            results.extend(
                SearchResultResponse(
                    kind="local_track",
                    id=row["id"],
                    title=row["file_path"].rsplit("/", 1)[-1],
                    subtitle=f"Local file • {row['library_root_rel_path']}",
                    route_path="/local-library",
                )
                for row in local_track_rows
            )

        return SearchResponse(query=query, results=results[:12])

    return router
