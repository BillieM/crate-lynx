from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import logging
import sqlite3
import stat
import subprocess
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from beets.library import Album, Item
from sqlalchemy import create_engine, select
from watchdog.events import FileClosedEvent, FileMovedEvent

from app.ingestion import repair as ingestion_repair
from app.ingestion.beets_mirror import (
    beets_album_attributes_table,
    beets_albums_table,
    beets_item_attributes_table,
    beets_items_table,
    metadata as beets_mirror_metadata,
)
from app.ingestion.pipeline import (
    AudioPreparer,
    BeetsImporter,
    FingerprintGenerator,
    ImportedTrack,
    IngestionCommandError,
    PreparedTrack,
    UnsupportedAudioFormatError,
)
from app.matching.jobs import MatchingJobEnqueuer
from app.sonic.jobs import SonicJobEnqueuer
from app.ingestion.watcher import FileSnapshot, IngestionEventHandler, IngestionWatcher
from app.ingestion.pipeline import IngestionProcessor
from app.ingestion.failures import (
    FailedIngestionAttemptStore,
    failed_ingestion_attempts_table,
    metadata as failed_ingestion_attempts_metadata,
)
from app.local_tracks.store import LocalTrackStore, local_tracks_table, metadata


class StubObserver:
    def __init__(self) -> None:
        self.scheduled: list[tuple[object, str, bool]] = []
        self.unscheduled: list[object] = []
        self.started = False
        self.stopped = False
        self.joined = False

    def schedule(self, handler: object, path: str, recursive: bool) -> object:
        self.scheduled.append((handler, path, recursive))
        return f"watch:{path}"

    def unschedule(self, watch: object) -> None:
        self.unscheduled.append(watch)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self) -> None:
        self.joined = True


def _started_watcher(
    tmp_path: Path,
    on_new_file: list[Path],
    *,
    stability_observations: int = 1,
    stability_interval_seconds: float = 0.0,
) -> tuple[IngestionWatcher, IngestionEventHandler]:
    stub_observer = StubObserver()
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=on_new_file.append,
        observer_factory=lambda: stub_observer,
        stability_observations=stability_observations,
        stability_interval_seconds=stability_interval_seconds,
        sleep=lambda _: None,
    )
    watcher.start()

    handler = stub_observer.scheduled[0][0]
    assert isinstance(handler, IngestionEventHandler)
    return watcher, handler


def test_ingestion_event_handler_forwards_new_files(tmp_path: Path) -> None:
    seen: list[Path] = []
    _, handler = _started_watcher(tmp_path, seen)
    track_path = tmp_path / "ingestion" / "track.mp3"
    track_path.write_bytes(b"mp3")

    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == [track_path]


def test_ingestion_event_handler_ignores_non_audio_files(tmp_path: Path) -> None:
    seen: list[Path] = []
    _, handler = _started_watcher(tmp_path, seen)

    for filename in (
        ".DS_Store",
        "._track.flac",
        ".track.flac",
        "2f940acf775f48998bf67a0866d66d56",
        "cover.jpg",
    ):
        path = tmp_path / "ingestion" / filename
        path.write_bytes(b"not-a-track")
        handler.on_closed(FileClosedEvent(str(path)))

    assert seen == []


def test_ingestion_event_handler_ignores_directory_events() -> None:
    seen: list[Path] = []
    handler = IngestionEventHandler(seen.append)

    handler.on_closed(
        SimpleNamespace(src_path="/tmp/ingestion/Artist", is_directory=True)
    )

    assert seen == []


def test_ingestion_event_handler_forwards_nested_supported_files(
    tmp_path: Path,
) -> None:
    seen: list[Path] = []
    _, handler = _started_watcher(tmp_path, seen)
    track_path = tmp_path / "ingestion" / "Artist" / "Album" / "track.FLAC"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"flac")

    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == [track_path]


def test_ingestion_event_handler_forwards_moved_audio_destination(
    tmp_path: Path,
) -> None:
    seen: list[Path] = []
    _, handler = _started_watcher(tmp_path, seen)
    source_path = tmp_path / "downloading" / "track.mp3"
    track_path = tmp_path / "ingestion" / "Artist" / "track.mp3"
    source_path.parent.mkdir()
    track_path.parent.mkdir()
    track_path.write_bytes(b"mp3")

    handler.on_moved(
        FileMovedEvent(
            str(source_path),
            str(track_path),
        )
    )

    assert seen == [track_path]


def test_ingestion_event_handler_ignores_moved_non_audio_files(tmp_path: Path) -> None:
    seen: list[Path] = []
    _, handler = _started_watcher(tmp_path, seen)
    source_path = tmp_path / "downloading" / "cover.jpg"
    cover_path = tmp_path / "ingestion" / "Artist" / "cover.jpg"
    source_path.parent.mkdir()
    cover_path.parent.mkdir()
    cover_path.write_bytes(b"jpg")

    handler.on_moved(
        FileMovedEvent(
            str(source_path),
            str(cover_path),
        )
    )

    assert seen == []


def test_ingestion_event_handler_ignores_moved_directories() -> None:
    seen: list[Path] = []
    handler = IngestionEventHandler(seen.append)

    handler.on_moved(
        SimpleNamespace(
            src_path="/tmp/soulseek/downloading/Artist",
            dest_path="/tmp/soulseek/complete/Artist",
            is_directory=True,
        )
    )

    assert seen == []


def test_ingestion_event_handler_logs_failures_without_raising(
    tmp_path: Path, monkeypatch
) -> None:
    seen: list[Path] = []
    logged: list[Path] = []
    track_path = tmp_path / "ingestion" / "bad.flac"

    def on_new_file(path: Path) -> None:
        seen.append(path)
        raise RuntimeError("boom")

    def fake_exception(message: str, source_path: Path) -> None:
        logged.append(source_path)

    monkeypatch.setattr("app.ingestion.watcher.logger.exception", fake_exception)
    stub_observer = StubObserver()
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=on_new_file,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )
    watcher.start()
    handler = stub_observer.scheduled[0][0]
    assert isinstance(handler, IngestionEventHandler)
    track_path.write_bytes(b"flac")

    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == [track_path]
    assert logged == [track_path]


def test_ingestion_watcher_starts_and_stops(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
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


def test_ingestion_watcher_schedules_multiple_roots(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    first_root = tmp_path / "ingestion"
    second_root = tmp_path / "soulseek"
    watcher = IngestionWatcher(
        root=[first_root, second_root],
        on_new_file=lambda path: None,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )

    watcher.start()

    assert first_root.is_dir()
    assert second_root.is_dir()
    assert {scheduled_path for _, scheduled_path, _ in stub_observer.scheduled} == {
        str(first_root),
        str(second_root),
    }
    assert stub_observer.started is True


def test_ingestion_watcher_scans_existing_supported_files_on_start(
    tmp_path: Path,
) -> None:
    stub_observer = StubObserver()
    first_track = tmp_path / "ingestion" / "Artist" / "track.mp3"
    second_track = tmp_path / "soulseek" / "Album" / "track.FLAC"
    cover = tmp_path / "soulseek" / "Album" / "cover.jpg"
    first_track.parent.mkdir(parents=True)
    second_track.parent.mkdir(parents=True)
    first_track.write_bytes(b"mp3")
    second_track.write_bytes(b"flac")
    cover.write_bytes(b"jpg")
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=[tmp_path / "ingestion", tmp_path / "soulseek"],
        on_new_file=seen.append,
        recursive=True,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )

    watcher.start()

    assert seen == [first_track, second_track]


def test_ingestion_watcher_scans_only_top_level_files_when_not_recursive(
    tmp_path: Path,
) -> None:
    stub_observer = StubObserver()
    top_level_track = tmp_path / "ingestion" / "track.mp3"
    nested_track = tmp_path / "ingestion" / "Artist" / "nested.mp3"
    top_level_track.parent.mkdir()
    nested_track.parent.mkdir()
    top_level_track.write_bytes(b"mp3")
    nested_track.write_bytes(b"mp3")
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        recursive=False,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )

    watcher.start()

    assert seen == [top_level_track]


def test_ingestion_watcher_logs_scan_failures_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    stub_observer = StubObserver()
    first_track = tmp_path / "ingestion" / "a.mp3"
    second_track = tmp_path / "ingestion" / "b.mp3"
    first_track.parent.mkdir()
    first_track.write_bytes(b"mp3")
    second_track.write_bytes(b"mp3")
    seen: list[Path] = []
    logged: list[Path] = []

    def on_new_file(path: Path) -> None:
        seen.append(path)
        if path == first_track:
            raise RuntimeError("boom")

    def fake_exception(message: str, source_path: Path) -> None:
        logged.append(source_path)

    monkeypatch.setattr("app.ingestion.watcher.logger.exception", fake_exception)
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=on_new_file,
        recursive=True,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )

    watcher.start()

    assert seen == [first_track, second_track]
    assert logged == [first_track]


def test_ingestion_watcher_adds_and_removes_roots_live(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    initial_root = tmp_path / "ingestion"
    added_root = tmp_path / "soulseek"
    watcher = IngestionWatcher(
        root=initial_root,
        on_new_file=lambda path: None,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )
    watcher.start()

    watcher.add_root(added_root)
    watcher.add_root(added_root)

    assert added_root.is_dir()
    assert [scheduled_path for _, scheduled_path, _ in stub_observer.scheduled] == [
        str(initial_root),
        str(added_root),
    ]

    watcher.remove_root(added_root)
    watcher.remove_root(added_root)

    assert stub_observer.unscheduled == [f"watch:{added_root}"]


def test_ingestion_watcher_requires_ten_stable_observations(
    tmp_path: Path,
) -> None:
    stub_observer = StubObserver()
    track_path = tmp_path / "ingestion" / "track.flac"
    sleep_calls: list[float] = []
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        observer_factory=lambda: stub_observer,
        stability_observations=10,
        stability_interval_seconds=0.5,
        sleep=sleep_calls.append,
    )
    watcher.start()
    handler = stub_observer.scheduled[0][0]
    assert isinstance(handler, IngestionEventHandler)
    track_path.write_bytes(b"flac")

    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == [track_path]
    assert sleep_calls == [0.5] * 9


def test_ingestion_watcher_deduplicates_recent_events(tmp_path: Path) -> None:
    seen: list[Path] = []
    _, handler = _started_watcher(tmp_path, seen)
    track_path = tmp_path / "ingestion" / "track.flac"
    track_path.write_bytes(b"flac")

    handler.on_closed(FileClosedEvent(str(track_path)))
    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == [track_path]


def test_ingestion_watcher_allows_retry_after_dedupe_ttl(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    now = 100.0

    def clock() -> float:
        return now

    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        recently_handled_ttl_seconds=30.0,
        sleep=lambda _: None,
        clock=clock,
    )
    watcher.start()
    handler = stub_observer.scheduled[0][0]
    assert isinstance(handler, IngestionEventHandler)
    track_path = tmp_path / "ingestion" / "track.flac"
    track_path.write_bytes(b"flac")

    handler.on_closed(FileClosedEvent(str(track_path)))
    now = 131.0
    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == [track_path, track_path]


def test_ingestion_watcher_periodically_scans_for_missed_events(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        scan_interval_seconds=0.01,
        sleep=lambda _: None,
    )
    watcher.start()
    track_path = tmp_path / "ingestion" / "missed.flac"
    track_path.write_bytes(b"flac")

    deadline = time.monotonic() + 1.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()

    assert seen == [track_path]


def test_ingestion_watcher_checks_stability_concurrently(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    ingestion_root = tmp_path / "ingestion"
    first_track = ingestion_root / "first.mp3"
    second_track = ingestion_root / "second.mp3"
    ingestion_root.mkdir()
    first_track.write_bytes(b"mp3")
    second_track.write_bytes(b"mp3")
    seen: list[Path] = []
    waiting_workers: list[str] = []
    both_workers_waiting = threading.Event()

    def sleep_until_both_workers_are_waiting(_interval: float) -> None:
        waiting_workers.append(threading.current_thread().name)
        if len(waiting_workers) == 2:
            both_workers_waiting.set()
        assert both_workers_waiting.wait(timeout=1.0)

    watcher = IngestionWatcher(
        root=ingestion_root,
        on_new_file=seen.append,
        observer_factory=lambda: stub_observer,
        stability_observations=2,
        stability_interval_seconds=0.0,
        stability_workers=2,
        sleep=sleep_until_both_workers_are_waiting,
    )
    watcher.start()

    deadline = time.monotonic() + 1.0
    while len(seen) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    watcher.stop()

    assert sorted(seen, key=str) == [first_track, second_track]
    assert len(set(waiting_workers)) == 2


def test_ingestion_watcher_scans_new_root_when_added_live(tmp_path: Path) -> None:
    stub_observer = StubObserver()
    seen: list[Path] = []
    watcher = IngestionWatcher(
        root=tmp_path / "ingestion",
        on_new_file=seen.append,
        recursive=True,
        observer_factory=lambda: stub_observer,
        stability_observations=1,
        sleep=lambda _: None,
    )
    watcher.start()
    added_root = tmp_path / "soulseek"
    track_path = added_root / "Album" / "track.flac"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"flac")

    watcher.add_root(added_root)
    watcher.stop()

    assert seen == [track_path]


def test_ingestion_watcher_skips_disappearing_files(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = iter((FileSnapshot(size=1, mtime_ns=1), None))
    seen: list[Path] = []
    watcher, handler = _started_watcher(
        tmp_path,
        seen,
        stability_observations=2,
        stability_interval_seconds=0.0,
    )
    track_path = tmp_path / "ingestion" / "track.flac"
    track_path.write_bytes(b"flac")
    monkeypatch.setattr(
        "app.ingestion.watcher._snapshot_file",
        lambda path: next(snapshots),
    )

    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == []
    assert watcher.roots == (tmp_path / "ingestion",)


def test_ingestion_watcher_skips_files_changing_during_stability_check(
    tmp_path: Path, monkeypatch
) -> None:
    snapshots = iter(
        (
            FileSnapshot(size=1, mtime_ns=1),
            FileSnapshot(size=2, mtime_ns=2),
        )
    )
    seen: list[Path] = []
    _, handler = _started_watcher(
        tmp_path,
        seen,
        stability_observations=2,
        stability_interval_seconds=0.0,
    )
    track_path = tmp_path / "ingestion" / "track.flac"
    track_path.write_bytes(b"flac")
    monkeypatch.setattr(
        "app.ingestion.watcher._snapshot_file",
        lambda path: next(snapshots),
    )

    handler.on_closed(FileClosedEvent(str(track_path)))

    assert seen == []


def test_ingestion_watcher_skips_zero_byte_audio_until_later_scan(
    tmp_path: Path,
) -> None:
    seen: list[Path] = []
    watcher, _ = _started_watcher(tmp_path, seen)
    track_path = tmp_path / "ingestion" / "track.mp3"
    track_path.write_bytes(b"")

    watcher._ingest_candidate(track_path)

    assert seen == []

    track_path.write_bytes(b"mp3")
    watcher._ingest_candidate(track_path)

    assert seen == [track_path]


def test_audio_preparer_passes_mp3_through_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "track.MP3"
    source.write_bytes(b"mp3")
    output_root = tmp_path / "staging"

    monkeypatch.setattr(
        "app.ingestion.pipeline.uuid.uuid4",
        lambda: type("StubUUID", (), {"hex": "abc123"})(),
    )

    prepared = AudioPreparer().prepare(source, output_root)

    assert prepared == PreparedTrack(
        source_path=source,
        prepared_path=output_root / "abc123_track.MP3",
        transcoded=False,
    )
    assert output_root.is_dir()
    assert prepared.prepared_path.read_bytes() == b"mp3"
    assert prepared.prepared_path.stat().st_ino == source.stat().st_ino


def test_audio_preparer_copies_mp3_when_hardlink_fails(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "track.mp3"
    source.write_bytes(b"mp3")
    output_root = tmp_path / "staging"

    monkeypatch.setattr(
        "app.ingestion.pipeline.uuid.uuid4",
        lambda: type("StubUUID", (), {"hex": "abc123"})(),
    )
    monkeypatch.setattr(
        "app.ingestion.pipeline.os.link",
        Mock(side_effect=OSError("cross-device link")),
    )

    prepared = AudioPreparer().prepare(source, output_root)

    assert prepared.prepared_path == output_root / "abc123_track.mp3"
    assert prepared.prepared_path.read_bytes() == b"mp3"
    assert prepared.prepared_path.stat().st_ino != source.stat().st_ino


def test_audio_preparer_uses_unique_staging_paths_for_same_basename_mp3s(
    tmp_path: Path, monkeypatch
) -> None:
    first_source = tmp_path / "one" / "track.mp3"
    second_source = tmp_path / "two" / "track.mp3"
    first_source.parent.mkdir()
    second_source.parent.mkdir()
    first_source.write_bytes(b"first")
    second_source.write_bytes(b"second")
    output_root = tmp_path / "staging"
    uuids = iter(("aaa111", "bbb222"))

    monkeypatch.setattr(
        "app.ingestion.pipeline.uuid.uuid4",
        lambda: type("StubUUID", (), {"hex": next(uuids)})(),
    )

    first_prepared = AudioPreparer().prepare(first_source, output_root)
    second_prepared = AudioPreparer().prepare(second_source, output_root)

    assert first_prepared.prepared_path == output_root / "aaa111_track.mp3"
    assert second_prepared.prepared_path == output_root / "bbb222_track.mp3"
    assert first_prepared.prepared_path.read_bytes() == b"first"
    assert second_prepared.prepared_path.read_bytes() == b"second"


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

    monkeypatch.setattr(
        "app.ingestion.pipeline.uuid.uuid4",
        lambda: type("StubUUID", (), {"hex": "def456"})(),
    )
    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

    prepared = AudioPreparer(ffmpeg_binary="ffmpeg-test").prepare(source, output_root)

    assert prepared == PreparedTrack(
        source_path=source,
        prepared_path=output_root / "def456_track.mp3",
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
            str(output_root / "def456_track.mp3"),
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


def test_beets_importer_runs_quiet_singleton_move_import(
    tmp_path: Path, monkeypatch
) -> None:
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

    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

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
            "--quiet-fallback=asis",
            "-m",
            "-s",
            str(prepared_path),
        ]
    ]


def test_beets_importer_creates_library_database_parent(
    tmp_path: Path, monkeypatch
) -> None:
    library_root = tmp_path / "music"
    library_database = tmp_path / "data" / "beets" / "library.db"
    prepared_path = tmp_path / "staging" / "track.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        assert library_database.parent.is_dir()
        with sqlite3.connect(library_database) as connection:
            connection.execute(
                "CREATE TABLE items (id INTEGER PRIMARY KEY, path BLOB NOT NULL)"
            )
            connection.execute(
                "INSERT INTO items (id, path) VALUES (?, ?)",
                (1, str(library_root / "Artist" / "track.mp3").encode("utf-8")),
            )
            connection.commit()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

    imported = BeetsImporter(
        library_root=library_root,
        library_database=library_database,
    ).import_file(prepared_path)

    assert imported.library_path == library_root / "Artist" / "track.mp3"
    assert library_database.parent.is_dir()


def test_beets_importer_serializes_library_lookup_and_import(
    tmp_path: Path, monkeypatch
) -> None:
    library_root = tmp_path / "library"
    library_database = tmp_path / "data" / "beets" / "library.db"
    prepared_path = tmp_path / "staging" / "track.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")
    importer = BeetsImporter(
        library_root=library_root,
        library_database=library_database,
    )
    state = {"active": False, "next_previous_id": 0}

    def fake_latest_item_id(self: BeetsImporter, library_database: Path) -> int:
        assert not state["active"]
        state["active"] = True
        previous_id = state["next_previous_id"]
        state["next_previous_id"] += 1
        return previous_id

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        time.sleep(0.05)
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_fetch_imported_track(
        self: BeetsImporter, library_database: Path, previous_item_id: int
    ) -> ImportedTrack:
        state["active"] = False
        return ImportedTrack(
            library_path=library_root / "Artist" / f"track-{previous_item_id + 1}.mp3",
            beets_id=previous_item_id + 1,
        )

    monkeypatch.setattr(BeetsImporter, "_latest_item_id", fake_latest_item_id)
    monkeypatch.setattr(
        BeetsImporter, "_fetch_imported_track", fake_fetch_imported_track
    )
    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

    with ThreadPoolExecutor(max_workers=2) as executor:
        imported = list(
            executor.map(importer.import_file, [prepared_path, prepared_path])
        )

    assert sorted(track.beets_id for track in imported) == [1, 2]


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

    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

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

    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

    try:
        FingerprintGenerator().generate(prepared_path)
    except ValueError as exc:
        assert "fingerprint" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_fingerprint_generator_includes_subprocess_output_in_failure(
    tmp_path: Path, monkeypatch
) -> None:
    prepared_path = tmp_path / "staging" / "track.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            2,
            command,
            output="",
            stderr="empty or unreadable audio file",
        )

    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

    try:
        FingerprintGenerator().generate(prepared_path)
    except RuntimeError as exc:
        assert "Chromaprint fingerprint failed with exit status 2" in str(exc)
        assert "empty or unreadable audio file" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_repair_logs_fingerprint_failures(tmp_path: Path, monkeypatch, caplog) -> None:
    library_path = tmp_path / "library" / "track.mp3"

    def fake_generate(_self: FingerprintGenerator, _audio_path: Path) -> str:
        raise IngestionCommandError("fpcalc failed")

    monkeypatch.setattr(
        "app.ingestion.repair.FingerprintGenerator.generate",
        fake_generate,
    )

    with caplog.at_level(logging.ERROR, logger="app.ingestion.repair"):
        fingerprint = ingestion_repair._fingerprint_or_none(library_path)

    assert fingerprint is None
    assert f"Failed to fingerprint library_path={library_path}" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)


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
    library_root = tmp_path / "library"
    library_path = library_root / "Artist" / "track.mp3"
    library_path.parent.mkdir(parents=True)
    library_path.write_bytes(b"imported")
    library_path.parent.chmod(0o700)
    library_path.chmod(0o600)
    importer.library_root = library_root
    importer.import_file.return_value = ImportedTrack(
        library_path=library_path,
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
    assert result.library_path == library_path
    assert result.beets_id == 17
    assert stat.S_IMODE(library_path.parent.stat().st_mode) & 0o777 == 0o775
    assert stat.S_IMODE(library_path.stat().st_mode) == 0o664
    preparer.prepare.assert_called_once_with(source, tmp_path / "staging")
    fingerprint_generator.generate.assert_called_once_with(prepared.prepared_path)
    importer.import_file.assert_called_once_with(prepared.prepared_path)
    assert source.exists() is False


def test_ingestion_processor_persists_relative_library_path(tmp_path: Path) -> None:
    source = tmp_path / "ingestion" / "track.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    library_root = tmp_path / "library"
    library_database = tmp_path / "library.db"
    prepared = PreparedTrack(
        source_path=source,
        prepared_path=tmp_path / "staging" / "track.mp3",
        transcoded=False,
    )
    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.return_value = prepared
    importer = Mock(spec=BeetsImporter)
    importer.library_root = library_root
    importer.library_database = library_database
    importer.import_file.return_value = ImportedTrack(
        library_path=library_root / "Artist" / "track.mp3",
        beets_id=42,
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "fp-42"

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    beets_mirror_metadata.create_all(engine)
    _create_repair_beets_library(
        library_database,
        items=[
            {
                "id": 42,
                "path": str(library_root / "Artist" / "track.mp3").encode("utf-8"),
                "album_id": 7,
                "title": "Track",
                "artist": "Artist",
                "album": "Album",
            }
        ],
        albums=[
            {
                "id": 7,
                "album": "Album",
                "albumartist": "Artist",
            }
        ],
        item_attributes=[
            (42, "mood", "bright"),
            (42, "source", "import-test"),
        ],
        album_attributes=[(7, "review", "kept")],
    )

    result = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        track_store=LocalTrackStore(database_url),
        database_engine=engine,
    ).process(source)

    with engine.connect() as connection:
        row = connection.execute(select(local_tracks_table)).mappings().one()
        item = connection.execute(select(beets_items_table)).mappings().one()
        album = connection.execute(select(beets_albums_table)).mappings().one()
        item_attributes = (
            connection.execute(
                select(beets_item_attributes_table).order_by(
                    beets_item_attributes_table.c.key
                )
            )
            .mappings()
            .all()
        )
        album_attributes = (
            connection.execute(select(beets_album_attributes_table)).mappings().all()
        )

    assert result.local_track_id == row["id"]
    assert row["file_path"] == "Artist/track.mp3"
    assert row["library_root_rel_path"] == "Artist/track.mp3"
    assert row["fingerprint"] == "fp-42"
    assert row["beets_id"] == 42
    assert item["beets_id"] == 42
    assert item["path"] == str(library_root / "Artist" / "track.mp3")
    assert item["album_id"] == 7
    assert item["title"] == "Track"
    assert item["artist"] == "Artist"
    assert album["beets_album_id"] == 7
    assert album["album"] == "Album"
    assert [(row["key"], row["value"]) for row in item_attributes] == [
        ("mood", "bright"),
        ("source", "import-test"),
    ]
    assert [(row["key"], row["value"]) for row in album_attributes] == [
        ("review", "kept")
    ]


def test_ingestion_processor_updates_existing_beets_mirror_row(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "track.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    library_root = tmp_path / "library"
    library_database = tmp_path / "library.db"
    library_path = library_root / "Artist" / "track.mp3"
    prepared = PreparedTrack(
        source_path=source,
        prepared_path=tmp_path / "staging" / "track.mp3",
        transcoded=False,
    )
    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.return_value = prepared
    importer = Mock(spec=BeetsImporter)
    importer.library_root = library_root
    importer.library_database = library_database
    importer.import_file.return_value = ImportedTrack(
        library_path=library_path,
        beets_id=42,
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "fp-42"

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    beets_mirror_metadata.create_all(engine)
    _create_repair_beets_library(
        library_database,
        items=[
            {
                "id": 42,
                "path": str(library_path).encode("utf-8"),
                "album_id": 7,
                "title": "First Title",
                "artist": "Artist",
            }
        ],
        albums=[{"id": 7, "album": "First Album"}],
        item_attributes=[(42, "mood", "bright")],
        album_attributes=[(7, "source", "first")],
    )

    processor = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        database_engine=engine,
    )

    processor.process(source)

    source.write_bytes(b"mp3")
    with sqlite3.connect(library_database) as connection:
        connection.execute(
            "UPDATE items SET title = ?, artist = ? WHERE id = ?",
            ("Second Title", "Updated Artist", 42),
        )
        connection.execute(
            "UPDATE albums SET album = ? WHERE id = ?",
            ("Second Album", 7),
        )
        connection.execute(
            "DELETE FROM item_attributes WHERE entity_id = ?",
            (42,),
        )
        connection.execute(
            "DELETE FROM album_attributes WHERE entity_id = ?",
            (7,),
        )
        _insert_repair_attribute(connection, "item_attributes", 42, "mood", "dark")
        _insert_repair_attribute(connection, "album_attributes", 7, "source", "second")
        connection.commit()

    processor.process(source)

    with engine.connect() as connection:
        items = connection.execute(select(beets_items_table)).mappings().all()
        item_attributes = (
            connection.execute(select(beets_item_attributes_table)).mappings().all()
        )
        albums = connection.execute(select(beets_albums_table)).mappings().all()
        album_attributes = (
            connection.execute(select(beets_album_attributes_table)).mappings().all()
        )

    assert [(row["beets_id"], row["title"], row["artist"]) for row in items] == [
        (42, "Second Title", "Updated Artist")
    ]
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in item_attributes
    ] == [(42, "mood", "dark")]
    assert [(row["beets_album_id"], row["album"]) for row in albums] == [
        (7, "Second Album")
    ]
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in album_attributes
    ] == [(7, "source", "second")]


def test_ingestion_processor_enqueues_matching_job_after_persisting(
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
        beets_id=42,
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "fp-42"
    enqueuer = Mock(spec=MatchingJobEnqueuer)
    enqueuer.enqueue.return_value = "job-123"
    sonic_enqueuer = Mock(spec=SonicJobEnqueuer)
    sonic_enqueuer.enqueue_feature_extraction.return_value = "sonic-job-123"

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    result = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        track_store=LocalTrackStore(database_url),
        matching_job_enqueuer=enqueuer,
        sonic_job_enqueuer=sonic_enqueuer,
    ).process(source)

    assert result.local_track_id is not None
    assert result.matching_job_id == "job-123"
    assert result.sonic_feature_job_id == "sonic-job-123"
    enqueuer.enqueue.assert_called_once_with(result.local_track_id)
    sonic_enqueuer.enqueue_feature_extraction.assert_called_once_with(
        result.local_track_id
    )


def test_ingestion_processor_retry_updates_existing_local_track_by_beets_id(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "track.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    prepared_tracks = [
        PreparedTrack(
            source_path=source,
            prepared_path=tmp_path / "staging" / "track-first.mp3",
            transcoded=False,
        ),
        PreparedTrack(
            source_path=source,
            prepared_path=tmp_path / "staging" / "track-retry.mp3",
            transcoded=False,
        ),
    ]
    for prepared in prepared_tracks:
        prepared.prepared_path.parent.mkdir(parents=True, exist_ok=True)
        prepared.prepared_path.write_bytes(b"mp3")

    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.side_effect = prepared_tracks
    library_root = tmp_path / "library"
    importer = Mock(spec=BeetsImporter)
    importer.library_root = library_root
    importer.import_file.return_value = ImportedTrack(
        library_path=library_root / "Artist" / "track.mp3",
        beets_id=42,
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.side_effect = ["fp-before-crash", "fp-after-retry"]
    enqueuer = Mock(spec=MatchingJobEnqueuer)
    enqueuer.enqueue.side_effect = [ValueError("job enqueue crashed"), "job-456"]

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    processor = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        track_store=LocalTrackStore(database_url),
        matching_job_enqueuer=enqueuer,
    )

    try:
        processor.process(source)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected mid-pipeline failure")

    assert source.exists()

    result = processor.process(source)

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(local_tracks_table).order_by(local_tracks_table.c.id)
            )
            .mappings()
            .all()
        )

    assert len(rows) == 1
    row = rows[0]
    assert result.local_track_id == row["id"]
    assert result.matching_job_id == "job-456"
    assert row["file_path"] == "Artist/track.mp3"
    assert row["fingerprint"] == "fp-after-retry"
    assert row["beets_id"] == 42
    assert [call.args[0] for call in enqueuer.enqueue.call_args_list] == [
        row["id"],
        row["id"],
    ]
    assert source.exists() is False


def test_ingestion_processor_persists_failed_attempt_with_fingerprint(
    tmp_path: Path,
    caplog,
) -> None:
    source = tmp_path / "ingestion" / "unknown.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    prepared = PreparedTrack(
        source_path=source,
        prepared_path=tmp_path / "staging" / "unknown.mp3",
        transcoded=False,
    )
    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.return_value = prepared
    importer = Mock(spec=BeetsImporter)
    importer.import_file.side_effect = IngestionCommandError(
        "Beets could not identify metadata"
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "fp_failed"

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    failed_ingestion_attempts_metadata.create_all(engine)

    processor = IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        failed_attempt_store=FailedIngestionAttemptStore(database_url),
    )
    with caplog.at_level(logging.ERROR, logger="app.ingestion.pipeline"):
        try:
            processor.process(source)
        except IngestionCommandError:
            pass
        else:
            raise AssertionError("Expected failed Beets import")

    with engine.connect() as connection:
        row = (
            connection.execute(select(failed_ingestion_attempts_table)).mappings().one()
        )

    assert row["source_path"] == str(source)
    assert row["filename"] == "unknown.mp3"
    assert row["fingerprint"] == "fp_failed"
    assert row["failure_reason"] == "Beets could not identify metadata"
    assert row["local_track_id"] is None
    assert "Failed to ingest source_path=" in caplog.text
    assert any(record.exc_info is not None for record in caplog.records)


def test_failed_ingestion_attempt_store_upserts_duplicate_source_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "unknown.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    failed_ingestion_attempts_metadata.create_all(engine)
    store = FailedIngestionAttemptStore(database_url)

    store.persist(
        source_path=source,
        fingerprint="fp-first",
        failure_reason="first failure",
        failed_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
    )
    store.persist(
        source_path=source,
        fingerprint="fp-second",
        failure_reason="second failure",
        failed_at=datetime(2026, 5, 1, 11, 0, tzinfo=UTC),
    )

    with engine.connect() as connection:
        rows = (
            connection.execute(select(failed_ingestion_attempts_table)).mappings().all()
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["source_path"] == str(source)
    assert row["fingerprint"] == "fp-second"
    assert row["failure_reason"] == "second failure"
    assert row["first_failed_at"] == datetime(2026, 5, 1, 10, 0)
    assert row["failed_at"] == datetime(2026, 5, 1, 11, 0)
    assert row["attempt_count"] == 2
    assert row["source_size"] == source.stat().st_size
    assert row["source_mtime_ns"] == source.stat().st_mtime_ns
    assert row["ignored_at"] is None


def test_failed_ingestion_attempt_store_skips_unchanged_sources_and_clears_changed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "unknown.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    failed_ingestion_attempts_metadata.create_all(engine)
    store = FailedIngestionAttemptStore(database_url)
    store.persist(
        source_path=source,
        fingerprint=None,
        failure_reason="Beets could not identify metadata",
    )

    assert store.should_skip_auto_enqueue(source) is True

    source.write_bytes(b"changed mp3")

    assert store.should_skip_auto_enqueue(source) is False
    with engine.connect() as connection:
        rows = connection.execute(select(failed_ingestion_attempts_table)).all()

    assert rows == []


def test_failed_ingestion_attempt_store_ignored_state_is_cleared_by_new_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "unknown.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    failed_ingestion_attempts_metadata.create_all(engine)
    store = FailedIngestionAttemptStore(database_url)
    store.persist(
        source_path=source,
        fingerprint=None,
        failure_reason="first failure",
    )
    attempt_id = store.get(1).id

    ignored = store.mark_ignored(attempt_id)
    assert ignored is not None
    assert ignored.ignored_at is not None
    store.persist(
        source_path=source,
        fingerprint=None,
        failure_reason="retry failed",
    )

    with engine.connect() as connection:
        row = (
            connection.execute(select(failed_ingestion_attempts_table)).mappings().one()
        )

    assert row["attempt_count"] == 2
    assert row["failure_reason"] == "retry failed"
    assert row["ignored_at"] is None


def test_ingestion_processor_clears_prior_failure_after_success(
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
    prepared.prepared_path.parent.mkdir()
    prepared.prepared_path.write_bytes(b"mp3")
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
    failed_ingestion_attempts_metadata.create_all(engine)
    failed_store = FailedIngestionAttemptStore(database_url)
    failed_store.persist(
        source_path=source,
        fingerprint=None,
        failure_reason="Chromaprint fingerprint failed",
    )

    IngestionProcessor(
        staging_root=tmp_path / "staging",
        audio_preparer=preparer,
        beets_importer=importer,
        fingerprint_generator=fingerprint_generator,
        track_store=LocalTrackStore(database_url),
        failed_attempt_store=failed_store,
    ).process(source)

    with engine.connect() as connection:
        rows = connection.execute(select(failed_ingestion_attempts_table)).all()

    assert rows == []


def test_ingestion_processor_deletes_prepared_file_after_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ingestion" / "unknown.mp3"
    source.parent.mkdir()
    source.write_bytes(b"mp3")
    prepared_path = tmp_path / "staging" / "unknown.mp3"
    prepared_path.parent.mkdir()
    prepared_path.write_bytes(b"mp3")
    prepared = PreparedTrack(
        source_path=source,
        prepared_path=prepared_path,
        transcoded=False,
    )
    preparer = Mock(spec=AudioPreparer)
    preparer.prepare.return_value = prepared
    importer = Mock(spec=BeetsImporter)
    importer.import_file.side_effect = IngestionCommandError(
        "Beets could not identify metadata"
    )
    fingerprint_generator = Mock(spec=FingerprintGenerator)
    fingerprint_generator.generate.return_value = "fp_failed"

    try:
        IngestionProcessor(
            staging_root=tmp_path / "staging",
            audio_preparer=preparer,
            beets_importer=importer,
            fingerprint_generator=fingerprint_generator,
        ).process(source)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected failed import")

    assert not prepared_path.exists()
    assert source.exists()


def test_ingestion_processor_smoke_ingests_flac_and_mp3_with_fingerprints(
    tmp_path: Path, monkeypatch
) -> None:
    ingestion_root = tmp_path / "ingestion"
    staging_root = tmp_path / "staging"
    library_root = tmp_path / "library"
    library_database = library_root / "library.db"
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    ingestion_root.mkdir()
    library_root.mkdir()

    mp3_source = ingestion_root / "first-track.mp3"
    flac_source = ingestion_root / "second-track.flac"
    mp3_source.write_bytes(b"mp3-source")
    flac_source.write_bytes(b"flac-source")

    with sqlite3.connect(library_database) as connection:
        connection.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, path BLOB NOT NULL)"
        )
        connection.commit()

    imported_ids: list[int] = []
    uuids = iter(("mp3uuid", "flacuuid"))

    def fake_run(
        command: list[str], *, check: bool, capture_output: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "ffmpeg":
            output_path = Path(command[-1])
            output_path.write_bytes(b"transcoded-mp3")
            return subprocess.CompletedProcess(command, 0, "", "")

        if command[0] == "fpcalc":
            prepared_path = Path(command[-1])
            fingerprint = f"fingerprint-{prepared_path.stem}"
            return subprocess.CompletedProcess(
                command,
                0,
                f'{{"fingerprint":"{fingerprint}"}}',
                "",
            )

        if command[0] == "beet":
            prepared_path = Path(command[-1])
            imported_id = len(imported_ids) + 1
            imported_ids.append(imported_id)
            imported_path = (
                library_root / "Imported" / f"{prepared_path.stem}-imported.mp3"
            )
            imported_path.parent.mkdir(parents=True, exist_ok=True)
            imported_path.write_bytes(prepared_path.read_bytes())
            with sqlite3.connect(library_database) as connection:
                connection.execute(
                    "INSERT INTO items (id, path) VALUES (?, ?)",
                    (imported_id, str(imported_path).encode("utf-8")),
                )
                connection.commit()
            return subprocess.CompletedProcess(command, 0, "", "")

        raise AssertionError(f"Unexpected subprocess command: {command}")

    monkeypatch.setattr(
        "app.ingestion.pipeline.uuid.uuid4",
        lambda: type("StubUUID", (), {"hex": next(uuids)})(),
    )
    monkeypatch.setattr("app.ingestion.pipeline.subprocess.run", fake_run)

    processor = IngestionProcessor(
        staging_root=staging_root,
        beets_importer=BeetsImporter(
            library_root=library_root,
            library_database=library_database,
        ),
        track_store=LocalTrackStore(database_url),
    )

    mp3_result = processor.process(mp3_source)
    flac_result = processor.process(flac_source)

    with engine.connect() as connection:
        rows = connection.execute(
            select(local_tracks_table).order_by(local_tracks_table.c.id)
        ).mappings()
        persisted = list(rows)

    assert mp3_result.transcoded is False
    assert mp3_result.fingerprint == "fingerprint-mp3uuid_first-track"
    assert mp3_result.local_track_id == 1
    assert (
        mp3_result.library_path
        == library_root / "Imported" / "mp3uuid_first-track-imported.mp3"
    )

    assert flac_result.transcoded is True
    assert flac_result.prepared_path.suffix == ".mp3"
    assert flac_result.fingerprint == "fingerprint-flacuuid_second-track"
    assert flac_result.local_track_id == 2
    assert (
        flac_result.library_path
        == library_root / "Imported" / "flacuuid_second-track-imported.mp3"
    )

    assert [row["file_path"] for row in persisted] == [
        "Imported/mp3uuid_first-track-imported.mp3",
        "Imported/flacuuid_second-track-imported.mp3",
    ]
    assert [row["fingerprint"] for row in persisted] == [
        "fingerprint-mp3uuid_first-track",
        "fingerprint-flacuuid_second-track",
    ]
    assert mp3_source.exists() is False
    assert flac_source.exists() is False


def test_repair_beets_mirror_dry_run_reports_without_writing(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_repair_engine(tmp_path)
    _create_repair_beets_library(
        beets_library,
        items=[
            {
                "id": 1,
                "path": b"/music/Artist/Track.mp3",
                "album_id": 7,
                "title": "Track",
                "artist": "Artist",
            }
        ],
        albums=[
            {
                "id": 7,
                "album": "Album",
                "albumartist": "Artist",
            }
        ],
        item_attributes=[(1, "mood", "bright")],
        album_attributes=[(7, "source", "bandcamp")],
    )

    with engine.begin() as connection:
        actions = ingestion_repair._repair_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=False,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "inserted beets_mirror album beets_album_id=7",
    ]
    with engine.connect() as connection:
        assert connection.execute(select(beets_items_table)).all() == []
        assert connection.execute(select(beets_albums_table)).all() == []


def test_repair_beets_mirror_apply_backfills_items_albums_and_attributes(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_repair_engine(tmp_path)
    _create_repair_beets_library(
        beets_library,
        items=[
            {
                "id": 1,
                "path": b"/music/Artist/Track.mp3",
                "album_id": 7,
                "title": "Track",
                "artist": "Artist",
            }
        ],
        albums=[
            {
                "id": 7,
                "album": "Album",
                "albumartist": "Artist",
            }
        ],
        item_attributes=[(1, "mood", "bright")],
        album_attributes=[(7, "source", "bandcamp")],
    )

    with engine.begin() as connection:
        actions = ingestion_repair._repair_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=True,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "inserted beets_mirror album beets_album_id=7",
    ]
    with engine.connect() as connection:
        item = connection.execute(select(beets_items_table)).mappings().one()
        album = connection.execute(select(beets_albums_table)).mappings().one()
        item_attributes = (
            connection.execute(select(beets_item_attributes_table)).mappings().all()
        )
        album_attributes = (
            connection.execute(select(beets_album_attributes_table)).mappings().all()
        )

    assert item["beets_id"] == 1
    assert item["path"] == "/music/Artist/Track.mp3"
    assert item["album_id"] == 7
    assert item["title"] == "Track"
    assert item["artist"] == "Artist"
    assert album["beets_album_id"] == 7
    assert album["album"] == "Album"
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in item_attributes
    ] == [(1, "mood", "bright")]
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in album_attributes
    ] == [(7, "source", "bandcamp")]


def test_repair_beets_mirror_updates_partial_mirror(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_repair_engine(tmp_path)
    _create_repair_beets_library(
        beets_library,
        items=[
            {
                "id": 1,
                "path": b"/music/Artist/Updated.mp3",
                "album_id": 7,
                "title": "Updated",
            },
            {
                "id": 2,
                "path": b"/music/Artist/New.mp3",
                "title": "New",
            },
        ],
        albums=[
            {
                "id": 7,
                "album": "Updated Album",
            }
        ],
        item_attributes=[(1, "mood", "new")],
        album_attributes=[(7, "source", "new")],
    )
    with engine.begin() as connection:
        connection.execute(
            beets_items_table.insert().values(
                beets_id=1,
                path="/music/Artist/Old.mp3",
                album_id=7,
                title="Old",
            )
        )
        connection.execute(
            beets_albums_table.insert().values(
                beets_album_id=7,
                album="Old Album",
            )
        )
        connection.execute(
            beets_item_attributes_table.insert().values(
                entity_id=1,
                key="old",
                value="remove",
            )
        )

    with engine.begin() as connection:
        actions = ingestion_repair._repair_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=True,
        )

    assert actions == [
        "updated beets_mirror item beets_id=1",
        "inserted beets_mirror item beets_id=2",
        "updated beets_mirror album beets_album_id=7",
    ]
    with engine.connect() as connection:
        items = (
            connection.execute(
                select(beets_items_table).order_by(beets_items_table.c.beets_id)
            )
            .mappings()
            .all()
        )
        attributes = (
            connection.execute(select(beets_item_attributes_table)).mappings().all()
        )
        album = connection.execute(select(beets_albums_table)).mappings().one()

    assert [(row["beets_id"], row["title"]) for row in items] == [
        (1, "Updated"),
        (2, "New"),
    ]
    assert [(row["entity_id"], row["key"], row["value"]) for row in attributes] == [
        (1, "mood", "new")
    ]
    assert album["album"] == "Updated Album"


def test_repair_beets_mirror_reports_stale_mirror_items(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_repair_engine(tmp_path)
    _create_repair_beets_library(
        beets_library,
        items=[
            {
                "id": 1,
                "path": b"/music/Artist/Track.mp3",
                "title": "Current",
            }
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            beets_items_table.insert().values(
                beets_id=99,
                path="/music/Missing.mp3",
                title="Missing",
            )
        )

    with engine.begin() as connection:
        actions = ingestion_repair._repair_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=False,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "stale_mirror_items beets_id=99 missing from Beets",
    ]


def test_repair_beets_mirror_reports_stale_local_track_beets_ids(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_repair_engine(tmp_path)
    _create_repair_beets_library(
        beets_library,
        items=[
            {
                "id": 1,
                "path": b"/music/Artist/Track.mp3",
                "title": "Current",
            }
        ],
    )
    with engine.begin() as connection:
        connection.execute(
            local_tracks_table.insert().values(
                file_path="Missing.mp3",
                library_root_rel_path="Missing.mp3",
                fingerprint="fp",
                beets_id=88,
            )
        )

    with engine.begin() as connection:
        actions = ingestion_repair._repair_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=False,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "stale_local_track_beets_ids local_track_id=1 beets_id=88 missing from Beets",
    ]


def _create_repair_engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'repair.db'}")
    metadata.create_all(engine)
    beets_mirror_metadata.create_all(engine)
    return engine


def _create_repair_beets_library(
    path: Path,
    *,
    items: list[dict[str, Any]],
    albums: list[dict[str, Any]] | None = None,
    item_attributes: list[tuple[int, str, str]] | None = None,
    album_attributes: list[tuple[int, str, str]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(_create_repair_beets_table_sql("items", Item._fields))
        connection.execute(_create_repair_beets_table_sql("albums", Album._fields))
        connection.execute(
            """
            CREATE TABLE item_attributes (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE album_attributes (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT
            )
            """
        )
        for item in items:
            _insert_repair_beets_row(connection, "items", item)
        for album in albums or []:
            _insert_repair_beets_row(connection, "albums", album)
        for entity_id, key, value in item_attributes or []:
            _insert_repair_attribute(
                connection,
                "item_attributes",
                entity_id,
                key,
                value,
            )
        for entity_id, key, value in album_attributes or []:
            _insert_repair_attribute(
                connection,
                "album_attributes",
                entity_id,
                key,
                value,
            )
        connection.commit()


def _create_repair_beets_table_sql(table_name: str, fields: dict[str, Any]) -> str:
    column_defs = []
    for field_name, field_type in fields.items():
        if field_name == "id":
            column_defs.append("id INTEGER PRIMARY KEY")
        else:
            column_defs.append(f"{field_name} {field_type.sql}")
    return f"CREATE TABLE {table_name} ({', '.join(column_defs)})"


def _insert_repair_beets_row(
    connection: sqlite3.Connection,
    table_name: str,
    values: dict[str, Any],
) -> None:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
        list(values.values()),
    )


def _insert_repair_attribute(
    connection: sqlite3.Connection,
    table_name: str,
    entity_id: int,
    key: str,
    value: str,
) -> None:
    connection.execute(
        f"INSERT INTO {table_name} (entity_id, key, value) VALUES (?, ?, ?)",
        (entity_id, key, value),
    )
