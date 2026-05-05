from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz
from sqlalchemy import create_engine, select

from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand, MatchResult
from app.streaming.models import streaming_tracks_table


_WHITESPACE_RE = re.compile(r"\s+")
DEFAULT_TAG_CANDIDATE_LIMIT = 10


@dataclass(frozen=True, slots=True)
class _LocalTags:
    title: str
    artist: str
    album: str | None


class TagMatcher:
    def __init__(self, *, database_url: str, beets_library: Path | str) -> None:
        self._engine = create_engine(database_url)
        self._beets_library = Path(beets_library)

    def match(self, local_track_id: int) -> MatchResult | None:
        candidates = self.candidates(local_track_id, limit=1)
        return candidates[0] if candidates else None

    def candidates(
        self,
        local_track_id: int,
        *,
        excluded_streaming_track_ids: set[int] | frozenset[int] | None = None,
        limit: int = DEFAULT_TAG_CANDIDATE_LIMIT,
    ) -> list[MatchResult]:
        beets_id = self._lookup_beets_id(local_track_id)
        if beets_id is None:
            return []

        local_tags = self._lookup_local_tags(beets_id)
        if local_tags is None:
            return []

        excluded_ids = excluded_streaming_track_ids or frozenset()
        candidates: list[MatchResult] = []
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    streaming_tracks_table.c.id,
                    streaming_tracks_table.c.title,
                    streaming_tracks_table.c.artist,
                    streaming_tracks_table.c.album,
                ).order_by(streaming_tracks_table.c.id.asc())
            ).mappings()

            for row in rows:
                streaming_track_id = row["id"]
                title = _normalize_text(row["title"])
                artist = _normalize_text(row["artist"])
                album = _normalize_text(row["album"])
                if (
                    not isinstance(streaming_track_id, int)
                    or title is None
                    or artist is None
                ):
                    continue
                if streaming_track_id in excluded_ids:
                    continue

                score = _score_tags(
                    local_title=local_tags.title,
                    local_artist=local_tags.artist,
                    local_album=local_tags.album,
                    streaming_title=title,
                    streaming_artist=artist,
                    streaming_album=album,
                )

                candidates.append(
                    MatchResult(
                        local_track_id=local_track_id,
                        streaming_track_id=streaming_track_id,
                        match_method="tags",
                        score=score,
                        confidence_band=ConfidenceBand.from_score(score),
                    )
                )

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates[:limit]

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

    def _lookup_local_tags(self, beets_id: int) -> _LocalTags | None:
        with sqlite3.connect(self._beets_library) as connection:
            row = connection.execute(
                "SELECT title, artist, album FROM items WHERE id = ?",
                (beets_id,),
            ).fetchone()

        if row is None:
            return None

        title = _normalize_text(row[0])
        artist = _normalize_text(row[1])
        album = _normalize_text(row[2])
        if title is None or artist is None:
            return None

        return _LocalTags(title=title, artist=artist, album=album)


def _score_tags(
    *,
    local_title: str,
    local_artist: str,
    local_album: str | None,
    streaming_title: str,
    streaming_artist: str,
    streaming_album: str | None,
) -> float:
    scores = [
        _similarity(local_title, streaming_title),
        _similarity(local_artist, streaming_artist),
    ]

    if local_album is not None and streaming_album is not None:
        scores.append(_similarity(local_album, streaming_album))

    return sum(scores) / len(scores)


def _similarity(left: str, right: str) -> float:
    return fuzz.ratio(left, right) / 100


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = _WHITESPACE_RE.sub(" ", value.strip().casefold())
    return normalized or None
