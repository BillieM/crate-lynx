from __future__ import annotations

import os
from pathlib import Path


CRATE_LYNX_STAGING_DIR_ENV = "CRATE_LYNX_STAGING_DIR"
DEFAULT_STAGING_BASE = Path("/tmp")


def default_staging_path(name: str) -> Path:
    return DEFAULT_STAGING_BASE / f"crate-lynx-{name}"


def resolve_staging_path(specific_env_var: str, name: str) -> Path:
    configured_path = os.environ.get(specific_env_var)
    if configured_path:
        return Path(configured_path)

    configured_root = os.environ.get(CRATE_LYNX_STAGING_DIR_ENV)
    if configured_root:
        return Path(configured_root) / name

    return default_staging_path(name)
