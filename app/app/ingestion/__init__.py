"""Ingestion pipeline and filesystem watcher package."""

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
    "IngestionWatcher",
    "PreparedTrack",
    "UnsupportedAudioFormatError",
    "failed_ingestion_attempts_metadata",
    "failed_ingestion_attempts_table",
]
