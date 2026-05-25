"""Sonic feature extraction and generated playlist package."""

from typing import Any

_EXPORT_MODULES = {
    "DEFAULT_SONIC_QUEUE_NAME": "app.sonic.jobs",
    "SonicJobEnqueuer": "app.sonic.jobs",
    "run_playlist_generation_job": "app.sonic.jobs",
    "run_sonic_feature_backfill_job": "app.sonic.jobs",
    "run_sonic_feature_extraction_job": "app.sonic.jobs",
    "run_sonic_feature_reconciliation_job": "app.sonic.jobs",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "DEFAULT_SONIC_QUEUE_NAME",
    "SonicJobEnqueuer",
    "run_playlist_generation_job",
    "run_sonic_feature_backfill_job",
    "run_sonic_feature_extraction_job",
    "run_sonic_feature_reconciliation_job",
]
