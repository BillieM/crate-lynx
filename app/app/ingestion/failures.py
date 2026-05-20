from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine

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
        "first_failed_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    Column(
        "failed_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column("attempt_count", Integer, server_default="1", nullable=False),
    Column("source_size", BigInteger, nullable=True),
    Column("source_mtime_ns", BigInteger, nullable=True),
    Column("ignored_at", DateTime(timezone=True), nullable=True),
    Column("local_track_id", Integer, nullable=True),
    UniqueConstraint("source_path", name="uq_failed_ingestion_attempts_source_path"),
)


@dataclass(frozen=True, slots=True)
class FailedIngestionAttempt:
    id: int
    source_path: str
    filename: str
    fingerprint: str | None
    failure_reason: str
    first_failed_at: datetime
    failed_at: datetime
    attempt_count: int
    source_size: int | None
    source_mtime_ns: int | None
    ignored_at: datetime | None
    local_track_id: int | None


@dataclass(frozen=True, slots=True)
class SourceFileSignature:
    size: int
    mtime_ns: int


class FailedIngestionAttemptStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def persist(
        self,
        *,
        source_path: Path | str,
        fingerprint: str | None,
        failure_reason: str,
        local_track_id: int | None = None,
        failed_at: datetime | None = None,
    ) -> None:
        path = _normalize_source_path(source_path)
        failed_at_value = failed_at or datetime.now(UTC)
        signature = _source_file_signature(path)
        values = {
            "source_path": str(path),
            "filename": path.name,
            "fingerprint": fingerprint,
            "failure_reason": failure_reason,
            "first_failed_at": failed_at_value,
            "failed_at": failed_at_value,
            "attempt_count": 1,
            "source_size": signature.size if signature is not None else None,
            "source_mtime_ns": signature.mtime_ns if signature is not None else None,
            "ignored_at": None,
            "local_track_id": local_track_id,
        }
        with self._engine.begin() as connection:
            dialect_name = connection.dialect.name
            if dialect_name == "postgresql":
                statement = postgresql_insert(failed_ingestion_attempts_table).values(
                    values
                )
                connection.execute(_with_conflict_update(statement))
            elif dialect_name == "sqlite":
                statement = sqlite_insert(failed_ingestion_attempts_table).values(
                    values
                )
                connection.execute(_with_conflict_update(statement))
            else:
                existing_id = connection.execute(
                    select(failed_ingestion_attempts_table.c.id).where(
                        failed_ingestion_attempts_table.c.source_path == str(path)
                    )
                ).scalar_one_or_none()
                if existing_id is None:
                    connection.execute(
                        insert(failed_ingestion_attempts_table).values(values)
                    )
                else:
                    connection.execute(
                        update(failed_ingestion_attempts_table)
                        .where(failed_ingestion_attempts_table.c.id == existing_id)
                        .values(_manual_update_values(values))
                    )

    def get(self, attempt_id: int) -> FailedIngestionAttempt | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(failed_ingestion_attempts_table).where(
                        failed_ingestion_attempts_table.c.id == attempt_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        return _row_to_failed_attempt(row) if row is not None else None

    def clear_for_source_path(self, source_path: Path | str) -> int:
        path = _normalize_source_path(source_path)
        with self._engine.begin() as connection:
            result = connection.execute(
                delete(failed_ingestion_attempts_table).where(
                    failed_ingestion_attempts_table.c.source_path == str(path)
                )
            )

        return result.rowcount or 0

    def mark_ignored(
        self,
        attempt_id: int,
        *,
        ignored_at: datetime | None = None,
    ) -> FailedIngestionAttempt | None:
        ignored_at_value = ignored_at or datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(failed_ingestion_attempts_table).where(
                        failed_ingestion_attempts_table.c.id == attempt_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            signature = _source_file_signature(Path(row["source_path"]))
            if (
                signature is not None
                and row["source_size"] is not None
                and row["source_mtime_ns"] is not None
                and (
                    row["source_size"] != signature.size
                    or row["source_mtime_ns"] != signature.mtime_ns
                )
            ):
                connection.execute(
                    delete(failed_ingestion_attempts_table).where(
                        failed_ingestion_attempts_table.c.id == attempt_id
                    )
                )
                return None

            values: dict[str, object] = {"ignored_at": ignored_at_value}
            if signature is not None:
                values["source_size"] = signature.size
                values["source_mtime_ns"] = signature.mtime_ns

            connection.execute(
                update(failed_ingestion_attempts_table)
                .where(failed_ingestion_attempts_table.c.id == attempt_id)
                .values(values)
            )
            updated = (
                connection.execute(
                    select(failed_ingestion_attempts_table).where(
                        failed_ingestion_attempts_table.c.id == attempt_id
                    )
                )
                .mappings()
                .one()
            )

        return _row_to_failed_attempt(updated)

    def restore(self, attempt_id: int) -> FailedIngestionAttempt | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(failed_ingestion_attempts_table).where(
                        failed_ingestion_attempts_table.c.id == attempt_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            connection.execute(
                update(failed_ingestion_attempts_table)
                .where(failed_ingestion_attempts_table.c.id == attempt_id)
                .values(ignored_at=None)
            )
            updated = (
                connection.execute(
                    select(failed_ingestion_attempts_table).where(
                        failed_ingestion_attempts_table.c.id == attempt_id
                    )
                )
                .mappings()
                .one()
            )

        return _row_to_failed_attempt(updated)

    def should_skip_auto_enqueue(self, source_path: Path | str) -> bool:
        path = _normalize_source_path(source_path)
        signature = _source_file_signature(path)
        if signature is None:
            return False

        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        failed_ingestion_attempts_table.c.id,
                        failed_ingestion_attempts_table.c.source_size,
                        failed_ingestion_attempts_table.c.source_mtime_ns,
                    ).where(failed_ingestion_attempts_table.c.source_path == str(path))
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return False

            if row["source_size"] is None or row["source_mtime_ns"] is None:
                connection.execute(
                    update(failed_ingestion_attempts_table)
                    .where(failed_ingestion_attempts_table.c.id == row["id"])
                    .values(
                        source_size=signature.size,
                        source_mtime_ns=signature.mtime_ns,
                    )
                )
                return True

            if (
                row["source_size"] == signature.size
                and row["source_mtime_ns"] == signature.mtime_ns
            ):
                return True

            connection.execute(
                delete(failed_ingestion_attempts_table).where(
                    failed_ingestion_attempts_table.c.id == row["id"]
                )
            )

        return False


def _with_conflict_update(statement):
    excluded = statement.excluded
    return statement.on_conflict_do_update(
        index_elements=[failed_ingestion_attempts_table.c.source_path],
        set_={
            "filename": excluded.filename,
            "fingerprint": excluded.fingerprint,
            "failure_reason": excluded.failure_reason,
            "failed_at": excluded.failed_at,
            "attempt_count": failed_ingestion_attempts_table.c.attempt_count + 1,
            "source_size": excluded.source_size,
            "source_mtime_ns": excluded.source_mtime_ns,
            "ignored_at": None,
            "local_track_id": excluded.local_track_id,
        },
    )


def _manual_update_values(values: dict[str, object]) -> dict[str, object]:
    return {
        "filename": values["filename"],
        "fingerprint": values["fingerprint"],
        "failure_reason": values["failure_reason"],
        "failed_at": values["failed_at"],
        "attempt_count": failed_ingestion_attempts_table.c.attempt_count + 1,
        "source_size": values["source_size"],
        "source_mtime_ns": values["source_mtime_ns"],
        "ignored_at": None,
        "local_track_id": values["local_track_id"],
    }


def _row_to_failed_attempt(row) -> FailedIngestionAttempt:
    return FailedIngestionAttempt(
        id=row["id"],
        source_path=row["source_path"],
        filename=row["filename"],
        fingerprint=row["fingerprint"],
        failure_reason=row["failure_reason"],
        first_failed_at=row["first_failed_at"],
        failed_at=row["failed_at"],
        attempt_count=row["attempt_count"],
        source_size=row["source_size"],
        source_mtime_ns=row["source_mtime_ns"],
        ignored_at=row["ignored_at"],
        local_track_id=row["local_track_id"],
    )


def _normalize_source_path(source_path: Path | str) -> Path:
    return Path(source_path).expanduser().resolve(strict=False)


def _source_file_signature(path: Path) -> SourceFileSignature | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None

    if not path.is_file():
        return None

    return SourceFileSignature(
        size=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
    )
