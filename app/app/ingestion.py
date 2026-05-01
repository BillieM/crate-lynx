from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Callable

from app.local_tracks import LocalTrackStore
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer


FileCallback = Callable[[Path], None]
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".aiff", ".aif"}
LOSSLESS_AUDIO_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif"}


class IngestionEventHandler(FileSystemEventHandler):
    def __init__(self, on_new_file: FileCallback) -> None:
        self._on_new_file = on_new_file

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        self._on_new_file(Path(event.src_path))


class UnsupportedAudioFormatError(ValueError):
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
            prepared_path = output_root / source.name
            shutil.copy2(source, prepared_path)
            return PreparedTrack(
                source_path=source,
                prepared_path=prepared_path,
                transcoded=False,
            )

        prepared_path = output_root / f"{source.stem}.mp3"
        self._transcode_to_mp3(source, prepared_path)
        return PreparedTrack(
            source_path=source,
            prepared_path=prepared_path,
            transcoded=True,
        )

    def _transcode_to_mp3(self, source_path: Path, output_path: Path) -> None:
        subprocess.run(
            [
                self.ffmpeg_binary,
                "-y",
                "-i",
                str(source_path),
                "-codec:a",
                "libmp3lame",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


@dataclass(slots=True)
class BeetsImporter:
    beet_binary: str = "beet"
    library_root: Path | str = "/library"
    library_database: Path | str | None = None

    def import_file(self, prepared_path: Path | str) -> ImportedTrack:
        library_root = Path(self.library_root)
        library_root.mkdir(parents=True, exist_ok=True)

        library_database = (
            Path(self.library_database)
            if self.library_database is not None
            else library_root / "library.db"
        )
        previous_item_id = self._latest_item_id(library_database)

        subprocess.run(
            [
                self.beet_binary,
                "-l",
                str(library_database),
                "-d",
                str(library_root),
                "import",
                "-q",
                "-m",
                str(prepared_path),
            ],
            check=True,
            capture_output=True,
            text=True,
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
            library_path=Path(self._decode_beets_path(row[1])),
            beets_id=int(row[0]),
        )

    def _decode_beets_path(self, raw_path: bytes | str) -> str:
        if isinstance(raw_path, bytes):
            return raw_path.decode("utf-8", errors="surrogateescape")

        return raw_path


@dataclass(slots=True)
class FingerprintGenerator:
    fpcalc_binary: str = "fpcalc"

    def generate(self, audio_path: Path | str) -> str:
        completed = subprocess.run(
            [
                self.fpcalc_binary,
                "-json",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
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

    def process(self, source_path: Path | str) -> PreparedTrack:
        prepared = self.audio_preparer.prepare(source_path, self.staging_root)
        prepared.fingerprint = self.fingerprint_generator.generate(
            prepared.prepared_path
        )
        imported_track = self.beets_importer.import_file(prepared.prepared_path)
        prepared.library_path = imported_track.library_path
        prepared.beets_id = imported_track.beets_id
        if self.track_store is not None:
            persisted = self.track_store.persist(
                library_root=self.beets_importer.library_root,
                library_path=imported_track.library_path,
                fingerprint=prepared.fingerprint,
                beets_id=imported_track.beets_id,
            )
            prepared.local_track_id = persisted.id
        self._cleanup_source(prepared.source_path)
        return prepared

    def _cleanup_source(self, source_path: Path) -> None:
        if source_path.exists():
            source_path.unlink()


@dataclass(slots=True)
class IngestionWatcher:
    root: Path | str
    on_new_file: FileCallback
    recursive: bool = False
    observer_factory: Callable[[], Observer] = Observer
    _observer: Observer | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._observer is not None:
            return

        root_path = Path(self.root)
        root_path.mkdir(parents=True, exist_ok=True)

        observer = self.observer_factory()
        observer.schedule(
            IngestionEventHandler(self.on_new_file),
            str(root_path),
            recursive=self.recursive,
        )
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return

        self._observer.stop()
        self._observer.join()
        self._observer = None
