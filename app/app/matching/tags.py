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
_NON_WORD_RE = re.compile(r"[^\w']+")
_TITLE_NOISE_BOUNDARY_RE = re.compile(
    r"\b(?:ft|feat|featuring|with|original|extended|radio|club|small)\b\.?.*"
)
_TITLE_PAREN_NOISE_RE = re.compile(
    r"\s*[\[(][^\])]*(?:ft|feat|featuring|original|extended|radio|club|small)\b[^\])]*[\])]",
)
DEFAULT_TAG_CANDIDATE_LIMIT = 10
TITLE_WEIGHT = 0.68
ARTIST_WEIGHT = 0.26
ALBUM_BONUS_WEIGHT = 0.04
DURATION_BONUS_WEIGHT = 0.02
DURATION_BONUS_TOLERANCE_MS = 10_000


@dataclass(frozen=True, slots=True)
class _LocalTags:
    title: str
    artist: str
    album: str | None
    duration_ms: int | None


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
                    streaming_tracks_table.c.duration_ms,
                ).order_by(streaming_tracks_table.c.id.asc())
            ).mappings()

            for row in rows:
                streaming_track_id = row["id"]
                title = _normalize_text(row["title"])
                artist = _normalize_text(row["artist"])
                album = _normalize_text(row["album"])
                duration_ms = row["duration_ms"]
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
                    local_duration_ms=local_tags.duration_ms,
                    streaming_title=title,
                    streaming_artist=artist,
                    streaming_album=album,
                    streaming_duration_ms=(
                        duration_ms if isinstance(duration_ms, int) else None
                    ),
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
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(items)").fetchall()
                if isinstance(row[1], str)
            }
            duration_column = ", length" if "length" in columns else ""
            row = connection.execute(
                f"SELECT title, artist, album{duration_column} FROM items WHERE id = ?",
                (beets_id,),
            ).fetchone()

        if row is None:
            return None

        title = _normalize_text(row[0])
        artist = _normalize_text(row[1])
        album = _normalize_text(row[2])
        duration_ms = _normalize_duration_ms(row[3]) if len(row) > 3 else None
        if title is None or artist is None:
            return None

        return _LocalTags(
            title=title,
            artist=artist,
            album=album,
            duration_ms=duration_ms,
        )


def _score_tags(
    *,
    local_title: str,
    local_artist: str,
    local_album: str | None,
    local_duration_ms: int | None,
    streaming_title: str,
    streaming_artist: str,
    streaming_album: str | None,
    streaming_duration_ms: int | None,
) -> float:
    score = (
        _title_similarity(local_title, streaming_title) * TITLE_WEIGHT
        + _token_similarity(local_artist, streaming_artist) * ARTIST_WEIGHT
    )

    if local_album is not None and streaming_album is not None:
        score += _album_similarity(local_album, streaming_album) * ALBUM_BONUS_WEIGHT

    if (
        local_duration_ms is not None
        and streaming_duration_ms is not None
        and abs(local_duration_ms - streaming_duration_ms)
        <= DURATION_BONUS_TOLERANCE_MS
    ):
        score += DURATION_BONUS_WEIGHT

    return min(score, 1.0)


def _title_similarity(left: str, right: str) -> float:
    return max(
        _token_similarity(left, right),
        _token_similarity(_title_identity(left), _title_identity(right)),
    )


def _token_similarity(left: str, right: str) -> float:
    return fuzz.token_set_ratio(left, right) / 100


def _album_similarity(left: str, right: str) -> float:
    return fuzz.token_sort_ratio(left, right) / 100


def _normalize_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = _WHITESPACE_RE.sub(" ", value.strip().casefold())
    return normalized or None


def _title_identity(value: str) -> str:
    without_parenthetical_noise = _TITLE_PAREN_NOISE_RE.sub("", value)
    without_suffix_noise = _TITLE_NOISE_BOUNDARY_RE.sub("", without_parenthetical_noise)
    normalized = _NON_WORD_RE.sub(" ", without_suffix_noise)
    normalized = _WHITESPACE_RE.sub(" ", normalized.strip())
    return normalized or value


def _normalize_duration_ms(value: object) -> int | None:
    if isinstance(value, int):
        return value * 1000
    if isinstance(value, float):
        return int(value * 1000)
    return None
