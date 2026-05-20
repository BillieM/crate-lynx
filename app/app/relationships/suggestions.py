from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.matching.models import ConfidenceBand
from app.matching.tags import normalize_match_text, score_track_tags
from app.relationships.models import (
    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
    STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    normalize_streaming_track_pair,
    streaming_relationship_suggestions_table,
    streaming_relationships_table,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


MATCH_METHOD_ISRC = "isrc"
MATCH_METHOD_TAGS = "tags"
ACTIVE_RELATIONSHIP_SUGGESTION_PLAYLIST_MODES = (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
)


@dataclass(frozen=True, slots=True)
class GeneratedStreamingRelationshipSuggestion:
    lower_track_id: int
    higher_track_id: int
    relationship_type: str
    match_method: str
    score: float
    confidence: str


@dataclass(frozen=True, slots=True)
class StreamingRelationshipSuggestionGenerationResult:
    created_count: int
    suggestions: tuple[GeneratedStreamingRelationshipSuggestion, ...]


@dataclass(frozen=True, slots=True)
class _StreamingTrackCandidate:
    id: int
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    isrc: str | None


@dataclass(frozen=True, slots=True)
class _SuppressionContext:
    groups: _TrackGroups
    existing_suggestion_pairs: frozenset[tuple[int, int]]
    accepted_group_pairs: frozenset[tuple[int, int]]
    rejected_group_pairs: frozenset[tuple[int, int]]


class StreamingRelationshipSuggestionGenerator:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def generate(self) -> StreamingRelationshipSuggestionGenerationResult:
        with self._engine.begin() as connection:
            tracks = _active_streaming_tracks(connection)
            suppression_context = _suppression_context(connection)
            suggestions = tuple(
                candidate
                for candidate in _relationship_candidates(tracks)
                if not _is_suppressed(candidate, suppression_context)
            )
            created_count = _insert_suggestions(
                connection,
                suggestions,
            )

        return StreamingRelationshipSuggestionGenerationResult(
            created_count=created_count,
            suggestions=suggestions,
        )


class _TrackGroups:
    def __init__(self) -> None:
        self._parents: dict[int, int] = {}

    def find(self, track_id: int) -> int:
        parent = self._parents.setdefault(track_id, track_id)
        if parent != track_id:
            parent = self.find(parent)
            self._parents[track_id] = parent
        return parent

    def union(self, first_track_id: int, second_track_id: int) -> None:
        first_root = self.find(first_track_id)
        second_root = self.find(second_track_id)
        if first_root == second_root:
            return

        lower_root, higher_root = sorted((first_root, second_root))
        self._parents[higher_root] = lower_root

    def pair_key(self, first_track_id: int, second_track_id: int) -> tuple[int, int]:
        return tuple(sorted((self.find(first_track_id), self.find(second_track_id))))


def _active_streaming_tracks(connection) -> tuple[_StreamingTrackCandidate, ...]:
    rows = (
        connection.execute(
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.duration_ms,
                streaming_tracks_table.c.isrc,
            )
            .select_from(
                streaming_tracks_table.join(
                    playlist_membership_table,
                    playlist_membership_table.c.streaming_track_id
                    == streaming_tracks_table.c.id,
                ).join(
                    streaming_playlists_table,
                    streaming_playlists_table.c.id
                    == playlist_membership_table.c.playlist_id,
                )
            )
            .where(
                streaming_playlists_table.c.sync_mode.in_(
                    ACTIVE_RELATIONSHIP_SUGGESTION_PLAYLIST_MODES
                )
            )
            .distinct()
            .order_by(streaming_tracks_table.c.id.asc())
        )
        .mappings()
        .all()
    )

    tracks: list[_StreamingTrackCandidate] = []
    for row in rows:
        title = normalize_match_text(row["title"])
        artist = normalize_match_text(row["artist"])
        if title is None or artist is None:
            continue

        duration_ms = row["duration_ms"]
        tracks.append(
            _StreamingTrackCandidate(
                id=int(row["id"]),
                title=title,
                artist=artist,
                album=normalize_match_text(row["album"]),
                duration_ms=duration_ms if isinstance(duration_ms, int) else None,
                isrc=_normalize_isrc(row["isrc"]),
            )
        )

    return tuple(tracks)


def _suppression_context(connection) -> _SuppressionContext:
    relationship_rows = (
        connection.execute(
            select(
                streaming_relationships_table.c.lower_track_id,
                streaming_relationships_table.c.higher_track_id,
                streaming_relationships_table.c.relationship_type,
            )
        )
        .mappings()
        .all()
    )
    groups = _TrackGroups()
    for row in relationship_rows:
        if row["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT:
            groups.union(int(row["lower_track_id"]), int(row["higher_track_id"]))

    accepted_group_pairs = frozenset(
        groups.pair_key(int(row["lower_track_id"]), int(row["higher_track_id"]))
        for row in relationship_rows
    )

    suggestion_rows = (
        connection.execute(
            select(
                streaming_relationship_suggestions_table.c.lower_track_id,
                streaming_relationship_suggestions_table.c.higher_track_id,
                streaming_relationship_suggestions_table.c.status,
            )
        )
        .mappings()
        .all()
    )
    existing_suggestion_pairs = frozenset(
        (
            int(row["lower_track_id"]),
            int(row["higher_track_id"]),
        )
        for row in suggestion_rows
    )
    rejected_group_pairs = frozenset(
        groups.pair_key(int(row["lower_track_id"]), int(row["higher_track_id"]))
        for row in suggestion_rows
        if row["status"] == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED
    )

    return _SuppressionContext(
        groups=groups,
        existing_suggestion_pairs=existing_suggestion_pairs,
        accepted_group_pairs=accepted_group_pairs,
        rejected_group_pairs=rejected_group_pairs,
    )


def _relationship_candidates(
    tracks: tuple[_StreamingTrackCandidate, ...],
) -> tuple[GeneratedStreamingRelationshipSuggestion, ...]:
    candidate_by_pair: dict[
        tuple[int, int],
        GeneratedStreamingRelationshipSuggestion,
    ] = {}

    for candidate in _isrc_candidates(tracks):
        candidate_by_pair[_suggestion_pair(candidate)] = candidate

    for candidate in _fuzzy_candidates(tracks):
        candidate_by_pair.setdefault(_suggestion_pair(candidate), candidate)

    return tuple(
        sorted(
            candidate_by_pair.values(),
            key=lambda candidate: (
                candidate.lower_track_id,
                candidate.higher_track_id,
                -candidate.score,
            ),
        )
    )


def _isrc_candidates(
    tracks: tuple[_StreamingTrackCandidate, ...],
) -> tuple[GeneratedStreamingRelationshipSuggestion, ...]:
    tracks_by_isrc: defaultdict[str, list[_StreamingTrackCandidate]] = defaultdict(list)
    for track in tracks:
        if track.isrc is not None:
            tracks_by_isrc[track.isrc].append(track)

    candidates: list[GeneratedStreamingRelationshipSuggestion] = []
    for isrc_tracks in tracks_by_isrc.values():
        if len(isrc_tracks) < 2:
            continue

        for first, second in combinations(isrc_tracks, 2):
            pair = normalize_streaming_track_pair(first.id, second.id)
            candidates.append(
                GeneratedStreamingRelationshipSuggestion(
                    lower_track_id=pair.lower_track_id,
                    higher_track_id=pair.higher_track_id,
                    relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
                    match_method=MATCH_METHOD_ISRC,
                    score=1.0,
                    confidence=STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
                )
            )

    return tuple(candidates)


def _fuzzy_candidates(
    tracks: tuple[_StreamingTrackCandidate, ...],
) -> tuple[GeneratedStreamingRelationshipSuggestion, ...]:
    candidates: list[GeneratedStreamingRelationshipSuggestion] = []
    for first, second in combinations(tracks, 2):
        score = score_track_tags(
            left_title=first.title,
            left_artist=first.artist,
            left_album=first.album,
            left_duration_ms=first.duration_ms,
            right_title=second.title,
            right_artist=second.artist,
            right_album=second.album,
            right_duration_ms=second.duration_ms,
        )
        confidence_band = ConfidenceBand.from_score(score)
        if confidence_band == ConfidenceBand.LOW:
            continue

        pair = normalize_streaming_track_pair(first.id, second.id)
        candidates.append(
            GeneratedStreamingRelationshipSuggestion(
                lower_track_id=pair.lower_track_id,
                higher_track_id=pair.higher_track_id,
                relationship_type=(
                    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT
                    if confidence_band == ConfidenceBand.HIGH
                    else STREAMING_RELATIONSHIP_TYPE_RELATED
                ),
                match_method=MATCH_METHOD_TAGS,
                score=score,
                confidence=(
                    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH
                    if confidence_band == ConfidenceBand.HIGH
                    else STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM
                ),
            )
        )

    return tuple(candidates)


def _is_suppressed(
    candidate: GeneratedStreamingRelationshipSuggestion,
    context: _SuppressionContext,
) -> bool:
    pair = _suggestion_pair(candidate)
    if pair in context.existing_suggestion_pairs:
        return True

    group_pair = context.groups.pair_key(
        candidate.lower_track_id,
        candidate.higher_track_id,
    )
    if group_pair[0] == group_pair[1]:
        return True

    return (
        group_pair in context.accepted_group_pairs
        or group_pair in context.rejected_group_pairs
    )


def _insert_suggestions(
    connection,
    suggestions: tuple[GeneratedStreamingRelationshipSuggestion, ...],
) -> int:
    if not suggestions:
        return 0

    rows = [
        {
            "lower_track_id": suggestion.lower_track_id,
            "higher_track_id": suggestion.higher_track_id,
            "relationship_type": suggestion.relationship_type,
            "match_method": suggestion.match_method,
            "score": suggestion.score,
            "confidence": suggestion.confidence,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
        }
        for suggestion in suggestions
    ]
    statement = _conflict_insert(
        streaming_relationship_suggestions_table,
        connection.dialect.name,
    ).on_conflict_do_nothing(
        index_elements=[
            streaming_relationship_suggestions_table.c.lower_track_id,
            streaming_relationship_suggestions_table.c.higher_track_id,
        ]
    )
    result = connection.execute(statement, rows)
    return result.rowcount or 0


def _conflict_insert(target_table: Any, dialect_name: str) -> Any:
    if dialect_name == "postgresql":
        return postgresql_insert(target_table)
    if dialect_name == "sqlite":
        return sqlite_insert(target_table)
    raise ValueError(
        f"Unsupported database dialect for relationship suggestion generation: "
        f"{dialect_name}"
    )


def _suggestion_pair(
    suggestion: GeneratedStreamingRelationshipSuggestion,
) -> tuple[int, int]:
    return (suggestion.lower_track_id, suggestion.higher_track_id)


def _normalize_isrc(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().upper()
    return normalized or None
