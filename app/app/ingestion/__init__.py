"""Ingestion pipeline, status, and filesystem watcher package."""

from app.ingestion.pipeline import (
    AudioPreparer,
    BeetsImporter,
    FingerprintGenerator,
    ImportedTrack,
    IngestionProcessor,
    PreparedTrack,
    UnsupportedAudioFormatError,
)
from app.ingestion.status import IngestionStatusEntry, IngestionStatusStore
from app.ingestion.watcher import (
    FileCallback,
    IngestionEventHandler,
    IngestionWatcher,
)

__all__ = [
    "AudioPreparer",
    "BeetsImporter",
    "FileCallback",
    "FingerprintGenerator",
    "ImportedTrack",
    "IngestionEventHandler",
    "IngestionProcessor",
    "IngestionStatusEntry",
    "IngestionStatusStore",
    "IngestionWatcher",
    "PreparedTrack",
    "UnsupportedAudioFormatError",
]
