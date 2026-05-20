from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.ingestion.failures import failed_ingestion_attempts_table
from app.ingestion.pipeline import SUPPORTED_AUDIO_EXTENSIONS
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


@dataclass(frozen=True, slots=True)
class MissingLocallyTrackRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    playlist_count: int
    playlist_ids: list[int]
    playlist_titles: list[str]


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


@dataclass(slots=True)
class _MissingLocallyAccumulator:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    playlist_titles_by_id: dict[int, str] = field(default_factory=dict)

    def to_record(self) -> MissingLocallyTrackRecord:
        return MissingLocallyTrackRecord(
            id=self.id,
            provider_track_id=self.provider_track_id,
            title=self.title,
            artist=self.artist,
            album=self.album,
            duration_ms=self.duration_ms,
            playlist_count=len(self.playlist_titles_by_id),
            playlist_ids=list(self.playlist_titles_by_id.keys()),
            playlist_titles=list(self.playlist_titles_by_id.values()),
        )


class MaintenanceStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def list_missing_locally(self) -> list[MissingLocallyTrackRecord]:
        query = (
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.provider_track_id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.duration_ms,
                streaming_playlists_table.c.id.label("playlist_id"),
                streaming_playlists_table.c.title.label("playlist_title"),
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
                streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL,
            )
            .order_by(
                streaming_tracks_table.c.id.asc(),
                streaming_playlists_table.c.title.asc(),
                streaming_playlists_table.c.id.asc(),
            )
        )

        tracks_by_id: dict[int, _MissingLocallyAccumulator] = {}
        with self._engine.connect() as connection:
            from app.relationships.resolver import StreamingRelationshipResolver

            resolver = StreamingRelationshipResolver(connection)
            for row in connection.execute(query).mappings():
                if resolver.resolve(int(row["id"])) is not None:
                    continue

                track = tracks_by_id.setdefault(
                    row["id"],
                    _MissingLocallyAccumulator(
                        id=row["id"],
                        provider_track_id=row["provider_track_id"],
                        title=row["title"],
                        artist=row["artist"],
                        album=row["album"],
                        duration_ms=row["duration_ms"],
                    ),
                )
                if row["playlist_id"] is not None:
                    track.playlist_titles_by_id[row["playlist_id"]] = row[
                        "playlist_title"
                    ]

        return [track.to_record() for track in tracks_by_id.values()]

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
