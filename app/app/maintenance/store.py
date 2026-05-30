from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.ingestion.failures import failed_ingestion_attempts_table
from app.ingestion.pipeline import SUPPORTED_AUDIO_EXTENSIONS
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table


@dataclass(frozen=True, slots=True)
class UnidentifiedTrackRecord:
    id: int
    attempt_count: int
    can_rematch_local_track: bool
    can_rescue_metadata: bool
    failed_at: str
    failure_reason: str
    filename: str
    first_failed_at: str
    ignored_at: str | None
    local_track_id: int | None
    source_mtime_ns: int | None
    source_path: str
    source_size: int | None


class MaintenanceStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def list_unidentified(self) -> list[UnidentifiedTrackRecord]:
        query = (
            select(
                failed_ingestion_attempts_table.c.id,
                failed_ingestion_attempts_table.c.attempt_count,
                final_links_table.c.id.label("final_link_id"),
                failed_ingestion_attempts_table.c.failed_at,
                failed_ingestion_attempts_table.c.failure_reason,
                failed_ingestion_attempts_table.c.filename,
                failed_ingestion_attempts_table.c.first_failed_at,
                failed_ingestion_attempts_table.c.ignored_at,
                local_tracks_table.c.id.label("existing_local_track_id"),
                failed_ingestion_attempts_table.c.local_track_id,
                failed_ingestion_attempts_table.c.source_mtime_ns,
                failed_ingestion_attempts_table.c.source_path,
                failed_ingestion_attempts_table.c.source_size,
            )
            .select_from(
                failed_ingestion_attempts_table.outerjoin(
                    local_tracks_table,
                    local_tracks_table.c.id
                    == failed_ingestion_attempts_table.c.local_track_id,
                ).outerjoin(
                    final_links_table,
                    final_links_table.c.local_track_id == local_tracks_table.c.id,
                )
            )
            .order_by(
                failed_ingestion_attempts_table.c.ignored_at.is_not(None).asc(),
                failed_ingestion_attempts_table.c.failed_at.desc(),
                failed_ingestion_attempts_table.c.id.desc(),
            )
        )

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()

        return [
            UnidentifiedTrackRecord(
                id=row["id"],
                attempt_count=row["attempt_count"],
                can_rematch_local_track=(
                    row["existing_local_track_id"] is not None
                    and row["final_link_id"] is None
                ),
                can_rescue_metadata=row["final_link_id"] is not None,
                failed_at=row["failed_at"].isoformat(),
                failure_reason=row["failure_reason"],
                filename=row["filename"],
                first_failed_at=row["first_failed_at"].isoformat(),
                ignored_at=(
                    row["ignored_at"].isoformat()
                    if row["ignored_at"] is not None
                    else None
                ),
                local_track_id=row["local_track_id"],
                source_mtime_ns=row["source_mtime_ns"],
                source_path=row["source_path"],
                source_size=row["source_size"],
            )
            for row in rows
            if _is_supported_audio_filename(row["filename"])
        ]


def _is_supported_audio_filename(filename: str) -> bool:
    return any(
        filename.lower().endswith(extension) for extension in SUPPORTED_AUDIO_EXTENSIONS
    )
