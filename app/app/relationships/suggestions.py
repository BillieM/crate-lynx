from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
import re
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.matching.tags import normalize_match_text, score_track_tags, title_identity
from app.relationships.models import (
    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
    STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
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
EQUIVALENT_SUGGESTION_SCORE_MIN = 0.94
RELATED_SUGGESTION_SCORE_MIN = 0.93
FUZZY_SUGGESTION_BUCKET_LIMIT = 5
MAX_PENDING_RELATIONSHIP_SUGGESTIONS = 1000
EQUIVALENT_DURATION_TOLERANCE_MS = 10_000
ALBUM_CONFLICT_SIMILARITY_MAX = 0.98
NEAR_TITLE_SIMILARITY_MIN = 0.90
ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
VERSION_TERM_RE = re.compile(
    r"\b(?:acoustic|alt|alternate|club|demo|edit|extended|instrumental|"
    r"karaoke|live|mix|mono|original|radio|remaster(?:ed)?|remix|session|"
    r"single|stereo|take|version)\b"
)
TITLE_VERSION_PAREN_RE = re.compile(
    r"\s*[\[(][^\])]*(?:acoustic|alt|alternate|club|demo|edit|extended|"
    r"instrumental|karaoke|live|mix|mono|original|radio|remaster(?:ed)?|"
    r"remix|session|single|stereo|take|version)\b[^\])]*[\])]"
)
TITLE_VERSION_SUFFIX_RE = re.compile(
    r"(?:\s+-\s+|\s+)(?:acoustic|alt|alternate|club|demo|edit|extended|"
    r"instrumental|karaoke|live|mix|mono|original|radio|remaster(?:ed)?|"
    r"remix|session|single|stereo|take|version)\b.*$"
)
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
    pruned_count: int
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
    final_suggestion_pairs: frozenset[tuple[int, int]]
    accepted_group_pairs: frozenset[tuple[int, int]]
    rejected_group_pairs: frozenset[tuple[int, int]]


@dataclass(frozen=True, slots=True)
class _EquivalentSafetyCheck:
    version_conflict: bool
    duration_conflict: bool
    album_conflict: bool

    @property
    def is_safe(self) -> bool:
        return not (
            self.version_conflict or self.duration_conflict or self.album_conflict
        )

    @property
    def has_related_signal(self) -> bool:
        return self.version_conflict


class StreamingRelationshipSuggestionGenerator:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def generate(self) -> StreamingRelationshipSuggestionGenerationResult:
        with self._engine.begin() as connection:
            tracks = _active_streaming_tracks(connection)
            suppression_context = _suppression_context(connection)
            suggestions = _relationship_candidates(tracks, suppression_context)
            pruned_count = _prune_pending_suggestions(
                connection,
                frozenset(_suggestion_pair(suggestion) for suggestion in suggestions),
            )
            created_count = _upsert_pending_suggestions(
                connection,
                suggestions,
            )

        return StreamingRelationshipSuggestionGenerationResult(
            created_count=created_count,
            pruned_count=pruned_count,
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
    final_suggestion_pairs = frozenset(
        (
            int(row["lower_track_id"]),
            int(row["higher_track_id"]),
        )
        for row in suggestion_rows
        if row["status"]
        in (
            STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
            STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
        )
    )
    rejected_group_pairs = frozenset(
        groups.pair_key(int(row["lower_track_id"]), int(row["higher_track_id"]))
        for row in suggestion_rows
        if row["status"] == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED
    )

    return _SuppressionContext(
        groups=groups,
        final_suggestion_pairs=final_suggestion_pairs,
        accepted_group_pairs=accepted_group_pairs,
        rejected_group_pairs=rejected_group_pairs,
    )


def _relationship_candidates(
    tracks: tuple[_StreamingTrackCandidate, ...],
    suppression_context: _SuppressionContext,
) -> tuple[GeneratedStreamingRelationshipSuggestion, ...]:
    candidate_by_pair: dict[
        tuple[int, int],
        GeneratedStreamingRelationshipSuggestion,
    ] = {}

    for candidate in _isrc_candidates(tracks, suppression_context):
        candidate_by_pair[_suggestion_pair(candidate)] = candidate

    for candidate in _fuzzy_candidates(tracks, suppression_context):
        candidate_by_pair.setdefault(_suggestion_pair(candidate), candidate)

    return tuple(
        sorted(
            candidate_by_pair.values(),
            key=lambda candidate: (
                -candidate.score,
                candidate.lower_track_id,
                candidate.higher_track_id,
            ),
        )[:MAX_PENDING_RELATIONSHIP_SUGGESTIONS]
    )


def _isrc_candidates(
    tracks: tuple[_StreamingTrackCandidate, ...],
    suppression_context: _SuppressionContext,
) -> tuple[GeneratedStreamingRelationshipSuggestion, ...]:
    tracks_by_isrc: defaultdict[str, list[_StreamingTrackCandidate]] = defaultdict(list)
    for track in tracks:
        if track.isrc is not None:
            tracks_by_isrc[track.isrc].append(track)

    candidates: list[GeneratedStreamingRelationshipSuggestion] = []
    for _, isrc_tracks in sorted(tracks_by_isrc.items()):
        if len(isrc_tracks) < 2:
            continue

        sorted_tracks = sorted(isrc_tracks, key=lambda track: track.id)
        anchor = sorted_tracks[0]
        for track in sorted_tracks[1:]:
            pair = normalize_streaming_track_pair(anchor.id, track.id)
            if _is_pair_suppressed(
                pair.lower_track_id,
                pair.higher_track_id,
                suppression_context,
            ):
                continue

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
    suppression_context: _SuppressionContext,
) -> tuple[GeneratedStreamingRelationshipSuggestion, ...]:
    candidates: list[GeneratedStreamingRelationshipSuggestion] = []
    tracks_by_bucket: defaultdict[
        tuple[str, str],
        list[_StreamingTrackCandidate],
    ] = defaultdict(list)
    for track in tracks:
        tracks_by_bucket[(track.artist, _fuzzy_title_bucket_key(track.title))].append(
            track
        )

    for bucket_tracks in tracks_by_bucket.values():
        if len(bucket_tracks) < 2:
            continue

        bucket_candidates: list[GeneratedStreamingRelationshipSuggestion] = []
        for first, second in combinations(
            sorted(bucket_tracks, key=lambda track: track.id),
            2,
        ):
            if first.isrc is not None and first.isrc == second.isrc:
                continue

            if first.artist != second.artist or not _has_near_same_title(
                first.title,
                second.title,
            ):
                continue

            pair = normalize_streaming_track_pair(first.id, second.id)
            if _is_pair_suppressed(
                pair.lower_track_id,
                pair.higher_track_id,
                suppression_context,
            ):
                continue

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
            safety = _equivalent_safety(first, second)
            if score >= EQUIVALENT_SUGGESTION_SCORE_MIN and safety.is_safe:
                bucket_candidates.append(
                    GeneratedStreamingRelationshipSuggestion(
                        lower_track_id=pair.lower_track_id,
                        higher_track_id=pair.higher_track_id,
                        relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
                        match_method=MATCH_METHOD_TAGS,
                        score=score,
                        confidence=STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
                    )
                )
                continue

            if score >= RELATED_SUGGESTION_SCORE_MIN and safety.has_related_signal:
                bucket_candidates.append(
                    GeneratedStreamingRelationshipSuggestion(
                        lower_track_id=pair.lower_track_id,
                        higher_track_id=pair.higher_track_id,
                        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
                        match_method=MATCH_METHOD_TAGS,
                        score=score,
                        confidence=STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
                    )
                )

        bucket_candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                candidate.lower_track_id,
                candidate.higher_track_id,
            )
        )
        candidates.extend(bucket_candidates[:FUZZY_SUGGESTION_BUCKET_LIMIT])

    return tuple(candidates)


def _is_pair_suppressed(
    lower_track_id: int,
    higher_track_id: int,
    context: _SuppressionContext,
) -> bool:
    pair = (lower_track_id, higher_track_id)
    if pair in context.final_suggestion_pairs:
        return True

    group_pair = context.groups.pair_key(
        lower_track_id,
        higher_track_id,
    )
    if group_pair[0] == group_pair[1]:
        return True

    return (
        group_pair in context.accepted_group_pairs
        or group_pair in context.rejected_group_pairs
    )


def _prune_pending_suggestions(
    connection,
    valid_pairs: frozenset[tuple[int, int]],
) -> int:
    pending_rows = (
        connection.execute(
            select(
                streaming_relationship_suggestions_table.c.id,
                streaming_relationship_suggestions_table.c.lower_track_id,
                streaming_relationship_suggestions_table.c.higher_track_id,
            ).where(
                streaming_relationship_suggestions_table.c.status
                == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING
            )
        )
        .mappings()
        .all()
    )
    stale_ids = [
        int(row["id"])
        for row in pending_rows
        if (
            int(row["lower_track_id"]),
            int(row["higher_track_id"]),
        )
        not in valid_pairs
    ]
    if not stale_ids:
        return 0

    result = connection.execute(
        delete(streaming_relationship_suggestions_table).where(
            streaming_relationship_suggestions_table.c.id.in_(stale_ids)
        )
    )
    return result.rowcount or 0


def _upsert_pending_suggestions(
    connection,
    suggestions: tuple[GeneratedStreamingRelationshipSuggestion, ...],
) -> int:
    if not suggestions:
        return 0

    existing_pending_pairs = _pending_suggestion_pairs(connection)
    created_count = sum(
        1
        for suggestion in suggestions
        if _suggestion_pair(suggestion) not in existing_pending_pairs
    )

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
    insert_statement = _conflict_insert(
        streaming_relationship_suggestions_table,
        connection.dialect.name,
    )
    statement = insert_statement.on_conflict_do_update(
        index_elements=[
            streaming_relationship_suggestions_table.c.lower_track_id,
            streaming_relationship_suggestions_table.c.higher_track_id,
        ],
        set_={
            "relationship_type": insert_statement.excluded.relationship_type,
            "match_method": insert_statement.excluded.match_method,
            "score": insert_statement.excluded.score,
            "confidence": insert_statement.excluded.confidence,
        },
        where=(
            streaming_relationship_suggestions_table.c.status
            == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING
        ),
    )
    connection.execute(statement, rows)
    return created_count


def _pending_suggestion_pairs(connection) -> frozenset[tuple[int, int]]:
    return frozenset(
        (
            int(row["lower_track_id"]),
            int(row["higher_track_id"]),
        )
        for row in connection.execute(
            select(
                streaming_relationship_suggestions_table.c.lower_track_id,
                streaming_relationship_suggestions_table.c.higher_track_id,
            ).where(
                streaming_relationship_suggestions_table.c.status
                == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING
            )
        )
        .mappings()
        .all()
    )


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

    normalized = re.sub(r"[\s-]+", "", value.strip().upper())
    if not normalized or ISRC_RE.fullmatch(normalized) is None:
        return None

    return normalized


def _fuzzy_title_key(title: str) -> str:
    without_parenthetical_versions = TITLE_VERSION_PAREN_RE.sub("", title)
    without_suffix_versions = TITLE_VERSION_SUFFIX_RE.sub(
        "",
        without_parenthetical_versions,
    )
    return title_identity(without_suffix_versions)


def _fuzzy_title_bucket_key(title: str) -> str:
    title_key = _fuzzy_title_key(title)
    first_token = title_key.split(maxsplit=1)[0] if title_key else ""
    return first_token or title_key


def _has_near_same_title(first_title: str, second_title: str) -> bool:
    first_key = _fuzzy_title_key(first_title)
    second_key = _fuzzy_title_key(second_title)
    if first_key == second_key:
        return True

    return fuzz.token_sort_ratio(first_key, second_key) / 100 >= (
        NEAR_TITLE_SIMILARITY_MIN
    )


def _equivalent_safety(
    first: _StreamingTrackCandidate,
    second: _StreamingTrackCandidate,
) -> _EquivalentSafetyCheck:
    return _EquivalentSafetyCheck(
        version_conflict=_title_version_tokens(first.title)
        != _title_version_tokens(second.title),
        duration_conflict=_has_duration_conflict(
            first.duration_ms,
            second.duration_ms,
        ),
        album_conflict=_has_album_conflict(first.album, second.album),
    )


def _title_version_tokens(title: str) -> frozenset[str]:
    return frozenset(match.group(0) for match in VERSION_TERM_RE.finditer(title))


def _has_duration_conflict(
    first_duration_ms: int | None,
    second_duration_ms: int | None,
) -> bool:
    return (
        first_duration_ms is not None
        and second_duration_ms is not None
        and abs(first_duration_ms - second_duration_ms)
        > EQUIVALENT_DURATION_TOLERANCE_MS
    )


def _has_album_conflict(first_album: str | None, second_album: str | None) -> bool:
    if first_album is None or second_album is None:
        return False

    return fuzz.token_sort_ratio(first_album, second_album) / 100 < (
        ALBUM_CONFLICT_SIMILARITY_MAX
    )
