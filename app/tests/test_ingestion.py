from pathlib import Path
import sqlite3
import subprocess
from unittest.mock import Mock

from watchdog.events import DirCreatedEvent, FileCreatedEvent

from app.ingestion import (
    AudioPreparer,
    BeetsImporter,
    FingerprintGenerator,
    ImportedTrack,
    IngestionEventHandler,
    IngestionProcessor,
    IngestionWatcher,
    PreparedTrack,
    UnsupportedAudioFormatError,
)
from app.local_tracks import LocalTrackStore, local_tracks_table, metadata
from sqlalchemy import create_engine, select


class StubObserver:
    def __init__(self) -> None:
        self.scheduled: list[tuple[object, str, bool]] = []
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler: object, path: str, recursive: bool) -> None:
        self.scheduled.append((handler, path, recursive))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self) -> None:
        self.joined = True


def test_ingestion_event_handler_ignores_directories() -> None:
    seen: list[Path] = []
    handler = IngestionEventHandler(seen.append)

    handler.on_created(DirCreatedEvent("/tmp/ingestion"))

    assert seen == []


def test_ingestion_event_handler_forwards_new_files() -> None:
    seen: list[Path] = []
    handler = IngestionEventHandler(seen.append)

    handler.on_created(FileCreatedEvent("/tmp/ingestion/track.mp3"))

    assert seen == [Path("/tmp/ingestion/track.mp3")]


def test_ingestion_watcher_starts_and_stops(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        observer_factory=lambda: stub_observer,
    )

    watcher.start()

    assert (tmp_path / "ingestion").is_dir()
    assert stub_observer.started is True
    assert len(stub_observer.scheduled) == 1
    _, scheduled_path, recursive = stub_observer.scheduled[0]
    assert scheduled_path == str(tmp_path / "ingestion")
    assert recursive is False

    watcher.stop()

    assert stub_observer.stopped is True
    assert stub_observer.joined is True


def test_audio_preparer_passes_mp3_through_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "track.MP3"
    source.write_bytes(b"mp3")
    output_root = tmp_path / "staging"

    prepared = AudioPreparer().prepare(source, output_root)

    assert prepared == PreparedTrack(
        source_path=source,
        prepared_path=output_root / "track.MP3",
        transcoded=False,
    )
    assert output_root.is_dir()
    assert prepared.prepared_path.read_bytes() == b"mp3"


def test_audio_preparer_transcodes_lossless_formats_to_mp3(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "track.flac"
    source.write_bytes(b"flac")
    output_root = tmp_path / "staging"
    seen_commands: list[list[str]] = []

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.ingestion.subprocess.run", fake_run)

    prepared = AudioPreparer(ffmpeg_binary="ffmpeg-test").prepare(source, output_root)

    assert prepared == PreparedTrack(
        source_path=source,
        prepared_path=output_root / "track.mp3",
        transcoded=True,
    )
    assert seen_commands == [
        [
            "ffmpeg-test",
            "-y",
            "-i",
            str(source),
            "-codec:a",
            "libmp3lame",
            str(output_root / "track.mp3"),
        ]
    ]


def test_audio_preparer_rejects_unsupported_formats(tmp_path: Path) -> None:
    source = tmp_path / "track.ogg"
    source.write_bytes(b"ogg")

    try:
        AudioPreparer().prepare(source, tmp_path / "staging")
    except UnsupportedAudioFormatError as exc:
        assert ".ogg" in str(exc)
    else:
        raise AssertionError("Expected UnsupportedAudioFormatError")


def test_beets_importer_runs_quiet_move_import(tmp_path: Path, monkeypatch) -> None:
    library_root = tmp_path / "library"
    library_database = library_root / "library.db"
    prepared_path = tmp_path / "staging" / "track.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")
    seen_commands: list[list[str]] = []
    library_root.mkdir()

    with sqlite3.connect(library_database) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, path BLOB NOT NULL)"
        )
        connection.execute(
            "INSERT INTO items (id, path) VALUES (?, ?)",
            (1, str(library_root / "Existing" / "old.mp3").encode("utf-8")),
        )
        connection.commit()

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        with sqlite3.connect(library_database) as connection:
            connection.execute(
                "INSERT INTO items (id, path) VALUES (?, ?)",
                (2, str(library_root / "Artist" / "track.mp3").encode("utf-8")),
            )
            connection.commit()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.ingestion.subprocess.run", fake_run)

    imported = BeetsImporter(
        beet_binary="beet-test",
        library_root=library_root,
        library_database=library_database,
    ).import_file(prepared_path)

    assert imported == ImportedTrack(
        library_path=library_root / "Artist" / "track.mp3",
        beets_id=2,
    )
    assert library_root.is_dir()
    assert seen_commands == [
        [
            "beet-test",
            "-l",
            str(library_database),
            "-d",
            str(library_root),
            "import",
            "-q",
            "-m",
            str(prepared_path),
        ]
    ]


def test_fingerprint_generator_runs_fpcalc_and_parses_json(
    tmp_path: Path, monkeypatch
) -> None:
    prepared_path = tmp_path / "staging" / "track.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")
    seen_commands: list[list[str]] = []

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            '{"fingerprint":"abc123","duration":123.45}',
            "",
        )

    monkeypatch.setattr("app.ingestion.subprocess.run", fake_run)

    fingerprint = FingerprintGenerator(fpcalc_binary="fpcalc-test").generate(
        prepared_path
    )

    assert fingerprint == "abc123"
    assert seen_commands == [["fpcalc-test", "-json", str(prepared_path)]]


def test_fingerprint_generator_rejects_missing_fingerprint(
    tmp_path: Path, monkeypatch
) -> None:
    prepared_path = tmp_path / "staging" / "track.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, '{"duration":123.45}', "")

    monkeypatch.setattr("app.ingestion.subprocess.run", fake_run)

    try:
        FingerprintGenerator().generate(prepared_path)
    except ValueError as exc:
        assert "fingerprint" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_ingestion_processor_prepares_imports_and_deletes_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "track.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    prepared = PreparedTrack(
        source_path=source,
        prepared_path=tmp_path / "staging" / "track.mp3",
        transcoded=False,
    )
    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.return_value = prepared
    importer = Mock(spec=BeetsImporter)
    importer.library_root = tmp_path / "library"
    importer.import_file.return_value = ImportedTrack(
        library_path=tmp_path / "library" / "Artist" / "track.mp3",
        beets_id=17,
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "abc123"

    result = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
    ).process(source)

    assert result is prepared
    assert result.fingerprint == "abc123"
    assert result.library_path == tmp_path / "library" / "Artist" / "track.mp3"
    assert result.beets_id == 17
    preparer.prepare.assert_called_once_with(source, tmp_path / "staging")
    fingerprint_generator.generate.assert_called_once_with(prepared.prepared_path)
    importer.import_file.assert_called_once_with(prepared.prepared_path)
    assert source.exists() is False


def test_ingestion_processor_persists_relative_library_path(tmp_path: Path) -> None:
    source = tmp_path / "ingestion" / "track.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    prepared = PreparedTrack(
        source_path=source,
        prepared_path=tmp_path / "staging" / "track.mp3",
        transcoded=False,
    )
    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.return_value = prepared
    importer = Mock(spec=BeetsImporter)
    importer.library_root = tmp_path / "library"
    importer.import_file.return_value = ImportedTrack(
        library_path=tmp_path / "library" / "Artist" / "track.mp3",
        beets_id=42,
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "fp-42"

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    result = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        track_store=LocalTrackStore(database_url),
    ).process(source)

    with engine.connect() as connection:
        row = connection.execute(select(local_tracks_table)).mappings().one()

    assert result.local_track_id == row["id"]
    assert row["file_path"] == "Artist/track.mp3"
    assert row["library_root_rel_path"] == "Artist/track.mp3"
    assert row["fingerprint"] == "fp-42"
    assert row["beets_id"] == 42
