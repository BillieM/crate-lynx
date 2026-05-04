from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Callable, Iterable

from watchdog.events import FileClosedEvent, FileSystemEventHandler
from watchdog.observers import Observer


FileCallback = Callable[[Path], None]
WatchHandle = object
logger = logging.getLogger(__name__)


class IngestionEventHandler(FileSystemEventHandler):
    def __init__(self, on_new_file: FileCallback) -> None:
        self._on_new_file = on_new_file

    def on_closed(self, event: FileClosedEvent) -> None:
        source_path = Path(event.src_path)
        try:
            self._on_new_file(source_path)
        except Exception:
            logger.exception("Failed to ingest file: %s", source_path)


@dataclass(slots=True)
class IngestionWatcher:
    root: Path | str | Iterable[Path | str]
    on_new_file: FileCallback
    recursive: bool = False
    observer_factory: Callable[[], Observer] = Observer
    _observer: Observer | None = field(default=None, init=False, repr=False)
    _roots: set[Path] = field(default_factory=set, init=False, repr=False)
    _watches: dict[Path, WatchHandle] = field(
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

    def stop(self) -> None:
        if self._observer is None:
            return

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
            IngestionEventHandler(self.on_new_file),
            str(root_path),
            recursive=self.recursive,
        )
        self._watches[root_path] = watch
