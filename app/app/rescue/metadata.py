from __future__ import annotations

from dataclasses import dataclass
import mimetypes
import os
from pathlib import Path
import sqlite3
from typing import Literal
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.engine import Engine
from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPE1, ID3, ID3NoHeaderError

from app.core.db import create_database_engine
from app.ingestion.beets_mirror_sync import (
    decode_beets_path,
    read_album,
    read_item,
    upsert_album,
    upsert_item,
)
from app.ingestion.failures import (
    FailedIngestionAttemptStore,
    failed_ingestion_attempts_table,
)
from app.ingestion.pipeline import beets_library_lock
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.streaming.adapters.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicTrackMetadata,
)
from app.streaming.models import (
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.store import StreamingAccountStore


class MetadataRescueError(RuntimeError):
    """Raised when local metadata rescue cannot be completed."""


class MetadataRescueConflictError(MetadataRescueError):
    """Raised when the failed attempt to resolve is ambiguous or mismatched."""


@dataclass(frozen=True, slots=True)
class RescueMetadata:
    title: str
    artist: str
    album: str | None
    year: int | None
    album_art_url: str | None


@dataclass(frozen=True, slots=True)
class ArtworkPayload:
    data: bytes
    mime_type: str
    description: str = "Cover"
    picture_type: int = 3


RescueStageStatus = Literal["succeeded", "failed", "skipped", "not_applicable"]


@dataclass(frozen=True, slots=True)
class RescueStageResult:
    name: str
    status: RescueStageStatus
    detail: str


@dataclass(frozen=True, slots=True)
class MetadataRescueResult:
    local_track_id: int
    file_path: str
    beets_id: int | None
    failed_attempt_id: int | None
    metadata: RescueMetadata | None
    stages: tuple[RescueStageResult, ...]

    @property
    def completed(self) -> bool:
        return all(stage.status not in {"failed", "skipped"} for stage in self.stages)

    @property
    def partial_failure(self) -> bool:
        mutation_names = {
            "file_tags",
            "beets_catalogue",
            "postgres_mirror",
            "failed_attempt",
        }
        mutation_succeeded = any(
            stage.name in mutation_names and stage.status == "succeeded"
            for stage in self.stages
        )
        return mutation_succeeded and any(
            stage.status == "failed" for stage in self.stages
        )


def rescue_metadata(
    local_track_id: int,
    *,
    failed_attempt_id: int | None = None,
    database_url: str | None = None,
    engine: Engine | None = None,
    library_root: Path | str | None = None,
    beets_library: Path | str | None = None,
    beets_import_lock_path: Path | str | None = None,
) -> MetadataRescueResult:
    resolved_database_url = database_url or os.environ.get("DATABASE_URL")
    if engine is None and not resolved_database_url:
        raise MetadataRescueError("DATABASE_URL must be configured for metadata rescue")

    resolved_library_root = Path(
        library_root or os.environ.get("LIBRARY_ROOT", "/nas/media/music")
    )
    resolved_beets_library = Path(
        beets_library or os.environ.get("BEETS_LIBRARY", "/data/beets/library.db")
    )
    resolved_beets_import_lock_path = beets_import_lock_path or os.environ.get(
        "BEETS_IMPORT_LOCK_PATH"
    )
    engine = engine or create_database_engine(resolved_database_url)

    with engine.connect() as connection:
        row = (
            connection.execute(
                select(
                    local_tracks_table.c.file_path,
                    local_tracks_table.c.beets_id,
                    streaming_tracks_table.c.provider_track_id,
                    streaming_tracks_table.c.title,
                    streaming_tracks_table.c.artist,
                    streaming_tracks_table.c.album,
                    streaming_tracks_table.c.year,
                    streaming_playlists_table.c.account_id,
                )
                .select_from(
                    final_links_table.join(
                        local_tracks_table,
                        local_tracks_table.c.id == final_links_table.c.local_track_id,
                    )
                    .join(
                        streaming_tracks_table,
                        streaming_tracks_table.c.id
                        == final_links_table.c.streaming_track_id,
                    )
                    .outerjoin(
                        playlist_membership_table,
                        playlist_membership_table.c.streaming_track_id
                        == streaming_tracks_table.c.id,
                    )
                    .outerjoin(
                        streaming_playlists_table,
                        streaming_playlists_table.c.id
                        == playlist_membership_table.c.playlist_id,
                    )
                )
                .where(final_links_table.c.local_track_id == local_track_id)
                .order_by(
                    streaming_playlists_table.c.account_id.asc(),
                    streaming_playlists_table.c.id.asc(),
                )
            )
            .mappings()
            .first()
        )

        if row is None:
            raise MetadataRescueError(
                f"No final link exists for local track {local_track_id}"
            )

        account_id = row["account_id"]
        if not isinstance(account_id, int):
            account_id = _fallback_account_id(connection)
        resolved_attempt_id = _resolve_failed_attempt_id(
            connection,
            local_track_id=local_track_id,
            failed_attempt_id=failed_attempt_id,
        )

    if account_id is None:
        raise MetadataRescueError(
            "No streaming account is available to fetch rescue metadata"
        )

    file_path = str(row["file_path"])
    audio_path = (resolved_library_root / file_path).resolve()
    beets_id = row["beets_id"] if isinstance(row["beets_id"], int) else None
    stages: list[RescueStageResult] = []

    try:
        account = StreamingAccountStore(engine=engine).get_account(account_id)
        adapter = YouTubeMusicAdapter.from_browser_auth(account.browser_headers)
        fetched_metadata = adapter.get_track_metadata(row["provider_track_id"])
        metadata = _merge_metadata(row, fetched_metadata)
        artwork = _download_artwork(metadata.album_art_url)
    except Exception as exc:
        stages.append(_failed_stage("metadata_fetch", exc))
        _append_skipped_stages(
            stages,
            "file_tags",
            "beets_catalogue",
            "postgres_mirror",
            "failed_attempt",
        )
        return _result(
            local_track_id,
            file_path,
            beets_id,
            resolved_attempt_id,
            None,
            stages,
        )

    stages.append(
        RescueStageResult(
            name="metadata_fetch",
            status="succeeded",
            detail="Fetched and validated streaming metadata",
        )
    )

    try:
        write_id3_tags(audio_path, metadata, artwork=artwork)
    except Exception as exc:
        stages.append(_failed_stage("file_tags", exc))
        _append_skipped_stages(
            stages,
            "beets_catalogue",
            "postgres_mirror",
            "failed_attempt",
        )
        return _result(
            local_track_id,
            file_path,
            beets_id,
            resolved_attempt_id,
            metadata,
            stages,
        )

    stages.append(
        RescueStageResult(
            name="file_tags",
            status="succeeded",
            detail="Updated ID3 tags on the local audio file",
        )
    )

    if beets_id is None:
        stages.extend(
            (
                RescueStageResult(
                    name="beets_catalogue",
                    status="not_applicable",
                    detail="Local track has no Beets catalogue identifier",
                ),
                RescueStageResult(
                    name="postgres_mirror",
                    status="not_applicable",
                    detail="No Beets catalogue row exists to mirror",
                ),
            )
        )
    else:
        try:
            update_beets_catalogue(
                resolved_beets_library,
                beets_id=beets_id,
                audio_path=audio_path,
                metadata=metadata,
                import_lock_path=resolved_beets_import_lock_path,
            )
        except Exception as exc:
            stages.append(_failed_stage("beets_catalogue", exc))
            _append_skipped_stages(stages, "postgres_mirror", "failed_attempt")
            return _result(
                local_track_id,
                file_path,
                beets_id,
                resolved_attempt_id,
                metadata,
                stages,
            )

        stages.append(
            RescueStageResult(
                name="beets_catalogue",
                status="succeeded",
                detail=f"Updated Beets item {beets_id}",
            )
        )

        try:
            reconcile_beets_mirror(
                engine,
                resolved_beets_library,
                beets_id=beets_id,
            )
        except Exception as exc:
            stages.append(_failed_stage("postgres_mirror", exc))
            _append_skipped_stages(stages, "failed_attempt")
            return _result(
                local_track_id,
                file_path,
                beets_id,
                resolved_attempt_id,
                metadata,
                stages,
            )

        stages.append(
            RescueStageResult(
                name="postgres_mirror",
                status="succeeded",
                detail=f"Reconciled Beets item {beets_id} into the database mirror",
            )
        )

    if resolved_attempt_id is None:
        stages.append(
            RescueStageResult(
                name="failed_attempt",
                status="not_applicable",
                detail="No failed ingestion attempt is associated with this local track",
            )
        )
    else:
        cleared = FailedIngestionAttemptStore(engine=engine).clear(
            resolved_attempt_id,
            local_track_id=local_track_id,
        )
        if cleared != 1:
            stages.append(
                RescueStageResult(
                    name="failed_attempt",
                    status="failed",
                    detail=(
                        f"Failed attempt {resolved_attempt_id} changed before it could "
                        "be resolved"
                    ),
                )
            )
        else:
            stages.append(
                RescueStageResult(
                    name="failed_attempt",
                    status="succeeded",
                    detail=f"Resolved failed ingestion attempt {resolved_attempt_id}",
                )
            )

    return _result(
        local_track_id,
        file_path,
        beets_id,
        resolved_attempt_id,
        metadata,
        stages,
    )


def update_beets_catalogue(
    library_database: Path | str,
    *,
    beets_id: int,
    audio_path: Path | str,
    metadata: RescueMetadata,
    import_lock_path: Path | str | None = None,
) -> None:
    database_path = Path(library_database)
    if not database_path.is_file():
        raise MetadataRescueError(f"Beets library does not exist: {database_path}")

    with beets_library_lock(
        database_path,
        import_lock_path=import_lock_path,
    ):
        with sqlite3.connect(database_path) as sqlite_conn:
            row = sqlite_conn.execute(
                "SELECT path FROM items WHERE id = ?",
                (beets_id,),
            ).fetchone()
            if row is None:
                raise MetadataRescueError(f"Beets item {beets_id} does not exist")

            item_path = Path(decode_beets_path(row[0])).resolve()
            expected_path = Path(audio_path).resolve()
            if item_path != expected_path:
                raise MetadataRescueError(
                    f"Beets item {beets_id} points to {item_path}, not {expected_path}"
                )

            sqlite_conn.execute(
                """
                UPDATE items
                SET title = ?, artist = ?, album = ?, year = ?
                WHERE id = ?
                """,
                (
                    metadata.title,
                    metadata.artist,
                    metadata.album or "",
                    metadata.year or 0,
                    beets_id,
                ),
            )


def reconcile_beets_mirror(
    engine: Engine,
    library_database: Path | str,
    *,
    beets_id: int,
) -> None:
    with sqlite3.connect(library_database) as sqlite_conn:
        item_row = read_item(sqlite_conn, beets_id)
        if item_row is None:
            raise MetadataRescueError(
                f"Beets item {beets_id} was not found during mirror reconciliation"
            )
        album_row = (
            read_album(sqlite_conn, item_row.album_id)
            if item_row.album_id is not None
            else None
        )
        if item_row.album_id is not None and album_row is None:
            raise MetadataRescueError(
                f"Beets album {item_row.album_id} was not found during mirror reconciliation"
            )

    with engine.begin() as connection:
        upsert_item(connection, item_row)
        if album_row is not None:
            upsert_album(connection, album_row)


def write_id3_tags(
    mp3_path: Path | str,
    metadata: RescueMetadata,
    *,
    artwork: ArtworkPayload | None = None,
) -> None:
    path = Path(mp3_path)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    for frame_id in ("TIT2", "TPE1", "TALB", "TDRC", "APIC"):
        tags.delall(frame_id)

    tags.add(TIT2(encoding=3, text=metadata.title))
    tags.add(TPE1(encoding=3, text=metadata.artist))

    if metadata.album:
        tags.add(TALB(encoding=3, text=metadata.album))

    if metadata.year is not None:
        tags.add(TDRC(encoding=3, text=str(metadata.year)))

    if artwork is not None:
        tags.add(
            APIC(
                encoding=3,
                mime=artwork.mime_type,
                type=artwork.picture_type,
                desc=artwork.description,
                data=artwork.data,
            )
        )

    tags.save(path)


def _fallback_account_id(connection) -> int | None:
    row = connection.execute(
        select(streaming_accounts_table.c.id).order_by(
            streaming_accounts_table.c.id.asc()
        )
    ).first()
    if row is None:
        return None
    account_id = row[0]
    return account_id if isinstance(account_id, int) else None


def _resolve_failed_attempt_id(
    connection,
    *,
    local_track_id: int,
    failed_attempt_id: int | None,
) -> int | None:
    query = (
        select(failed_ingestion_attempts_table.c.id)
        .where(failed_ingestion_attempts_table.c.local_track_id == local_track_id)
        .order_by(failed_ingestion_attempts_table.c.id.asc())
    )
    if failed_attempt_id is not None:
        query = query.where(failed_ingestion_attempts_table.c.id == failed_attempt_id)

    attempt_ids = [int(attempt_id) for attempt_id in connection.scalars(query)]
    if failed_attempt_id is not None:
        if not attempt_ids:
            raise MetadataRescueConflictError(
                f"Failed attempt {failed_attempt_id} is not associated with local track "
                f"{local_track_id}"
            )
        return attempt_ids[0]

    if len(attempt_ids) > 1:
        raise MetadataRescueConflictError(
            f"Local track {local_track_id} has multiple failed attempts; provide "
            "failed_attempt_id explicitly"
        )
    return attempt_ids[0] if attempt_ids else None


def _result(
    local_track_id: int,
    file_path: str,
    beets_id: int | None,
    failed_attempt_id: int | None,
    metadata: RescueMetadata | None,
    stages: list[RescueStageResult],
) -> MetadataRescueResult:
    return MetadataRescueResult(
        local_track_id=local_track_id,
        file_path=file_path,
        beets_id=beets_id,
        failed_attempt_id=failed_attempt_id,
        metadata=metadata,
        stages=tuple(stages),
    )


def _failed_stage(name: str, exc: Exception) -> RescueStageResult:
    detail = str(exc).strip() or exc.__class__.__name__
    return RescueStageResult(name=name, status="failed", detail=detail)


def _append_skipped_stages(
    stages: list[RescueStageResult],
    *names: str,
) -> None:
    stages.extend(
        RescueStageResult(
            name=name,
            status="skipped",
            detail="Skipped because an earlier rescue stage failed",
        )
        for name in names
    )


def _merge_metadata(
    row,
    fetched_metadata: YouTubeMusicTrackMetadata,
) -> RescueMetadata:
    title = fetched_metadata.title or row["title"]
    artist = fetched_metadata.artist or row["artist"]
    if not title or not artist:
        raise MetadataRescueError(
            "Streaming metadata is missing required title or artist fields"
        )

    album = (
        fetched_metadata.album if fetched_metadata.album is not None else row["album"]
    )
    year = fetched_metadata.year if fetched_metadata.year is not None else row["year"]

    return RescueMetadata(
        title=title,
        artist=artist,
        album=album,
        year=year,
        album_art_url=fetched_metadata.album_art_url,
    )


def _download_artwork(album_art_url: str | None) -> ArtworkPayload | None:
    if not album_art_url:
        return None

    with urlopen(album_art_url, timeout=30) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type")

    if not data:
        return None

    mime_type = _resolve_mime_type(album_art_url, content_type)
    return ArtworkPayload(data=data, mime_type=mime_type)


def _resolve_mime_type(url: str, content_type: str | None) -> str:
    if isinstance(content_type, str) and content_type:
        return content_type.split(";", 1)[0].strip()

    guessed_type, _ = mimetypes.guess_type(url)
    if guessed_type:
        return guessed_type

    return "image/jpeg"
