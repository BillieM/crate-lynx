from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import uuid

from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.core.paths import resolve_staging_path
from app.local_tracks.store import LocalTrackStore
from app.matching.jobs import MatchingJobEnqueuer
from app.sonic.jobs import SonicJobEnqueuer
from app.ingestion.beets_mirror_sync import (
    decode_beets_path,
    read_album,
    read_item,
    upsert_album,
    upsert_item,
)
from app.ingestion.failures import FailedIngestionAttemptStore


logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aiff", ".aif"}
LOSSLESS_AUDIO_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif"}
IMPORTED_AUDIO_FILE_MODE = 0o664
IMPORTED_AUDIO_DIRECTORY_MODE = 0o2775


class UnsupportedAudioFormatError(ValueError):
    pass


class IngestionCommandError(RuntimeError):
    pass


@dataclass(slots=True)
class PreparedTrack:
    source_path: Path
    prepared_path: Path
    transcoded: bool
    fingerprint: str | None = None
    library_path: Path | None = None
    beets_id: int | None = None
    local_track_id: int | None = None
    matching_job_id: str | None = None
    sonic_feature_job_id: str | None = None


@dataclass(slots=True)
class ImportedTrack:
    library_path: Path
    beets_id: int | None = None


@dataclass(slots=True)
class AudioPreparer:
    ffmpeg_binary: str = "ffmpeg"

    def prepare(
        self, source_path: Path | str, output_directory: Path | str
    ) -> PreparedTrack:
        source = Path(source_path)
        output_root = Path(output_directory)
        extension = source.suffix.lower()

        if extension not in SUPPORTED_AUDIO_EXTENSIONS:
            raise UnsupportedAudioFormatError(
                f"Unsupported audio format for ingestion: {source.suffix or '<none>'}"
            )

        output_root.mkdir(parents=True, exist_ok=True)

        if extension == ".mp3":
            prepared_path = output_root / f"{uuid.uuid4().hex}_{source.name}"
            _link_or_copy(source, prepared_path)
            return PreparedTrack(
                source_path=source,
                prepared_path=prepared_path,
                transcoded=False,
            )

        prepared_path = output_root / f"{uuid.uuid4().hex}_{source.stem}.mp3"
        self._transcode_to_mp3(source, prepared_path)
        return PreparedTrack(
            source_path=source,
            prepared_path=prepared_path,
            transcoded=True,
        )

    def _transcode_to_mp3(self, source_path: Path, output_path: Path) -> None:
        _run_checked(
            "FFmpeg transcode",
            [
                self.ffmpeg_binary,
                "-y",
                "-i",
                str(source_path),
                "-codec:a",
                "libmp3lame",
                str(output_path),
            ],
        )


@dataclass(slots=True)
class BeetsImporter:
    beet_binary: str = "beet"
    library_root: Path | str = "/nas/media/music"
    library_database: Path | str = "/data/beets/library.db"
    import_lock_path: Path | str | None = None
    _import_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def import_file(self, prepared_path: Path | str) -> ImportedTrack:
        library_root = Path(self.library_root)
        library_root.mkdir(parents=True, exist_ok=True)

        library_database = Path(self.library_database)
        library_database.parent.mkdir(parents=True, exist_ok=True)
        import_lock_path = _resolve_import_lock_path(
            library_database,
            self.import_lock_path,
        )
        with self._import_lock:
            with _exclusive_file_lock(import_lock_path):
                previous_item_id = self._latest_item_id(library_database)

                _run_checked(
                    "Beets import",
                    [
                        self.beet_binary,
                        "-l",
                        str(library_database),
                        "-d",
                        str(library_root),
                        "import",
                        "-q",
                        "--quiet-fallback=asis",
                        "-m",
                        "-s",
                        str(prepared_path),
                    ],
                )
                return self._fetch_imported_track(library_database, previous_item_id)

    def _latest_item_id(self, library_database: Path) -> int:
        if not library_database.exists():
            return 0

        with sqlite3.connect(library_database) as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(id), 0) FROM items"
            ).fetchone()

        return 0 if row is None else int(row[0])

    def _fetch_imported_track(
        self, library_database: Path, previous_item_id: int
    ) -> ImportedTrack:
        with sqlite3.connect(library_database) as connection:
            row = connection.execute(
                "SELECT id, path FROM items WHERE id > ? ORDER BY id DESC LIMIT 1",
                (previous_item_id,),
            ).fetchone()

        if row is None:
            raise ValueError("Beets import did not create a library item")

        return ImportedTrack(
            library_path=Path(decode_beets_path(row[1])),
            beets_id=int(row[0]),
        )


@dataclass(slots=True)
class FingerprintGenerator:
    fpcalc_binary: str = "fpcalc"

    def generate(self, audio_path: Path | str) -> str:
        completed = _run_checked(
            "Chromaprint fingerprint",
            [
                self.fpcalc_binary,
                "-json",
                str(audio_path),
            ],
        )
        return self._parse_fingerprint(completed.stdout)

    def _parse_fingerprint(self, output: str) -> str:
        payload = json.loads(output)
        fingerprint = payload.get("fingerprint")

        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("fpcalc output did not include a fingerprint")

        return fingerprint


@dataclass(slots=True)
class IngestionProcessor:
    staging_root: Path | str
    audio_preparer: AudioPreparer = field(default_factory=AudioPreparer)
    beets_importer: BeetsImporter = field(default_factory=BeetsImporter)
    fingerprint_generator: FingerprintGenerator = field(
        default_factory=FingerprintGenerator
    )
    track_store: LocalTrackStore | None = None
    failed_attempt_store: FailedIngestionAttemptStore | None = None
    matching_job_enqueuer: MatchingJobEnqueuer | None = None
    sonic_job_enqueuer: SonicJobEnqueuer | None = None
    database_engine: Engine | None = None

    def process(self, source_path: Path | str) -> PreparedTrack:
        prepared: PreparedTrack | None = None
        try:
            prepared = self.audio_preparer.prepare(source_path, self.staging_root)
            prepared.fingerprint = self.fingerprint_generator.generate(
                prepared.prepared_path
            )
            imported_track = self.beets_importer.import_file(prepared.prepared_path)
            self._normalize_import_permissions(imported_track.library_path)
            prepared.library_path = imported_track.library_path
            prepared.beets_id = imported_track.beets_id
            self._mirror_imported_track(imported_track)
            if self.track_store is not None:
                persisted = self.track_store.persist(
                    library_root=self.beets_importer.library_root,
                    library_path=imported_track.library_path,
                    fingerprint=prepared.fingerprint,
                    beets_id=imported_track.beets_id,
                )
                prepared.local_track_id = persisted.id
                self._mark_soulseek_acquisition_ingested(prepared)
            if (
                self.matching_job_enqueuer is not None
                and prepared.local_track_id is not None
            ):
                prepared.matching_job_id = self.matching_job_enqueuer.enqueue(
                    prepared.local_track_id
                )
            if (
                self.sonic_job_enqueuer is not None
                and prepared.local_track_id is not None
            ):
                prepared.sonic_feature_job_id = (
                    self.sonic_job_enqueuer.enqueue_feature_extraction(
                        prepared.local_track_id
                    )
                )
            if self.failed_attempt_store is not None:
                self.failed_attempt_store.clear_for_source_path(prepared.source_path)
            self._cleanup_source(prepared.source_path)
            return prepared
        except (
            FileNotFoundError,
            IngestionCommandError,
            sqlite3.Error,
            UnsupportedAudioFormatError,
            ValueError,
        ) as exc:
            logger.exception("Failed to ingest source_path=%s", source_path)
            if prepared is not None:
                self._cleanup_prepared(prepared.prepared_path)
            if self.failed_attempt_store is not None:
                self.failed_attempt_store.persist(
                    source_path=source_path,
                    fingerprint=prepared.fingerprint if prepared is not None else None,
                    failure_reason=str(exc),
                    local_track_id=(
                        prepared.local_track_id if prepared is not None else None
                    ),
                )
            self._mark_soulseek_acquisition_failed(source_path, exc)
            raise

    def _normalize_import_permissions(self, library_path: Path) -> None:
        try:
            normalize_imported_track_permissions(
                library_root=self.beets_importer.library_root,
                library_path=library_path,
            )
        except (OSError, ValueError):
            logger.warning(
                "Failed to normalize imported track permissions for %s",
                library_path,
                exc_info=True,
            )

    def _mirror_imported_track(self, imported_track: ImportedTrack) -> None:
        if self.database_engine is None or imported_track.beets_id is None:
            return

        with sqlite3.connect(self.beets_importer.library_database) as sqlite_conn:
            item_row = read_item(
                sqlite_conn,
                imported_track.beets_id,
            )
            if item_row is None:
                raise ValueError(
                    "Beets mirror item "
                    f"beets_id={imported_track.beets_id} was not found after import"
                )
            album_row = (
                read_album(sqlite_conn, item_row.album_id)
                if item_row.album_id is not None
                else None
            )
            if item_row.album_id is not None and album_row is None:
                raise ValueError(
                    "Beets mirror album "
                    f"beets_album_id={item_row.album_id} was not found after import"
                )

        with self.database_engine.begin() as pg_conn:
            upsert_item(pg_conn, item_row)
            if album_row is not None:
                upsert_album(pg_conn, album_row)

    def _mark_soulseek_acquisition_ingested(self, prepared: PreparedTrack) -> None:
        if self.database_engine is None or prepared.local_track_id is None:
            return

        try:
            from app.soulseek.store import SoulseekStore

            result = SoulseekStore(
                engine=self.database_engine
            ).mark_ingested_and_auto_link_from_source_path(
                local_track_id=prepared.local_track_id,
                source_path=str(prepared.source_path),
            )
            if result is not None and result.affected_playlist_ids:
                redis_url = os.environ.get("REDIS_URL")
                if redis_url:
                    from app.m3u.jobs import M3uRegenerationJobEnqueuer

                    M3uRegenerationJobEnqueuer(redis_url).enqueue_playlists(
                        result.affected_playlist_ids
                    )
        except Exception:
            logger.warning(
                "Failed to mark Soulseek acquisition ingested for source_path=%s",
                prepared.source_path,
                exc_info=True,
            )

    def _mark_soulseek_acquisition_failed(
        self,
        source_path: Path | str,
        exc: Exception,
    ) -> None:
        if self.database_engine is None:
            return

        try:
            from app.soulseek.store import SoulseekStore

            SoulseekStore(engine=self.database_engine).mark_failed_from_source_path(
                error_detail=str(exc),
                source_path=str(source_path),
            )
        except Exception:
            logger.warning(
                "Failed to mark Soulseek acquisition failed for source_path=%s",
                source_path,
                exc_info=True,
            )

    def _cleanup_source(self, source_path: Path) -> None:
        if source_path.exists():
            source_path.unlink()

    def _cleanup_prepared(self, prepared_path: Path) -> None:
        if prepared_path.exists():
            prepared_path.unlink()


def build_ingestion_processor(
    *,
    database_engine: Engine | None = None,
    database_url: str | None = None,
    redis_url: str | None = None,
    staging_root: Path | str | None = None,
) -> IngestionProcessor:
    resolved_database_url = (
        database_url if database_url is not None else os.environ.get("DATABASE_URL")
    )
    engine = database_engine
    if engine is None and resolved_database_url:
        engine = create_database_engine(resolved_database_url)

    resolved_redis_url = (
        redis_url if redis_url is not None else os.environ.get("REDIS_URL")
    )

    return IngestionProcessor(
        staging_root=(
            staging_root
            if staging_root is not None
            else resolve_staging_path("INGESTION_STAGING_ROOT", "ingestion-staging")
        ),
        beets_importer=BeetsImporter(
            beet_binary=os.environ.get("BEET_BINARY", "beet"),
            library_root=Path(os.environ.get("LIBRARY_ROOT", "/nas/media/music")),
            library_database=os.environ.get("BEETS_LIBRARY", "/data/beets/library.db"),
            import_lock_path=os.environ.get("BEETS_IMPORT_LOCK_PATH"),
        ),
        track_store=LocalTrackStore(engine=engine) if engine is not None else None,
        failed_attempt_store=(
            FailedIngestionAttemptStore(engine=engine) if engine is not None else None
        ),
        matching_job_enqueuer=(
            MatchingJobEnqueuer(resolved_redis_url) if resolved_redis_url else None
        ),
        sonic_job_enqueuer=(
            SonicJobEnqueuer(resolved_redis_url) if resolved_redis_url else None
        ),
        database_engine=engine,
    )


def _run_checked(
    operation: str, command: list[str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = _format_process_output(exc)
        raise IngestionCommandError(
            f"{operation} failed with exit status {exc.returncode}: {detail}"
        ) from exc


def _format_process_output(exc: subprocess.CalledProcessError) -> str:
    stderr = (exc.stderr or "").strip()
    stdout = (exc.stdout or "").strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    return "no output captured"


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def normalize_imported_track_permissions(
    *,
    library_root: Path | str,
    library_path: Path | str,
    file_mode: int = IMPORTED_AUDIO_FILE_MODE,
    directory_mode: int = IMPORTED_AUDIO_DIRECTORY_MODE,
) -> None:
    resolved_library_root = Path(library_root).resolve()
    resolved_library_path = Path(library_path).resolve()
    resolved_library_path.relative_to(resolved_library_root)

    group_id = resolved_library_root.stat().st_gid
    for directory in _library_path_directories(
        library_root=resolved_library_root,
        library_path=resolved_library_path,
    ):
        _chgrp_if_needed(directory, group_id)
        directory.chmod(directory_mode)

    _chgrp_if_needed(resolved_library_path, group_id)
    resolved_library_path.chmod(file_mode)


def _library_path_directories(
    *,
    library_root: Path,
    library_path: Path,
) -> list[Path]:
    directories = []
    current = library_path.parent
    while current != library_root.parent:
        directories.append(current)
        if current == library_root:
            break
        current = current.parent

    return list(reversed(directories))


def _chgrp_if_needed(path: Path, group_id: int) -> None:
    if path.stat().st_gid != group_id:
        os.chown(path, -1, group_id)


def _resolve_import_lock_path(
    library_database: Path,
    configured_lock_path: Path | str | None,
) -> Path:
    if configured_lock_path is not None:
        return Path(configured_lock_path)

    return library_database.with_name(f"{library_database.name}.import.lock")


@contextmanager
def _exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
