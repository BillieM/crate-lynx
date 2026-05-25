"""Ingestion pipeline and filesystem watcher package."""

from typing import Any

_EXPORT_MODULES = {
    "AudioPreparer": "app.ingestion.pipeline",
    "BeetsImporter": "app.ingestion.pipeline",
    "FileCallback": "app.ingestion.watcher",
    "FailedIngestionAttempt": "app.ingestion.failures",
    "FailedIngestionAttemptStore": "app.ingestion.failures",
    "FingerprintGenerator": "app.ingestion.pipeline",
    "ImportedTrack": "app.ingestion.pipeline",
    "IngestionEventHandler": "app.ingestion.watcher",
    "IngestionJobEnqueuer": "app.ingestion.jobs",
    "IngestionProcessor": "app.ingestion.pipeline",
    "IngestionWatcher": "app.ingestion.watcher",
    "PreparedTrack": "app.ingestion.pipeline",
    "UnsupportedAudioFormatError": "app.ingestion.pipeline",
    "build_ingestion_processor": "app.ingestion.pipeline",
    "failed_ingestion_attempts_metadata": "app.ingestion.failures",
    "failed_ingestion_attempts_table": "app.ingestion.failures",
    "run_ingestion_job": "app.ingestion.jobs",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module

    module = import_module(module_name)
    if name == "failed_ingestion_attempts_metadata":
        value = module.metadata
    else:
        value = getattr(module, name)
    globals()[name] = value
    return value


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
