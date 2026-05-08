from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    column,
    func,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine

metadata = MetaData()

local_tracks_table = Table(
    "local_tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("file_path", String, nullable=False),
    Column("library_root_rel_path", String, nullable=False),
    Column("fingerprint", String, nullable=True),
    Column("beets_id", Integer, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint("beets_id", name="uq_local_tracks_beets_id"),
    Index("ix_local_tracks_fingerprint", "fingerprint"),
    Index("ix_local_tracks_beets_id", "beets_id"),
)

SUGGESTED_LINK_STATUS_PENDING = "pending"
final_links_view = table(
    "final_links",
    column("id"),
    column("local_track_id"),
    column("streaming_track_id"),
    column("approved_at"),
)
suggested_links_view = table(
    "suggested_links",
    column("id"),
    column("local_track_id"),
    column("streaming_track_id"),
    column("match_method"),
    column("score"),
    column("status"),
    column("created_at"),
)
failed_ingestion_attempts_view = table(
    "failed_ingestion_attempts",
    column("id"),
    column("source_path"),
    column("filename"),
    column("failure_reason"),
    column("failed_at"),
    column("local_track_id"),
)


@dataclass(slots=True)
class PersistedLocalTrack:
    id: int
    file_path: str


@dataclass(frozen=True, slots=True)
class LocalTrackFinalLinkRecord:
    id: int
    streaming_track_id: int
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class LocalTrackSuggestionRecord:
    id: int
    streaming_track_id: int
    match_method: str
    score: float
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LocalTrackFailedIngestionRecord:
    id: int
    source_path: str
    filename: str
    failure_reason: str
    failed_at: datetime


@dataclass(frozen=True, slots=True)
class LocalTrackDetailRecord:
    id: int
    file_path: str
    library_root_rel_path: str
    link_status: str
    final_link: LocalTrackFinalLinkRecord | None
    pending_suggestions: list[LocalTrackSuggestionRecord]
    failed_ingestion_attempts: list[LocalTrackFailedIngestionRecord]


class LocalTrackStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def persist(
        self,
        *,
        library_root: Path | str,
        library_path: Path | str,
        fingerprint: str | None,
        beets_id: int | None,
    ) -> PersistedLocalTrack:
        relative_path = _relative_library_path(library_root, library_path)

        with self._engine.begin() as connection:
            statement = _conflict_insert(
                local_tracks_table,
                connection.dialect.name,
            ).values(
                file_path=relative_path,
                library_root_rel_path=relative_path,
                fingerprint=fingerprint,
                beets_id=beets_id,
            )
            row = (
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[local_tracks_table.c.beets_id],
                        set_={
                            "file_path": statement.excluded.file_path,
                            "library_root_rel_path": (
                                statement.excluded.library_root_rel_path
                            ),
                            "fingerprint": statement.excluded.fingerprint,
                            "updated_at": func.now(),
                        },
                    ).returning(
                        local_tracks_table.c.id,
                        local_tracks_table.c.file_path,
                    )
                )
                .mappings()
                .one()
            )

        return PersistedLocalTrack(id=row["id"], file_path=row["file_path"])

    def get_detail(self, local_track_id: int) -> LocalTrackDetailRecord | None:
        with self._engine.connect() as connection:
            local_track = (
                connection.execute(
                    select(
                        local_tracks_table.c.id,
                        local_tracks_table.c.file_path,
                        local_tracks_table.c.library_root_rel_path,
                    ).where(local_tracks_table.c.id == local_track_id)
                )
                .mappings()
                .one_or_none()
            )

            if local_track is None:
                return None

            final_link_row = (
                connection.execute(
                    select(
                        final_links_view.c.id,
                        final_links_view.c.streaming_track_id,
                        final_links_view.c.approved_at,
                    ).where(final_links_view.c.local_track_id == local_track_id)
                )
                .mappings()
                .one_or_none()
            )
            suggestion_rows = (
                connection.execute(
                    select(
                        suggested_links_view.c.id,
                        suggested_links_view.c.streaming_track_id,
                        suggested_links_view.c.match_method,
                        suggested_links_view.c.score,
                        suggested_links_view.c.status,
                        suggested_links_view.c.created_at,
                    )
                    .where(
                        suggested_links_view.c.local_track_id == local_track_id,
                        suggested_links_view.c.status == SUGGESTED_LINK_STATUS_PENDING,
                    )
                    .order_by(
                        suggested_links_view.c.score.desc(),
                        suggested_links_view.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )
            failed_ingestion_rows = (
                connection.execute(
                    select(
                        failed_ingestion_attempts_view.c.id,
                        failed_ingestion_attempts_view.c.source_path,
                        failed_ingestion_attempts_view.c.filename,
                        failed_ingestion_attempts_view.c.failure_reason,
                        failed_ingestion_attempts_view.c.failed_at,
                    )
                    .where(
                        failed_ingestion_attempts_view.c.local_track_id
                        == local_track_id
                    )
                    .order_by(
                        failed_ingestion_attempts_view.c.failed_at.desc(),
                        failed_ingestion_attempts_view.c.id.desc(),
                    )
                    .limit(5)
                )
                .mappings()
                .all()
            )

        final_link = (
            LocalTrackFinalLinkRecord(
                id=final_link_row["id"],
                streaming_track_id=final_link_row["streaming_track_id"],
                approved_at=final_link_row["approved_at"],
            )
            if final_link_row is not None
            else None
        )
        pending_suggestions = [
            LocalTrackSuggestionRecord(
                id=row["id"],
                streaming_track_id=row["streaming_track_id"],
                match_method=row["match_method"],
                score=row["score"],
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in suggestion_rows
        ]

        if final_link is not None:
            link_status = "linked"
        elif pending_suggestions:
            link_status = "pending"
        else:
            link_status = "unlinked"

        return LocalTrackDetailRecord(
            id=local_track["id"],
            file_path=local_track["file_path"],
            library_root_rel_path=local_track["library_root_rel_path"],
            link_status=link_status,
            final_link=final_link,
            pending_suggestions=pending_suggestions,
            failed_ingestion_attempts=[
                LocalTrackFailedIngestionRecord(
                    id=row["id"],
                    source_path=row["source_path"],
                    filename=row["filename"],
                    failure_reason=row["failure_reason"],
                    failed_at=row["failed_at"],
                )
                for row in failed_ingestion_rows
            ],
        )


def _conflict_insert(target_table, dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql_insert(target_table)
    if dialect_name == "sqlite":
        return sqlite_insert(target_table)
    raise ValueError(
        f"Unsupported database dialect for local track upsert: {dialect_name}"
    )


def _relative_library_path(library_root: Path | str, library_path: Path | str) -> str:
    library_root_path = Path(library_root).resolve()
    track_path = Path(library_path).resolve()
    return str(track_path.relative_to(library_root_path))
