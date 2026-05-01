from pathlib import Path

from watchdog.events import DirCreatedEvent, FileCreatedEvent

from app.ingestion import IngestionEventHandler, IngestionWatcher


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
