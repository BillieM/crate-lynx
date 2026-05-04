from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
)


metadata = MetaData()

failed_ingestion_attempts_table = Table(
    "failed_ingestion_attempts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_path", String, nullable=False),
    Column("filename", String, nullable=False),
    Column("fingerprint", String, nullable=True),
    Column("failure_reason", String, nullable=False),
    Column(
        "failed_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column("local_track_id", Integer, nullable=True),
)


@dataclass(frozen=True, slots=True)
class FailedIngestionAttempt:
    id: int
    source_path: str
    filename: str
    fingerprint: str | None
    failure_reason: str
    failed_at: datetime
    local_track_id: int | None


class FailedIngestionAttemptStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def persist(
        self,
        *,
        source_path: Path | str,
        fingerprint: str | None,
        failure_reason: str,
        local_track_id: int | None = None,
        failed_at: datetime | None = None,
    ) -> None:
        path = Path(source_path)
        with self._engine.begin() as connection:
            connection.execute(
                insert(failed_ingestion_attempts_table).values(
                    source_path=str(path),
                    filename=path.name,
                    fingerprint=fingerprint,
                    failure_reason=failure_reason,
                    failed_at=failed_at or datetime.now(UTC),
                    local_track_id=local_track_id,
                )
            )
