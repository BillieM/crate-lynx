from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
from typing import Callable

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

    def import_file(self, prepared_path: Path | str) -> None:
        library_root = Path(self.library_root)
        library_root.mkdir(parents=True, exist_ok=True)

        library_database = (
            Path(self.library_database)
            if self.library_database is not None
            else library_root / "library.db"
        )

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


@dataclass(slots=True)
class IngestionProcessor:
    staging_root: Path | str
    audio_preparer: AudioPreparer = field(default_factory=AudioPreparer)
    beets_importer: BeetsImporter = field(default_factory=BeetsImporter)

    def process(self, source_path: Path | str) -> PreparedTrack:
        prepared = self.audio_preparer.prepare(source_path, self.staging_root)
        self.beets_importer.import_file(prepared.prepared_path)
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
