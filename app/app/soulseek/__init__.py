"""Soulseek/slskd acquisition package."""

from typing import Any

_EXPORT_MODULES = {
    "SOULSEEK_BULK_SEARCH_LIMIT": "app.soulseek.models",
    "SOULSEEK_QUEUE_NAME": "app.soulseek.models",
    "SOULSEEK_STATUS_CANDIDATES_FOUND": "app.soulseek.models",
    "SOULSEEK_STATUS_COMPLETED": "app.soulseek.models",
    "SOULSEEK_STATUS_DOWNLOADING": "app.soulseek.models",
    "SOULSEEK_STATUS_FAILED": "app.soulseek.models",
    "SOULSEEK_STATUS_INGESTED": "app.soulseek.models",
    "SOULSEEK_STATUS_LINKED": "app.soulseek.models",
    "SOULSEEK_STATUS_LINK_FAILED": "app.soulseek.models",
    "SOULSEEK_STATUS_NO_CANDIDATES": "app.soulseek.models",
    "SOULSEEK_STATUS_PROPOSAL_AVAILABLE": "app.soulseek.models",
    "SOULSEEK_STATUS_QUEUED": "app.soulseek.models",
    "SOULSEEK_STATUS_SEARCHING": "app.soulseek.models",
    "SoulseekStore": "app.soulseek.store",
    "create_router": "app.soulseek.router",
    "enqueue_soulseek_candidate": "app.soulseek.jobs",
    "metadata": "app.soulseek.models",
    "refresh_soulseek_acquisition": "app.soulseek.jobs",
    "search_missing_track": "app.soulseek.jobs",
    "soulseek_acquisitions_table": "app.soulseek.models",
    "soulseek_candidates_table": "app.soulseek.models",
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


__all__ = sorted(_EXPORT_MODULES)
