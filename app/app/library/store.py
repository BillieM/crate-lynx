from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import json
from pathlib import PurePath
from typing import Literal

from sqlalchemy import String, and_, case, cast, func, or_, select
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


LibraryLinkStatus = Literal["linked", "pending", "unlinked"]
LibrarySortField = Literal[
    "id", "title", "artist", "album", "duration_ms", "link_status"
]
SortDirection = Literal["asc", "desc"]


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
    filtered_total: int
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class _LibraryCursor:
    sort: LibrarySortField
    direction: SortDirection
    value: str | int
    row_id: int


class LibraryStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def list_tracks_page(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
        query_text: str | None = None,
        link_status: LibraryLinkStatus | None = None,
        sort: LibrarySortField = "id",
        direction: SortDirection = "asc",
    ) -> LibraryTracksPage:
        rows_table = _library_rows_query().subquery("library_rows")
        filtered_query = select(rows_table)
        filters = []
        normalized_query = query_text.strip() if query_text else ""
        if normalized_query:
            pattern = f"%{normalized_query}%"
            filters.append(
                or_(
                    rows_table.c.title_sort.ilike(pattern),
                    rows_table.c.artist_sort.ilike(pattern),
                    rows_table.c.album_sort.ilike(pattern),
                    rows_table.c.file_path.ilike(pattern),
                    rows_table.c.library_root_rel_path.ilike(pattern),
                )
            )
        if link_status is not None:
            filters.append(rows_table.c.link_status == link_status)
        if filters:
            filtered_query = filtered_query.where(*filters)

        sort_column = getattr(rows_table.c, f"{sort}_sort")
        decoded_cursor = _decode_cursor(cursor) if cursor is not None else None
        if decoded_cursor is not None:
            if decoded_cursor.sort != sort or decoded_cursor.direction != direction:
                raise ValueError("Library cursor does not match the requested sort")
            value_clause = (
                sort_column > decoded_cursor.value
                if direction == "asc"
                else sort_column < decoded_cursor.value
            )
            filtered_query = filtered_query.where(
                or_(
                    value_clause,
                    and_(
                        sort_column == decoded_cursor.value,
                        rows_table.c.id > decoded_cursor.row_id,
                    ),
                )
            )

        order_clause = sort_column.asc() if direction == "asc" else sort_column.desc()
        page_query = filtered_query.order_by(order_clause, rows_table.c.id.asc()).limit(
            limit + 1
        )
        count_query = select(func.count()).select_from(rows_table)
        if filters:
            count_query = count_query.where(*filters)

        with self._engine.connect() as connection:
            filtered_total = int(connection.execute(count_query).scalar_one())
            rows = connection.execute(page_query).mappings().all()

        page_rows = rows[:limit]
        tracks = [_record_from_row(row) for row in page_rows]
        next_cursor = None
        if len(rows) > limit and page_rows:
            last_row = page_rows[-1]
            next_cursor = _encode_cursor(
                _LibraryCursor(
                    sort=sort,
                    direction=direction,
                    value=last_row[f"{sort}_sort"],
                    row_id=int(last_row["id"]),
                )
            )
        return LibraryTracksPage(
            tracks=tracks,
            filtered_total=filtered_total,
            next_cursor=next_cursor,
        )

    def compute_stats(self) -> LibraryStatsRecord:
        rows_table = _library_rows_query().subquery("library_stats_rows")
        query = select(
            func.count(rows_table.c.id).label("total"),
            func.sum(case((rows_table.c.link_status == "linked", 1), else_=0)).label(
                "linked"
            ),
            func.sum(case((rows_table.c.link_status == "pending", 1), else_=0)).label(
                "pending"
            ),
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


def _library_rows_query():
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
    pending_streaming_track = streaming_tracks_table.alias("pending_streaming_track")
    final_streaming_track = streaming_tracks_table.alias("final_streaming_track")
    link_status = case(
        (final_links_table.c.id.is_not(None), "linked"),
        (pending_suggestion.c.id.is_not(None), "pending"),
        else_="unlinked",
    )
    title_sort = func.lower(
        func.coalesce(
            final_streaming_track.c.title,
            pending_streaming_track.c.title,
            local_tracks_table.c.library_root_rel_path,
            "",
        )
    )
    artist_sort = func.lower(
        func.coalesce(
            final_streaming_track.c.artist,
            pending_streaming_track.c.artist,
            "",
        )
    )
    album_sort = func.lower(
        func.coalesce(
            final_streaming_track.c.album,
            pending_streaming_track.c.album,
            "",
        )
    )
    duration_sort = func.coalesce(
        final_streaming_track.c.duration_ms,
        pending_streaming_track.c.duration_ms,
        -1,
    )
    return select(
        local_tracks_table.c.id,
        local_tracks_table.c.id.label("id_sort"),
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
        link_status.label("link_status"),
        cast(link_status, String).label("link_status_sort"),
        title_sort.label("title_sort"),
        artist_sort.label("artist_sort"),
        album_sort.label("album_sort"),
        duration_sort.label("duration_ms_sort"),
    ).select_from(
        local_tracks_table.outerjoin(
            final_links_table,
            final_links_table.c.local_track_id == local_tracks_table.c.id,
        )
        .outerjoin(
            final_streaming_track,
            final_streaming_track.c.id == final_links_table.c.streaming_track_id,
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
            pending_streaming_track.c.id == pending_suggestion.c.streaming_track_id,
        )
    )


def _record_from_row(row) -> LibraryTrackRecord:
    return LibraryTrackRecord(
        id=int(row["id"]),
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
        link_status=row["link_status"],
        match_method=(
            row["approved_match_method"]
            if row["final_link_id"] is not None
            else row["pending_match_method"]
        ),
        file_status="available",
    )


def _display_filename(path: str) -> str:
    return PurePath(path).name


def _encode_cursor(cursor: _LibraryCursor) -> str:
    payload = json.dumps(
        {
            "direction": cursor.direction,
            "id": cursor.row_id,
            "sort": cursor.sort,
            "value": cursor.value,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> _LibraryCursor:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        sort = payload["sort"]
        direction = payload["direction"]
        cursor_value = payload["value"]
        row_id = payload["id"]
        if sort not in {"id", "title", "artist", "album", "duration_ms", "link_status"}:
            raise ValueError
        if direction not in {"asc", "desc"}:
            raise ValueError
        if not isinstance(cursor_value, (str, int)) or not isinstance(row_id, int):
            raise ValueError
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError("Invalid library cursor") from exc
    return _LibraryCursor(
        sort=sort,
        direction=direction,
        value=cursor_value,
        row_id=row_id,
    )
