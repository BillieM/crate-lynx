from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, func, select

from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand, MatchResult
from app.streaming.models import streaming_tracks_table


class IsrcMatcher:
    def __init__(self, *, database_url: str, beets_library: Path | str) -> None:
        self._engine = create_engine(database_url)
        self._beets_library = Path(beets_library)

    def match(self, local_track_id: int) -> MatchResult | None:
        beets_id = self._lookup_beets_id(local_track_id)
        if beets_id is None:
            return None

        isrc = self._lookup_beets_isrc(beets_id)
        if isrc is None:
            return None

        streaming_track_id = self._lookup_streaming_track_id(isrc)
        if streaming_track_id is None:
            return None

        return MatchResult(
            local_track_id=local_track_id,
            streaming_track_id=streaming_track_id,
            match_method="isrc",
            score=1.0,
            confidence_band=ConfidenceBand.HIGH,
        )

    def _lookup_beets_id(self, local_track_id: int) -> int | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(local_tracks_table.c.beets_id).where(
                        local_tracks_table.c.id == local_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        beets_id = row["beets_id"]
        return beets_id if isinstance(beets_id, int) else None

    def _lookup_beets_isrc(self, beets_id: int) -> str | None:
        with sqlite3.connect(self._beets_library) as connection:
            row = connection.execute(
                "SELECT isrc FROM items WHERE id = ?",
                (beets_id,),
            ).fetchone()

        if row is None:
            return None

        return _normalize_isrc(row[0])

    def _lookup_streaming_track_id(self, isrc: str) -> int | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(streaming_tracks_table.c.id)
                    .where(func.upper(streaming_tracks_table.c.isrc) == isrc)
                    .order_by(streaming_tracks_table.c.id.asc())
                )
                .mappings()
                .first()
            )

        if row is None:
            return None

        streaming_track_id = row["id"]
        return streaming_track_id if isinstance(streaming_track_id, int) else None


def _normalize_isrc(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().upper()
    return normalized or None
