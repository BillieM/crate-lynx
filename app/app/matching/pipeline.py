from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path

from redis import Redis
from rq import Queue
from sqlalchemy import (
    and_,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from app.matching.isrc import IsrcMatcher
from app.matching.models import ConfidenceBand, MatchResult
from app.matching.tags import TagMatcher


logger = logging.getLogger(__name__)

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


@dataclass(slots=True)
class AcousticJobEnqueuer:
    redis_url: str
    queue_name: str = "matching"
    job_timeout: str = "10m"

    def enqueue(self, local_track_id: int, candidates: list[dict[str, object]]) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            "app.matching.run_acoustic_match_job",
            local_track_id,
            candidates,
            job_timeout=self.job_timeout,
        )
        return job.id


@dataclass(slots=True)
class SuggestedLinkStore:
    database_url: str
    _engine: Engine = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._engine = create_engine(self.database_url)

    def clear_non_approved_for_track(self, local_track_id: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                delete(suggested_links_table).where(
                    suggested_links_table.c.local_track_id == local_track_id,
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                )
            )

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


@dataclass(slots=True)
class MatchingPipeline:
    database_url: str
    beets_library: Path | str
    redis_url: str | None = None
    isrc_matcher: IsrcMatcher | None = None
    tag_matcher: TagMatcher | None = None
    suggestion_store: SuggestedLinkStore | None = None
    acoustic_job_enqueuer: AcousticJobEnqueuer | None = None

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
        if self.acoustic_job_enqueuer is None and self.redis_url is not None:
            self.acoustic_job_enqueuer = AcousticJobEnqueuer(self.redis_url)

    def run(self, local_track_id: int) -> MatchResult | None:
        result = self.isrc_matcher.match(local_track_id)
        if result is not None:
            if self.suggestion_store.persist(result):
                return result

        result = self.tag_matcher.match(local_track_id)
        if result is None:
            return None

        if not self.suggestion_store.persist(result):
            return None

        if result.confidence_band is ConfidenceBand.LOW:
            self._enqueue_acoustic_fallback(local_track_id, result)

        return result

    def _enqueue_acoustic_fallback(
        self, local_track_id: int, result: MatchResult
    ) -> None:
        if self.acoustic_job_enqueuer is None:
            logger.warning(
                "Skipping acoustic fallback enqueue for local_track_id=%s because "
                "REDIS_URL is not configured",
                local_track_id,
            )
            return

        candidates = self._build_acoustic_candidates(result)
        self.acoustic_job_enqueuer.enqueue(local_track_id, candidates)

    def _build_acoustic_candidates(
        self, result: MatchResult
    ) -> list[dict[str, object]]:
        return [
            {
                "streaming_track_id": result.streaming_track_id,
                # Fingerprint population is not available yet in the streaming model.
                "fingerprint": "",
            }
        ]


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
