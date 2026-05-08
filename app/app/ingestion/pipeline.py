from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import uuid

from sqlalchemy.engine import Engine

from app.local_tracks.store import LocalTrackStore
from app.matching.jobs import MatchingJobEnqueuer
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
            shutil.copy2(source, prepared_path)
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
    library_root: Path | str = "/music"
    library_database: Path | str = "/data/beets/library.db"
    _import_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def import_file(self, prepared_path: Path | str) -> ImportedTrack:
        library_root = Path(self.library_root)
        library_root.mkdir(parents=True, exist_ok=True)

        library_database = Path(self.library_database)
        library_database.parent.mkdir(parents=True, exist_ok=True)
        with self._import_lock:
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
    database_engine: Engine | None = None

    def process(self, source_path: Path | str) -> PreparedTrack:
        prepared: PreparedTrack | None = None
        try:
            prepared = self.audio_preparer.prepare(source_path, self.staging_root)
            prepared.fingerprint = self.fingerprint_generator.generate(
                prepared.prepared_path
            )
            imported_track = self.beets_importer.import_file(prepared.prepared_path)
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
            if (
                self.matching_job_enqueuer is not None
                and prepared.local_track_id is not None
            ):
                prepared.matching_job_id = self.matching_job_enqueuer.enqueue(
                    prepared.local_track_id
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
            raise

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

    def _cleanup_source(self, source_path: Path) -> None:
        if source_path.exists():
            source_path.unlink()

    def _cleanup_prepared(self, prepared_path: Path) -> None:
        if prepared_path.exists():
            prepared_path.unlink()


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
