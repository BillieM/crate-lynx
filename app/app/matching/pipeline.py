from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import (
    and_,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    column,
    create_engine,
    delete,
    func,
    insert,
    select,
    table,
)
from sqlalchemy.engine import Engine

from app.matching.isrc import IsrcMatcher
from app.matching.models import MatchResult
from app.matching.tags import TagMatcher


TAG_SHORTLIST_LIMIT = 3
TAG_PLAUSIBLE_SCORE_THRESHOLD = 0.5
TAG_FALLBACK_LIMIT = 2

SUGGESTED_LINK_STATUS_PENDING = "pending"
SUGGESTED_LINK_STATUS_APPROVED = "approved"
SUGGESTED_LINK_STATUS_REJECTED = "rejected"

metadata = MetaData()

suggested_links_table = Table(
    "suggested_links",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("local_track_id", Integer, nullable=False),
    Column("streaming_track_id", Integer, nullable=False),
    Column("match_method", String, nullable=False),
    Column("score", Float, nullable=False),
    Column("status", String, nullable=False),
    Column("rejected_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
)

final_links_view = table("final_links", column("local_track_id"))


@dataclass(slots=True)
class SuggestedLinkStore:
    database_url: str | None = None
    engine: Engine | None = None
    _engine: Engine = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.engine is None:
            if self.database_url is None:
                raise ValueError("database_url or engine is required")
            self._engine = create_engine(self.database_url)
            return
        self._engine = self.engine

    def clear_non_approved_for_track(self, local_track_id: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                delete(suggested_links_table).where(
                    suggested_links_table.c.local_track_id == local_track_id,
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                )
            )

    def delete_pending_for_linked_tracks(self) -> int:
        with self._engine.begin() as connection:
            result = connection.execute(
                delete(suggested_links_table).where(
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                    suggested_links_table.c.local_track_id.in_(
                        select(final_links_view.c.local_track_id)
                    ),
                )
            )

        return result.rowcount or 0

    def has_rejected_pair(self, local_track_id: int, streaming_track_id: int) -> bool:
        with self._engine.connect() as connection:
            rejected_pair = connection.execute(
                select(suggested_links_table.c.id)
                .where(
                    and_(
                        suggested_links_table.c.local_track_id == local_track_id,
                        suggested_links_table.c.streaming_track_id
                        == streaming_track_id,
                        suggested_links_table.c.status
                        == SUGGESTED_LINK_STATUS_REJECTED,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()

        return rejected_pair is not None

    def rejected_streaming_track_ids(self, local_track_id: int) -> set[int]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(suggested_links_table.c.streaming_track_id).where(
                    suggested_links_table.c.local_track_id == local_track_id,
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_REJECTED,
                )
            )
            return {
                streaming_track_id
                for streaming_track_id in rows.scalars()
                if isinstance(streaming_track_id, int)
            }

    def persist(self, result: MatchResult) -> bool:
        if self.has_rejected_pair(result.local_track_id, result.streaming_track_id):
            return False

        self.clear_non_approved_for_track(result.local_track_id)

        with self._engine.begin() as connection:
            connection.execute(
                insert(suggested_links_table).values(
                    local_track_id=result.local_track_id,
                    streaming_track_id=result.streaming_track_id,
                    match_method=result.match_method,
                    score=result.score,
                    status=SUGGESTED_LINK_STATUS_PENDING,
                )
            )

        return True

    def persist_many(self, results: list[MatchResult]) -> list[MatchResult]:
        if not results:
            return []

        local_track_id = results[0].local_track_id
        accepted = [
            result
            for result in results
            if result.local_track_id == local_track_id
            and not self.has_rejected_pair(
                result.local_track_id,
                result.streaming_track_id,
            )
        ]
        if not accepted:
            return []

        self.clear_non_approved_for_track(local_track_id)
        with self._engine.begin() as connection:
            connection.execute(
                insert(suggested_links_table),
                [
                    {
                        "local_track_id": result.local_track_id,
                        "streaming_track_id": result.streaming_track_id,
                        "match_method": result.match_method,
                        "score": result.score,
                        "status": SUGGESTED_LINK_STATUS_PENDING,
                    }
                    for result in accepted
                ],
            )

        return accepted


@dataclass(slots=True)
class MatchingPipeline:
    database_url: str
    beets_library: Path | str
    redis_url: str | None = None
    isrc_matcher: IsrcMatcher | None = None
    tag_matcher: TagMatcher | None = None
    suggestion_store: SuggestedLinkStore | None = None

    def __post_init__(self) -> None:
        if self.isrc_matcher is None:
            self.isrc_matcher = IsrcMatcher(
                database_url=self.database_url,
                beets_library=self.beets_library,
            )
        if self.tag_matcher is None:
            self.tag_matcher = TagMatcher(
                database_url=self.database_url,
                beets_library=self.beets_library,
            )
        if self.suggestion_store is None:
            self.suggestion_store = SuggestedLinkStore(self.database_url)

    def run(self, local_track_id: int) -> MatchResult | None:
        result = self.isrc_matcher.match(local_track_id)
        if result is not None:
            if self.suggestion_store.persist(result):
                return result

        rejected_streaming_track_ids = (
            self.suggestion_store.rejected_streaming_track_ids(local_track_id)
        )
        candidates = self.tag_matcher.candidates(
            local_track_id,
            excluded_streaming_track_ids=rejected_streaming_track_ids,
            limit=TAG_SHORTLIST_LIMIT,
        )
        if not candidates:
            return None

        persisted = self.suggestion_store.persist_many(
            _persistable_tag_candidates(candidates)
        )
        return persisted[0] if persisted else None


def fetch_suggested_links(database_url: str) -> list[dict[str, object]]:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = connection.execute(
            select(
                suggested_links_table.c.local_track_id,
                suggested_links_table.c.streaming_track_id,
                suggested_links_table.c.match_method,
                suggested_links_table.c.score,
                suggested_links_table.c.status,
            ).order_by(suggested_links_table.c.id.asc())
        ).mappings()
        return [dict(row) for row in rows]


def _persistable_tag_candidates(candidates: list[MatchResult]) -> list[MatchResult]:
    plausible = [
        candidate
        for candidate in candidates
        if candidate.score >= TAG_PLAUSIBLE_SCORE_THRESHOLD
    ]
    if plausible:
        return plausible

    return candidates[:TAG_FALLBACK_LIMIT]
