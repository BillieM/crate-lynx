from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import and_, create_engine, func, select

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
class LibraryTracksResult:
    stats: LibraryStatsRecord
    tracks: list[LibraryTrackRecord]


class LibraryStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def list_tracks(self) -> LibraryTracksResult:
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
        )

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings()
            tracks = [
                LibraryTrackRecord(
                    id=row["id"],
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
            return LibraryTracksResult(stats=_library_stats(tracks), tracks=tracks)


def _display_filename(path: str) -> str:
    return PurePath(path).name


def _link_status(row: object) -> str:
    if row["final_link_id"] is not None:
        return "linked"
    if row["pending_suggestion_id"] is not None:
        return "pending"
    return "unlinked"


def _library_stats(tracks: list[LibraryTrackRecord]) -> LibraryStatsRecord:
    linked = sum(1 for track in tracks if track.link_status == "linked")
    pending = sum(1 for track in tracks if track.link_status == "pending")
    unlinked = sum(1 for track in tracks if track.link_status == "unlinked")
    return LibraryStatsRecord(
        total=len(tracks),
        linked=linked,
        pending=pending,
        unlinked=unlinked,
    )
