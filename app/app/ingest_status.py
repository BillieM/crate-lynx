from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.ingestion import PreparedTrack


QueueDepthReader = Callable[[], Mapping[str, int | None]]


@dataclass(slots=True)
class IngestionStatusEntry:
    timestamp: datetime
    status: str
    source_path: str
    library_path: str | None = None
    fingerprint: str | None = None
    local_track_id: int | None = None
    matching_job_id: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "source_path": self.source_path,
            "library_path": self.library_path,
            "fingerprint": self.fingerprint,
            "local_track_id": self.local_track_id,
            "matching_job_id": self.matching_job_id,
            "error": self.error,
        }


class IngestionStatusStore:
    def __init__(
        self,
        *,
        queue_depth_reader: QueueDepthReader,
        max_results: int = 20,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._queue_depth_reader = queue_depth_reader
        self._recent_results: deque[IngestionStatusEntry] = deque(maxlen=max_results)
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = Lock()

    def record_success(
        self,
        *,
        source_path: Path | str,
        prepared_track: PreparedTrack,
    ) -> None:
        self._append(
            IngestionStatusEntry(
                timestamp=self._now(),
                status="ok",
                source_path=str(source_path),
                library_path=(
                    str(prepared_track.library_path)
                    if prepared_track.library_path is not None
                    else None
                ),
                fingerprint=prepared_track.fingerprint,
                local_track_id=prepared_track.local_track_id,
                matching_job_id=prepared_track.matching_job_id,
            )
        )

    def record_failure(self, *, source_path: Path | str, error: Exception) -> None:
        self._append(
            IngestionStatusEntry(
                timestamp=self._now(),
                status="error",
                source_path=str(source_path),
                error=str(error),
            )
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent_results = [entry.as_dict() for entry in self._recent_results]

        return {
            "queue_depths": dict(self._queue_depth_reader()),
            "recent_results": recent_results,
        }

    def _append(self, entry: IngestionStatusEntry) -> None:
        with self._lock:
            self._recent_results.appendleft(entry)
