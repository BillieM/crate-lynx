from pathlib import Path
import subprocess

from watchdog.events import DirCreatedEvent, FileCreatedEvent

from app.ingestion import (
    AudioPreparer,
    IngestionEventHandler,
    IngestionWatcher,
    PreparedTrack,
    UnsupportedAudioFormatError,
)


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
        prepared_path=source,
        transcoded=False,
    )
    assert output_root.is_dir()


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
