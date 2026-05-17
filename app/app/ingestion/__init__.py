"""Ingestion pipeline and filesystem watcher package."""

from app.ingestion.pipeline import (
    AudioPreparer,
    BeetsImporter,
    FingerprintGenerator,
    ImportedTrack,
    IngestionProcessor,
    PreparedTrack,
    UnsupportedAudioFormatError,
    build_ingestion_processor,
)
from app.ingestion.jobs import IngestionJobEnqueuer, run_ingestion_job
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
    "IngestionJobEnqueuer",
    "IngestionProcessor",
    "IngestionWatcher",
    "PreparedTrack",
    "UnsupportedAudioFormatError",
    "build_ingestion_processor",
    "failed_ingestion_attempts_metadata",
    "failed_ingestion_attempts_table",
    "run_ingestion_job",
]
