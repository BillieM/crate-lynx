from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import threading
import time
from typing import Callable, Iterable

from watchdog.events import FileClosedEvent, FileMovedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.ingestion.pipeline import SUPPORTED_AUDIO_EXTENSIONS


FileCallback = Callable[[Path], None]
SleepCallback = Callable[[float], None]
ClockCallback = Callable[[], float]
WatchHandle = object
logger = logging.getLogger(__name__)
DEFAULT_STABILITY_OBSERVATIONS = 10
DEFAULT_STABILITY_INTERVAL_SECONDS = 0.5
DEFAULT_RECENTLY_HANDLED_TTL_SECONDS = 30.0
DEFAULT_SCAN_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    size: int
    mtime_ns: int


class IngestionEventHandler(FileSystemEventHandler):
    def __init__(self, on_candidate_file: FileCallback) -> None:
        self._on_candidate_file = on_candidate_file

    def on_closed(self, event: FileClosedEvent) -> None:
        if event.is_directory:
            return

        self._on_candidate_file(Path(event.src_path))

    def on_moved(self, event: FileMovedEvent) -> None:
        if event.is_directory:
            return

        self._on_candidate_file(Path(event.dest_path))


@dataclass(slots=True)
class IngestionWatcher:
    root: Path | str | Iterable[Path | str]
    on_new_file: FileCallback
    recursive: bool = False
    observer_factory: Callable[[], Observer] = Observer
    stability_observations: int = DEFAULT_STABILITY_OBSERVATIONS
    stability_interval_seconds: float = DEFAULT_STABILITY_INTERVAL_SECONDS
    recently_handled_ttl_seconds: float = DEFAULT_RECENTLY_HANDLED_TTL_SECONDS
    scan_interval_seconds: float = DEFAULT_SCAN_INTERVAL_SECONDS
    sleep: SleepCallback = time.sleep
    clock: ClockCallback = time.monotonic
    _observer: Observer | None = field(default=None, init=False, repr=False)
    _scan_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_scan_event: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _state_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    _roots: set[Path] = field(default_factory=set, init=False, repr=False)
    _watches: dict[Path, WatchHandle] = field(
        default_factory=dict, init=False, repr=False
    )
    _in_flight: set[Path] = field(default_factory=set, init=False, repr=False)
    _recently_handled: dict[Path, float] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        roots: Iterable[Path | str]
        if isinstance(self.root, Path | str):
            roots = (self.root,)
        else:
            roots = self.root

        self._roots = {self._normalize_root(root) for root in roots}

    @property
    def roots(self) -> tuple[Path, ...]:
        return tuple(sorted(self._roots, key=str))

    def start(self) -> None:
        if self._observer is not None:
            return

        observer = self.observer_factory()
        for root_path in self.roots:
            self._schedule_root(observer, root_path)
        observer.start()
        self._observer = observer
        self._scan_existing_files()
        self._start_periodic_scan()

    def stop(self) -> None:
        if self._observer is None:
            return

        self._stop_periodic_scan()
        self._observer.stop()
        self._observer.join()
        self._observer = None
        self._watches.clear()

    def add_root(self, root: Path | str) -> None:
        root_path = self._normalize_root(root)
        if root_path in self._roots:
            return

        self._roots.add(root_path)
        if self._observer is not None:
            self._schedule_root(self._observer, root_path)
            self._scan_root(root_path)

    def remove_root(self, root: Path | str) -> None:
        root_path = self._normalize_root(root)
        if root_path not in self._roots:
            return

        self._roots.remove(root_path)
        watch = self._watches.pop(root_path, None)
        if self._observer is not None and watch is not None:
            self._observer.unschedule(watch)

    @staticmethod
    def _normalize_root(root: Path | str) -> Path:
        return Path(root).expanduser().resolve(strict=False)

    def _schedule_root(self, observer: Observer, root_path: Path) -> None:
        root_path.mkdir(parents=True, exist_ok=True)
        watch = observer.schedule(
            IngestionEventHandler(self._ingest_candidate),
            str(root_path),
            recursive=self.recursive,
        )
        self._watches[root_path] = watch

    def _start_periodic_scan(self) -> None:
        if self._scan_thread is not None:
            return

        self._stop_scan_event.clear()
        self._scan_thread = threading.Thread(
            target=self._run_periodic_scan,
            name="crate-lynx-ingestion-scan",
            daemon=True,
        )
        self._scan_thread.start()

    def _stop_periodic_scan(self) -> None:
        if self._scan_thread is None:
            return

        self._stop_scan_event.set()
        self._scan_thread.join()
        self._scan_thread = None

    def _run_periodic_scan(self) -> None:
        while not self._stop_scan_event.wait(self.scan_interval_seconds):
            self._scan_existing_files()

    def _scan_existing_files(self) -> None:
        for root_path in self.roots:
            self._scan_root(root_path)

    def _scan_root(self, root_path: Path) -> None:
        paths = root_path.rglob("*") if self.recursive else root_path.iterdir()
        for candidate_path in sorted(paths, key=str):
            if not candidate_path.is_file():
                continue
            self._ingest_candidate(candidate_path)

    def _ingest_candidate(self, source_path: Path) -> None:
        if not _is_supported_audio_file(source_path):
            return

        cache_path = source_path.resolve(strict=False)
        if not self._claim_candidate(cache_path):
            return

        try:
            if not _is_stable_file(
                source_path,
                observations=self.stability_observations,
                interval_seconds=self.stability_interval_seconds,
                sleep=self.sleep,
            ):
                return

            self._mark_recently_handled(cache_path)
            self.on_new_file(source_path)
        except Exception:
            logger.exception("Failed to ingest file: %s", source_path)
        finally:
            self._release_candidate(cache_path)

    def _claim_candidate(self, cache_path: Path) -> bool:
        with self._state_lock:
            self._prune_recently_handled()
            if cache_path in self._in_flight or cache_path in self._recently_handled:
                return False

            self._in_flight.add(cache_path)
            return True

    def _mark_recently_handled(self, cache_path: Path) -> None:
        with self._state_lock:
            self._recently_handled[cache_path] = self.clock()

    def _release_candidate(self, cache_path: Path) -> None:
        with self._state_lock:
            self._in_flight.discard(cache_path)

    def _prune_recently_handled(self) -> None:
        expires_before = self.clock() - self.recently_handled_ttl_seconds
        self._recently_handled = {
            path: handled_at
            for path, handled_at in self._recently_handled.items()
            if handled_at >= expires_before
        }


def _is_stable_file(
    path: Path,
    *,
    observations: int,
    interval_seconds: float,
    sleep: SleepCallback,
) -> bool:
    previous_snapshot = _snapshot_file(path)
    if previous_snapshot is None:
        return False

    for _ in range(max(1, observations) - 1):
        sleep(interval_seconds)
        next_snapshot = _snapshot_file(path)
        if next_snapshot is None or next_snapshot != previous_snapshot:
            return False

    return True


def _snapshot_file(path: Path) -> FileSnapshot | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None

    if not path.is_file():
        return None

    return FileSnapshot(size=stat_result.st_size, mtime_ns=stat_result.st_mtime_ns)


def _is_supported_audio_file(path: Path) -> bool:
    if path.name.startswith("."):
        return False

    return path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
