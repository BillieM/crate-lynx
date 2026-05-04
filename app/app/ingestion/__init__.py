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
from app.ingestion.failures import (
    FailedIngestionAttempt,
    FailedIngestionAttemptStore,
    failed_ingestion_attempts_table,
    metadata as failed_ingestion_attempts_metadata,
)
from app.ingestion.router import router
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
    "FailedIngestionAttempt",
    "FailedIngestionAttemptStore",
    "FingerprintGenerator",
    "ImportedTrack",
    "IngestionEventHandler",
    "IngestionProcessor",
    "IngestionStatusEntry",
    "IngestionStatusStore",
    "IngestionWatcher",
    "PreparedTrack",
    "router",
    "UnsupportedAudioFormatError",
    "failed_ingestion_attempts_metadata",
    "failed_ingestion_attempts_table",
]
