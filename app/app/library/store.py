from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import and_, case, func, select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_PENDING,
    suggested_links_table,
)
from app.streaming.models import streaming_tracks_table


@dataclass(frozen=True, slots=True)
class LibraryTrackRecord:
    id: int
    final_link_id: int | None
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None
    file_path: str
    library_root_rel_path: str
    link_status: str
    match_method: str | None
    file_status: str


@dataclass(frozen=True, slots=True)
class LibraryStatsRecord:
    total: int
    linked: int
    pending: int
    unlinked: int


@dataclass(frozen=True, slots=True)
class LibraryTracksPage:
    tracks: list[LibraryTrackRecord]
    next_cursor: int | None


class LibraryStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def list_tracks_page(
        self,
        *,
        cursor: int | None = None,
        limit: int = 100,
    ) -> LibraryTracksPage:
        pending_suggestion_ids = (
            select(
                suggested_links_table.c.local_track_id,
                func.min(suggested_links_table.c.id).label("suggestion_id"),
            )
            .where(suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING)
            .group_by(suggested_links_table.c.local_track_id)
            .subquery()
        )
        approved_suggestion_ids = (
            select(
                suggested_links_table.c.local_track_id,
                suggested_links_table.c.streaming_track_id,
                func.min(suggested_links_table.c.id).label("suggestion_id"),
            )
            .where(suggested_links_table.c.status == SUGGESTED_LINK_STATUS_APPROVED)
            .group_by(
                suggested_links_table.c.local_track_id,
                suggested_links_table.c.streaming_track_id,
            )
            .subquery()
        )
        pending_suggestion = suggested_links_table.alias("pending_suggestion")
        approved_suggestion = suggested_links_table.alias("approved_suggestion")
        pending_streaming_track = streaming_tracks_table.alias(
            "pending_streaming_track"
        )
        final_streaming_track = streaming_tracks_table.alias("final_streaming_track")

        query = (
            select(
                local_tracks_table.c.id,
                local_tracks_table.c.file_path,
                local_tracks_table.c.library_root_rel_path,
                final_links_table.c.id.label("final_link_id"),
                final_streaming_track.c.title.label("final_title"),
                final_streaming_track.c.artist.label("final_artist"),
                final_streaming_track.c.album.label("final_album"),
                final_streaming_track.c.duration_ms.label("final_duration_ms"),
                approved_suggestion.c.match_method.label("approved_match_method"),
                pending_suggestion.c.id.label("pending_suggestion_id"),
                pending_streaming_track.c.title.label("pending_title"),
                pending_streaming_track.c.artist.label("pending_artist"),
                pending_streaming_track.c.album.label("pending_album"),
                pending_streaming_track.c.duration_ms.label("pending_duration_ms"),
                pending_suggestion.c.match_method.label("pending_match_method"),
            )
            .select_from(
                local_tracks_table.outerjoin(
                    final_links_table,
                    final_links_table.c.local_track_id == local_tracks_table.c.id,
                )
                .outerjoin(
                    final_streaming_track,
                    final_streaming_track.c.id
                    == final_links_table.c.streaming_track_id,
                )
                .outerjoin(
                    approved_suggestion_ids,
                    and_(
                        approved_suggestion_ids.c.local_track_id
                        == final_links_table.c.local_track_id,
                        approved_suggestion_ids.c.streaming_track_id
                        == final_links_table.c.streaming_track_id,
                    ),
                )
                .outerjoin(
                    approved_suggestion,
                    approved_suggestion.c.id == approved_suggestion_ids.c.suggestion_id,
                )
                .outerjoin(
                    pending_suggestion_ids,
                    pending_suggestion_ids.c.local_track_id == local_tracks_table.c.id,
                )
                .outerjoin(
                    pending_suggestion,
                    pending_suggestion.c.id == pending_suggestion_ids.c.suggestion_id,
                )
                .outerjoin(
                    pending_streaming_track,
                    pending_streaming_track.c.id
                    == pending_suggestion.c.streaming_track_id,
                )
            )
            .order_by(local_tracks_table.c.id.asc())
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(local_tracks_table.c.id > cursor)

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings()
            tracks = [
                LibraryTrackRecord(
                    id=row["id"],
                    final_link_id=row["final_link_id"],
                    title=(
                        row["final_title"]
                        or row["pending_title"]
                        or _display_filename(row["library_root_rel_path"])
                    ),
                    artist=row["final_artist"] or row["pending_artist"],
                    album=row["final_album"] or row["pending_album"],
                    duration_ms=row["final_duration_ms"] or row["pending_duration_ms"],
                    file_path=row["file_path"],
                    library_root_rel_path=row["library_root_rel_path"],
                    link_status=_link_status(row),
                    match_method=(
                        row["approved_match_method"]
                        if row["final_link_id"] is not None
                        else row["pending_match_method"]
                    ),
                    file_status="available",
                )
                for row in rows
            ]
            next_cursor = tracks[limit - 1].id if len(tracks) > limit else None
            return LibraryTracksPage(tracks=tracks[:limit], next_cursor=next_cursor)

    def compute_stats(self) -> LibraryStatsRecord:
        pending_suggestion_ids = (
            select(
                suggested_links_table.c.local_track_id,
                func.min(suggested_links_table.c.id).label("suggestion_id"),
            )
            .where(suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING)
            .group_by(suggested_links_table.c.local_track_id)
            .subquery()
        )
        linked_case = case((final_links_table.c.id.is_not(None), 1), else_=0)
        pending_case = case(
            (
                and_(
                    final_links_table.c.id.is_(None),
                    pending_suggestion_ids.c.suggestion_id.is_not(None),
                ),
                1,
            ),
            else_=0,
        )
        query = select(
            func.count(local_tracks_table.c.id).label("total"),
            func.sum(linked_case).label("linked"),
            func.sum(pending_case).label("pending"),
        ).select_from(
            local_tracks_table.outerjoin(
                final_links_table,
                final_links_table.c.local_track_id == local_tracks_table.c.id,
            ).outerjoin(
                pending_suggestion_ids,
                pending_suggestion_ids.c.local_track_id == local_tracks_table.c.id,
            )
        )

        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one()

        total = int(row["total"] or 0)
        linked = int(row["linked"] or 0)
        pending = int(row["pending"] or 0)
        return LibraryStatsRecord(
            total=total,
            linked=linked,
            pending=pending,
            unlinked=total - linked - pending,
        )


def _display_filename(path: str) -> str:
    return PurePath(path).name


def _link_status(row: object) -> str:
    if row["final_link_id"] is not None:
        return "linked"
    if row["pending_suggestion_id"] is not None:
        return "pending"
    return "unlinked"
