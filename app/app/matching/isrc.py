from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.core.tables import beets_items_view
from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand, MatchResult
from app.streaming.models import streaming_tracks_table


class IsrcMatcher:
    def __init__(
        self, *, database_url: str | None = None, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def match(self, local_track_id: int) -> MatchResult | None:
        isrc = self._lookup_local_isrc(local_track_id)
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

    def _lookup_local_isrc(self, local_track_id: int) -> str | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(beets_items_view.c.isrc)
                    .select_from(
                        local_tracks_table.join(
                            beets_items_view,
                            local_tracks_table.c.beets_id
                            == beets_items_view.c.beets_id,
                        )
                    )
                    .where(local_tracks_table.c.id == local_track_id)
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return _normalize_isrc(row["isrc"])

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
