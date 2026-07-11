from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection, Engine

from app.core.cursors import ScoreIdCursor
from app.core.db import create_database_engine
from app.ingestion.beets_mirror import beets_items_table
from app.links.store import detach_final_links as detach_final_link_records
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.relationships.models import (
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPES,
    normalize_streaming_track_pair,
    streaming_relationship_suggestions_table,
    streaming_relationships_table,
)
from app.relationships.resolver import (
    RESOLUTION_SOURCE_DIRECT,
    EquivalentAcceptanceConflict,
    RelationshipFinalLink,
    ResolvedStreamingTrackLink,
    StreamingRelationshipResolver,
)
from app.relationships.suggestions import (
    StreamingRelationshipSuggestionGenerationResult,
    StreamingRelationshipSuggestionGenerator,
)
from app.streaming.models import streaming_tracks_table


CONFLICT_STATE_NONE = "none"
CONFLICT_STATE_DIFFERENT_LOCAL_LINKS = "different_local_links"
DEFAULT_RELATIONSHIP_SUGGESTION_LIST_LIMIT = 50


class StreamingRelationshipSuggestionNotFoundError(Exception):
    pass


class StaleStreamingRelationshipSuggestionError(Exception):
    pass


class StreamingRelationshipAcceptanceConflictError(Exception):
    def __init__(self, conflict: EquivalentAcceptanceConflict) -> None:
        super().__init__(
            "winning_final_link_id is required for conflicting equivalent relationship"
        )
        self.conflict = conflict


class InvalidWinningFinalLinkError(Exception):
    pass


class StreamingRelationshipNotFoundError(Exception):
    pass


class StreamingRelationshipAlreadyExistsError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StreamingRelationshipTrackRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class StreamingRelationshipLocalLinkContext:
    final_link_id: int
    local_track_id: int
    local_file_path: str | None
    local_title: str | None
    local_artist: str | None
    local_album: str | None
    streaming_track_id: int
    source_streaming_track_id: int
    resolution_source: str
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class StreamingRelationshipConflictContext:
    first_group_track_ids: tuple[int, ...]
    second_group_track_ids: tuple[int, ...]
    local_track_ids: tuple[int, ...]
    final_links: tuple[StreamingRelationshipLocalLinkContext, ...]


@dataclass(frozen=True, slots=True)
class StreamingRelationshipSuggestionRecord:
    id: int
    lower_track_id: int
    higher_track_id: int
    relationship_type: str
    match_method: str
    score: float
    confidence: str
    status: str
    created_at: datetime
    first_track: StreamingRelationshipTrackRecord
    second_track: StreamingRelationshipTrackRecord
    first_link: StreamingRelationshipLocalLinkContext | None
    second_link: StreamingRelationshipLocalLinkContext | None
    conflict_state: str
    conflict: StreamingRelationshipConflictContext | None


@dataclass(frozen=True, slots=True)
class AcceptStreamingRelationshipSuggestionResult:
    suggestion_id: int
    relationship_id: int
    relationship_type: str
    accepted_at: datetime
    detached_final_link_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RejectStreamingRelationshipSuggestionResult:
    suggestion_id: int
    rejected_at: datetime


@dataclass(frozen=True, slots=True)
class StreamingRelationshipMutationResult:
    relationship_id: int
    relationship_type: str
    accepted_at: datetime | None
    detached_final_link_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _SuggestionResolutionContext:
    row: object
    lower_track_id: int
    higher_track_id: int
    first_resolved_link: ResolvedStreamingTrackLink | None
    second_resolved_link: ResolvedStreamingTrackLink | None
    conflict: EquivalentAcceptanceConflict | None

    @property
    def final_link_ids(self) -> tuple[int, ...]:
        link_ids = [
            resolved.final_link_id
            for resolved in (self.first_resolved_link, self.second_resolved_link)
            if resolved is not None
        ]
        if self.conflict is not None:
            link_ids.extend(link.id for link in self.conflict.final_links)
        return tuple(link_ids)


class StreamingRelationshipSuggestionStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def count_pending(self, *, relationship_type: str | None = None) -> int:
        if relationship_type is not None:
            _validate_relationship_type(relationship_type)

        query = select(
            streaming_relationship_suggestions_table.c.lower_track_id,
            streaming_relationship_suggestions_table.c.higher_track_id,
        ).where(
            streaming_relationship_suggestions_table.c.status
            == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
            _no_existing_relationship_clause(),
        )
        if relationship_type is not None:
            query = query.where(
                streaming_relationship_suggestions_table.c.relationship_type
                == relationship_type
            )

        with self._engine.connect() as connection:
            resolver = StreamingRelationshipResolver(connection)
            return sum(
                1
                for row in connection.execute(query).mappings().all()
                if not _is_stale_pending_suggestion(
                    connection,
                    resolver=resolver,
                    lower_track_id=int(row["lower_track_id"]),
                    higher_track_id=int(row["higher_track_id"]),
                    direct_relationships_filtered=True,
                )
            )

    def list_pending(
        self,
        *,
        cursor: ScoreIdCursor | None = None,
        limit: int | None = DEFAULT_RELATIONSHIP_SUGGESTION_LIST_LIMIT,
        relationship_type: str | None = None,
    ) -> list[StreamingRelationshipSuggestionRecord]:
        if relationship_type is not None:
            _validate_relationship_type(relationship_type)

        first_track = streaming_tracks_table.alias("first_track")
        second_track = streaming_tracks_table.alias("second_track")
        query = (
            select(
                streaming_relationship_suggestions_table.c.id,
                streaming_relationship_suggestions_table.c.lower_track_id,
                streaming_relationship_suggestions_table.c.higher_track_id,
                streaming_relationship_suggestions_table.c.relationship_type,
                streaming_relationship_suggestions_table.c.match_method,
                streaming_relationship_suggestions_table.c.score,
                streaming_relationship_suggestions_table.c.confidence,
                streaming_relationship_suggestions_table.c.status,
                streaming_relationship_suggestions_table.c.created_at,
                first_track.c.provider_track_id.label("first_provider_track_id"),
                first_track.c.title.label("first_title"),
                first_track.c.artist.label("first_artist"),
                first_track.c.album.label("first_album"),
                first_track.c.year.label("first_year"),
                first_track.c.isrc.label("first_isrc"),
                first_track.c.duration_ms.label("first_duration_ms"),
                second_track.c.provider_track_id.label("second_provider_track_id"),
                second_track.c.title.label("second_title"),
                second_track.c.artist.label("second_artist"),
                second_track.c.album.label("second_album"),
                second_track.c.year.label("second_year"),
                second_track.c.isrc.label("second_isrc"),
                second_track.c.duration_ms.label("second_duration_ms"),
            )
            .select_from(
                streaming_relationship_suggestions_table.join(
                    first_track,
                    first_track.c.id
                    == streaming_relationship_suggestions_table.c.lower_track_id,
                ).join(
                    second_track,
                    second_track.c.id
                    == streaming_relationship_suggestions_table.c.higher_track_id,
                )
            )
            .where(
                streaming_relationship_suggestions_table.c.status
                == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
                _no_existing_relationship_clause(),
            )
            .order_by(
                streaming_relationship_suggestions_table.c.score.desc(),
                streaming_relationship_suggestions_table.c.id.asc(),
            )
        )
        if relationship_type is not None:
            query = query.where(
                streaming_relationship_suggestions_table.c.relationship_type
                == relationship_type
            )
        if cursor is not None:
            query = query.where(
                or_(
                    streaming_relationship_suggestions_table.c.score < cursor.score,
                    and_(
                        streaming_relationship_suggestions_table.c.score
                        == cursor.score,
                        streaming_relationship_suggestions_table.c.id > cursor.row_id,
                    ),
                )
            )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
            resolver = StreamingRelationshipResolver(connection)
            link_contexts = _LocalLinkContextFactory(connection)
            contexts: list[_SuggestionResolutionContext] = []
            for row in rows:
                lower_track_id = int(row["lower_track_id"])
                higher_track_id = int(row["higher_track_id"])
                if _is_stale_pending_suggestion(
                    connection,
                    resolver=resolver,
                    lower_track_id=lower_track_id,
                    higher_track_id=higher_track_id,
                    direct_relationships_filtered=True,
                ):
                    continue

                contexts.append(
                    _suggestion_resolution_context(row=row, resolver=resolver)
                )
                if limit is not None and len(contexts) >= limit:
                    break

            link_contexts.prime(
                final_link_id
                for context in contexts
                for final_link_id in context.final_link_ids
            )

            return [
                _suggestion_record(
                    context=context,
                    link_contexts=link_contexts,
                )
                for context in contexts
            ]

    def accept(
        self,
        suggestion_id: int,
        *,
        relationship_type: str | None = None,
        winning_final_link_id: int | None = None,
    ) -> AcceptStreamingRelationshipSuggestionResult:
        accepted_at = datetime.now(UTC)

        with self._engine.begin() as connection:
            suggestion = _pending_suggestion_row(connection, suggestion_id)
            if suggestion is None:
                raise StreamingRelationshipSuggestionNotFoundError
            if suggestion["status"] != STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING:
                raise StaleStreamingRelationshipSuggestionError

            lower_track_id = int(suggestion["lower_track_id"])
            higher_track_id = int(suggestion["higher_track_id"])
            accepted_relationship_type = (
                str(suggestion["relationship_type"])
                if relationship_type is None
                else relationship_type
            )
            _validate_relationship_type(accepted_relationship_type)
            if _has_existing_relationship(
                connection,
                lower_track_id=lower_track_id,
                higher_track_id=higher_track_id,
            ):
                raise StaleStreamingRelationshipSuggestionError

            resolver = StreamingRelationshipResolver(connection)
            if higher_track_id in resolver.equivalent_group_track_ids(lower_track_id):
                raise StaleStreamingRelationshipSuggestionError

            detached_final_link_ids: tuple[int, ...] = ()
            if accepted_relationship_type == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT:
                resolver = _lock_equivalence_mutation_tracks(
                    connection,
                    lower_track_id=lower_track_id,
                    higher_track_id=higher_track_id,
                )
                if higher_track_id in resolver.equivalent_group_track_ids(
                    lower_track_id
                ):
                    raise StaleStreamingRelationshipSuggestionError
                conflict = resolver.detect_equivalent_acceptance_conflict(
                    lower_track_id,
                    higher_track_id,
                )
                if conflict is not None:
                    if winning_final_link_id is None:
                        raise StreamingRelationshipAcceptanceConflictError(conflict)
                    detached_final_link_ids = _detached_final_link_ids(
                        conflict,
                        winning_final_link_id,
                    )

            relationship_id = _create_relationship(
                connection,
                lower_track_id=lower_track_id,
                higher_track_id=higher_track_id,
                relationship_type=accepted_relationship_type,
                accepted_at=accepted_at,
            )
            _detach_final_links(connection, detached_final_link_ids)
            connection.execute(
                update(streaming_relationship_suggestions_table)
                .where(streaming_relationship_suggestions_table.c.id == suggestion_id)
                .values(
                    status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
                    accepted_relationship_id=relationship_id,
                    accepted_at=accepted_at,
                )
            )

        return AcceptStreamingRelationshipSuggestionResult(
            suggestion_id=suggestion_id,
            relationship_id=relationship_id,
            relationship_type=accepted_relationship_type,
            accepted_at=accepted_at,
            detached_final_link_ids=detached_final_link_ids,
        )

    def reject(
        self,
        suggestion_id: int,
    ) -> RejectStreamingRelationshipSuggestionResult:
        rejected_at = datetime.now(UTC)

        with self._engine.begin() as connection:
            suggestion = _pending_suggestion_row(connection, suggestion_id)
            if suggestion is None:
                raise StreamingRelationshipSuggestionNotFoundError
            if suggestion["status"] != STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING:
                raise StaleStreamingRelationshipSuggestionError

            lower_track_id = int(suggestion["lower_track_id"])
            higher_track_id = int(suggestion["higher_track_id"])
            resolver = StreamingRelationshipResolver(connection)
            if _is_stale_pending_suggestion(
                connection,
                resolver=resolver,
                lower_track_id=lower_track_id,
                higher_track_id=higher_track_id,
            ):
                raise StaleStreamingRelationshipSuggestionError

            connection.execute(
                update(streaming_relationship_suggestions_table)
                .where(streaming_relationship_suggestions_table.c.id == suggestion_id)
                .values(
                    status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
                    rejected_at=rejected_at,
                )
            )

        return RejectStreamingRelationshipSuggestionResult(
            suggestion_id=suggestion_id,
            rejected_at=rejected_at,
        )

    def generate(self) -> StreamingRelationshipSuggestionGenerationResult:
        return StreamingRelationshipSuggestionGenerator(engine=self._engine).generate()


class StreamingRelationshipStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def create(
        self,
        *,
        first_track_id: int,
        second_track_id: int,
        relationship_type: str,
        winning_final_link_id: int | None = None,
    ) -> StreamingRelationshipMutationResult:
        _validate_relationship_type(relationship_type)
        accepted_at = datetime.now(UTC)

        with self._engine.begin() as connection:
            if not _streaming_tracks_exist(connection, first_track_id, second_track_id):
                raise StreamingRelationshipNotFoundError

            pair = _normalized_pair(first_track_id, second_track_id)
            if _has_existing_relationship(
                connection,
                lower_track_id=pair.lower_track_id,
                higher_track_id=pair.higher_track_id,
            ):
                raise StreamingRelationshipAlreadyExistsError

            detached_final_link_ids = _prepare_relationship_type_change(
                connection,
                lower_track_id=pair.lower_track_id,
                higher_track_id=pair.higher_track_id,
                relationship_type=relationship_type,
                winning_final_link_id=winning_final_link_id,
            )
            relationship_id = _create_relationship(
                connection,
                lower_track_id=pair.lower_track_id,
                higher_track_id=pair.higher_track_id,
                relationship_type=relationship_type,
                accepted_at=accepted_at,
            )
            _detach_final_links(connection, detached_final_link_ids)

        return StreamingRelationshipMutationResult(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            accepted_at=accepted_at,
            detached_final_link_ids=detached_final_link_ids,
        )

    def update(
        self,
        relationship_id: int,
        *,
        relationship_type: str,
        winning_final_link_id: int | None = None,
    ) -> StreamingRelationshipMutationResult:
        _validate_relationship_type(relationship_type)

        with self._engine.begin() as connection:
            relationship = _relationship_row(connection, relationship_id)
            if relationship is None:
                raise StreamingRelationshipNotFoundError

            current_type = str(relationship["relationship_type"])
            lower_track_id = int(relationship["lower_track_id"])
            higher_track_id = int(relationship["higher_track_id"])
            detached_final_link_ids: tuple[int, ...] = ()
            if current_type != relationship_type:
                if current_type == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT:
                    _lock_equivalence_mutation_tracks(
                        connection,
                        lower_track_id=lower_track_id,
                        higher_track_id=higher_track_id,
                    )
                else:
                    detached_final_link_ids = _prepare_relationship_type_change(
                        connection,
                        lower_track_id=lower_track_id,
                        higher_track_id=higher_track_id,
                        relationship_type=relationship_type,
                        winning_final_link_id=winning_final_link_id,
                    )
                connection.execute(
                    update(streaming_relationships_table)
                    .where(streaming_relationships_table.c.id == relationship_id)
                    .values(relationship_type=relationship_type)
                )
                _detach_final_links(connection, detached_final_link_ids)

        return StreamingRelationshipMutationResult(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            accepted_at=relationship["accepted_at"],
            detached_final_link_ids=detached_final_link_ids,
        )

    def delete(self, relationship_id: int) -> StreamingRelationshipMutationResult:
        with self._engine.begin() as connection:
            relationship = _relationship_row(connection, relationship_id)
            if relationship is None:
                raise StreamingRelationshipNotFoundError

            relationship_type = str(relationship["relationship_type"])
            lower_track_id = int(relationship["lower_track_id"])
            higher_track_id = int(relationship["higher_track_id"])
            if relationship_type == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT:
                _lock_equivalence_mutation_tracks(
                    connection,
                    lower_track_id=lower_track_id,
                    higher_track_id=higher_track_id,
                )
            connection.execute(
                delete(streaming_relationships_table).where(
                    streaming_relationships_table.c.id == relationship_id
                )
            )

        return StreamingRelationshipMutationResult(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            accepted_at=None,
            detached_final_link_ids=(),
        )


class _LocalLinkContextFactory:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._rows_by_final_link_id: dict[int, object] = {}

    def for_resolved(
        self,
        resolved: ResolvedStreamingTrackLink | None,
    ) -> StreamingRelationshipLocalLinkContext | None:
        if resolved is None:
            return None

        row = self._row(resolved.final_link_id)
        return StreamingRelationshipLocalLinkContext(
            final_link_id=resolved.final_link_id,
            local_track_id=resolved.local_track_id,
            local_file_path=row["local_file_path"],
            local_title=row["local_title"],
            local_artist=row["local_artist"],
            local_album=row["local_album"],
            streaming_track_id=resolved.streaming_track_id,
            source_streaming_track_id=resolved.source_streaming_track_id,
            resolution_source=resolved.resolution_source,
            approved_at=row["approved_at"],
        )

    def for_final_link(
        self,
        final_link: RelationshipFinalLink,
    ) -> StreamingRelationshipLocalLinkContext:
        row = self._row(final_link.id)
        return StreamingRelationshipLocalLinkContext(
            final_link_id=final_link.id,
            local_track_id=final_link.local_track_id,
            local_file_path=row["local_file_path"],
            local_title=row["local_title"],
            local_artist=row["local_artist"],
            local_album=row["local_album"],
            streaming_track_id=final_link.streaming_track_id,
            source_streaming_track_id=final_link.streaming_track_id,
            resolution_source=RESOLUTION_SOURCE_DIRECT,
            approved_at=final_link.approved_at,
        )

    def prime(self, final_link_ids: Iterable[int]) -> None:
        missing_ids = tuple(
            sorted(
                {
                    int(final_link_id)
                    for final_link_id in final_link_ids
                    if int(final_link_id) not in self._rows_by_final_link_id
                }
            )
        )
        if not missing_ids:
            return

        rows = (
            self._connection.execute(
                select(
                    final_links_table.c.id,
                    final_links_table.c.local_track_id,
                    final_links_table.c.approved_at,
                    local_tracks_table.c.file_path.label("local_file_path"),
                    beets_items_table.c.title.label("local_title"),
                    beets_items_table.c.artist.label("local_artist"),
                    beets_items_table.c.album.label("local_album"),
                )
                .select_from(
                    final_links_table.outerjoin(
                        local_tracks_table,
                        local_tracks_table.c.id == final_links_table.c.local_track_id,
                    ).outerjoin(
                        beets_items_table,
                        beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                    )
                )
                .where(final_links_table.c.id.in_(missing_ids))
            )
            .mappings()
            .all()
        )
        for row in rows:
            self._rows_by_final_link_id[int(row["id"])] = row

    def _row(self, final_link_id: int):
        cached = self._rows_by_final_link_id.get(final_link_id)
        if cached is not None:
            return cached

        self.prime((final_link_id,))
        return self._rows_by_final_link_id[final_link_id]


def _suggestion_resolution_context(
    *,
    row,
    resolver: StreamingRelationshipResolver,
) -> _SuggestionResolutionContext:
    lower_track_id = int(row["lower_track_id"])
    higher_track_id = int(row["higher_track_id"])
    return _SuggestionResolutionContext(
        row=row,
        lower_track_id=lower_track_id,
        higher_track_id=higher_track_id,
        first_resolved_link=resolver.resolve(lower_track_id),
        second_resolved_link=resolver.resolve(higher_track_id),
        conflict=resolver.detect_equivalent_acceptance_conflict(
            lower_track_id,
            higher_track_id,
        ),
    )


def _suggestion_record(
    *,
    context: _SuggestionResolutionContext,
    link_contexts: _LocalLinkContextFactory,
) -> StreamingRelationshipSuggestionRecord:
    row = context.row
    lower_track_id = context.lower_track_id
    higher_track_id = context.higher_track_id
    first_link = link_contexts.for_resolved(context.first_resolved_link)
    second_link = link_contexts.for_resolved(context.second_resolved_link)
    conflict = None
    conflict_state = CONFLICT_STATE_NONE
    detected_conflict = context.conflict
    if detected_conflict is not None:
        conflict_state = CONFLICT_STATE_DIFFERENT_LOCAL_LINKS
        conflict = StreamingRelationshipConflictContext(
            first_group_track_ids=detected_conflict.first_group_track_ids,
            second_group_track_ids=detected_conflict.second_group_track_ids,
            local_track_ids=detected_conflict.local_track_ids,
            final_links=tuple(
                link_contexts.for_final_link(final_link)
                for final_link in detected_conflict.final_links
            ),
        )

    return StreamingRelationshipSuggestionRecord(
        id=int(row["id"]),
        lower_track_id=lower_track_id,
        higher_track_id=higher_track_id,
        relationship_type=str(row["relationship_type"]),
        match_method=str(row["match_method"]),
        score=float(row["score"]),
        confidence=str(row["confidence"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        first_track=_track_record(row, "first", lower_track_id),
        second_track=_track_record(row, "second", higher_track_id),
        first_link=first_link,
        second_link=second_link,
        conflict_state=conflict_state,
        conflict=conflict,
    )


def _track_record(row, prefix: str, track_id: int) -> StreamingRelationshipTrackRecord:
    return StreamingRelationshipTrackRecord(
        id=track_id,
        provider_track_id=row[f"{prefix}_provider_track_id"],
        title=row[f"{prefix}_title"],
        artist=row[f"{prefix}_artist"],
        album=row[f"{prefix}_album"],
        year=row[f"{prefix}_year"],
        isrc=row[f"{prefix}_isrc"],
        duration_ms=row[f"{prefix}_duration_ms"],
    )


def _pending_suggestion_row(connection: Connection, suggestion_id: int):
    return (
        connection.execute(
            select(
                streaming_relationship_suggestions_table.c.id,
                streaming_relationship_suggestions_table.c.lower_track_id,
                streaming_relationship_suggestions_table.c.higher_track_id,
                streaming_relationship_suggestions_table.c.relationship_type,
                streaming_relationship_suggestions_table.c.status,
            )
            .where(streaming_relationship_suggestions_table.c.id == suggestion_id)
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _relationship_row(connection: Connection, relationship_id: int):
    return (
        connection.execute(
            select(
                streaming_relationships_table.c.id,
                streaming_relationships_table.c.lower_track_id,
                streaming_relationships_table.c.higher_track_id,
                streaming_relationships_table.c.relationship_type,
                streaming_relationships_table.c.accepted_at,
            )
            .where(streaming_relationships_table.c.id == relationship_id)
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )


def _streaming_tracks_exist(
    connection: Connection,
    first_track_id: int,
    second_track_id: int,
) -> bool:
    if first_track_id == second_track_id:
        return False

    count = connection.execute(
        select(func.count()).where(
            streaming_tracks_table.c.id.in_((first_track_id, second_track_id))
        )
    ).scalar_one()
    return int(count) == 2


def _normalized_pair(first_track_id: int, second_track_id: int):
    try:
        return normalize_streaming_track_pair(first_track_id, second_track_id)
    except ValueError as exc:
        raise StreamingRelationshipNotFoundError from exc


def _prepare_relationship_type_change(
    connection: Connection,
    *,
    lower_track_id: int,
    higher_track_id: int,
    relationship_type: str,
    winning_final_link_id: int | None,
) -> tuple[int, ...]:
    if relationship_type != STREAMING_RELATIONSHIP_TYPE_EQUIVALENT:
        return ()

    resolver = _lock_equivalence_mutation_tracks(
        connection,
        lower_track_id=lower_track_id,
        higher_track_id=higher_track_id,
    )
    conflict = resolver.detect_equivalent_acceptance_conflict(
        lower_track_id,
        higher_track_id,
    )
    if conflict is None:
        return ()
    if winning_final_link_id is None:
        raise StreamingRelationshipAcceptanceConflictError(conflict)
    return _detached_final_link_ids(conflict, winning_final_link_id)


def _detach_final_links(
    connection: Connection,
    final_link_ids: tuple[int, ...],
) -> None:
    if not final_link_ids:
        return

    detach_final_link_records(connection, final_link_ids)


def _is_stale_pending_suggestion(
    connection: Connection,
    *,
    resolver: StreamingRelationshipResolver,
    lower_track_id: int,
    higher_track_id: int,
    direct_relationships_filtered: bool = False,
) -> bool:
    if not direct_relationships_filtered and _has_existing_relationship(
        connection,
        lower_track_id=lower_track_id,
        higher_track_id=higher_track_id,
    ):
        return True

    return higher_track_id in resolver.equivalent_group_track_ids(lower_track_id)


def _no_existing_relationship_clause():
    existing_relationship = streaming_relationships_table.alias(
        "existing_suggestion_relationship"
    )
    return (
        ~select(existing_relationship.c.id)
        .where(
            existing_relationship.c.lower_track_id
            == streaming_relationship_suggestions_table.c.lower_track_id,
            existing_relationship.c.higher_track_id
            == streaming_relationship_suggestions_table.c.higher_track_id,
        )
        .exists()
    )


def _has_existing_relationship(
    connection: Connection,
    *,
    lower_track_id: int,
    higher_track_id: int,
) -> bool:
    existing_relationship_id = (
        connection.execute(
            select(streaming_relationships_table.c.id)
            .where(
                streaming_relationships_table.c.lower_track_id == lower_track_id,
                streaming_relationships_table.c.higher_track_id == higher_track_id,
            )
            .limit(1)
        )
        .scalars()
        .one_or_none()
    )
    return existing_relationship_id is not None


def _detached_final_link_ids(
    conflict: EquivalentAcceptanceConflict,
    winning_final_link_id: int,
) -> tuple[int, ...]:
    conflict_final_link_ids = {link.id for link in conflict.final_links}
    if winning_final_link_id not in conflict_final_link_ids:
        raise InvalidWinningFinalLinkError

    return tuple(
        sorted(
            link.id for link in conflict.final_links if link.id != winning_final_link_id
        )
    )


def _lock_equivalence_mutation_tracks(
    connection: Connection,
    *,
    lower_track_id: int,
    higher_track_id: int,
) -> StreamingRelationshipResolver:
    resolver = StreamingRelationshipResolver(connection)
    locked_track_ids = tuple(
        sorted(
            {
                *resolver.equivalent_group_track_ids(lower_track_id),
                *resolver.equivalent_group_track_ids(higher_track_id),
            }
        )
    )
    connection.execute(
        select(streaming_tracks_table.c.id)
        .where(streaming_tracks_table.c.id.in_(locked_track_ids))
        .order_by(streaming_tracks_table.c.id.asc())
        .with_for_update()
    ).all()
    return StreamingRelationshipResolver(connection)


def _create_relationship(
    connection: Connection,
    *,
    lower_track_id: int,
    higher_track_id: int,
    relationship_type: str,
    accepted_at: datetime,
) -> int:
    pair = normalize_streaming_track_pair(lower_track_id, higher_track_id)
    relationship_id = connection.execute(
        insert(streaming_relationships_table).values(
            lower_track_id=pair.lower_track_id,
            higher_track_id=pair.higher_track_id,
            relationship_type=relationship_type,
            accepted_at=accepted_at,
        )
    ).inserted_primary_key[0]
    if not isinstance(relationship_id, int):
        raise ValueError("Failed to persist streaming relationship")
    return relationship_id


def _validate_relationship_type(relationship_type: str) -> None:
    if relationship_type not in STREAMING_RELATIONSHIP_TYPES:
        raise ValueError(
            f"Unsupported streaming relationship type: {relationship_type}"
        )
