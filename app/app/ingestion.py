from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer


FileCallback = Callable[[Path], None]


class IngestionEventHandler(FileSystemEventHandler):
    def __init__(self, on_new_file: FileCallback) -> None:
        self._on_new_file = on_new_file

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return

        self._on_new_file(Path(event.src_path))


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
