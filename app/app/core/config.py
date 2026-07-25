from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_INGESTION_ROOT = Path("/nas/cratelynx/music-in")
DEFAULT_INGESTION_STABILITY_WORKERS = 4
DEFAULT_INGESTION_WORKER_COUNT = 1
DEFAULT_SONIC_WORKER_COUNT = 2
DEFAULT_AUTOPILOT_SCHEDULER_TICK_SECONDS = 30
MAX_INGESTION_STABILITY_WORKERS = 64
MAX_QUEUE_WORKER_COUNT = 32
MAX_AUTOPILOT_SCHEDULER_TICK_SECONDS = 3600
DEFAULT_STAGING_BASE = Path("/tmp")
CRATE_LYNX_STAGING_DIR_ENV = "CRATE_LYNX_STAGING_DIR"
DEFAULT_SONIC_SEMANTIC_MODEL_PATH = Path("/data/models/clap-htsat-unfused-audio.onnx")
DEFAULT_AUTOPILOT_EXPORT_ROOT = Path("/data/exports/autopilot")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    database_url: str | None
    redis_url: str | None
    token_encryption_key: str | None
    ingestion_root: Path
    ingestion_stability_workers: int
    ingestion_worker_count: int
    sonic_worker_count: int
    sonic_semantic_enabled: bool
    sonic_semantic_model_path: Path
    autopilot_scheduler_enabled: bool
    autopilot_scheduler_tick_seconds: int
    autopilot_startup_run_dry_run: bool
    autopilot_export_root: Path
    beets_import_lock_path: Path | None
    warnings: tuple[str, ...] = ()


def load_runtime_config(environ: Mapping[str, str] | None = None) -> RuntimeConfig:
    env = os.environ if environ is None else environ
    warnings: list[str] = []
    return RuntimeConfig(
        database_url=optional_env("DATABASE_URL", env),
        redis_url=optional_env("REDIS_URL", env),
        token_encryption_key=optional_env("TOKEN_ENCRYPTION_KEY", env),
        ingestion_root=path_env("INGESTION_ROOT", DEFAULT_INGESTION_ROOT, env),
        ingestion_stability_workers=int_env(
            "INGESTION_STABILITY_WORKERS",
            DEFAULT_INGESTION_STABILITY_WORKERS,
            env,
            minimum=1,
            maximum=MAX_INGESTION_STABILITY_WORKERS,
            warnings=warnings,
        ),
        ingestion_worker_count=int_env(
            "INGESTION_WORKER_COUNT",
            DEFAULT_INGESTION_WORKER_COUNT,
            env,
            minimum=1,
            maximum=MAX_QUEUE_WORKER_COUNT,
            warnings=warnings,
        ),
        sonic_worker_count=int_env(
            "SONIC_WORKER_COUNT",
            DEFAULT_SONIC_WORKER_COUNT,
            env,
            minimum=1,
            maximum=MAX_QUEUE_WORKER_COUNT,
            warnings=warnings,
        ),
        sonic_semantic_enabled=bool_env(
            "SONIC_SEMANTIC_ENABLED",
            False,
            env,
            warnings=warnings,
        ),
        sonic_semantic_model_path=path_env(
            "SONIC_SEMANTIC_MODEL_PATH",
            DEFAULT_SONIC_SEMANTIC_MODEL_PATH,
            env,
        ),
        autopilot_scheduler_enabled=bool_env(
            "AUTOPILOT_SCHEDULER_ENABLED",
            True,
            env,
            warnings=warnings,
        ),
        autopilot_scheduler_tick_seconds=int_env(
            "AUTOPILOT_SCHEDULER_TICK_SECONDS",
            DEFAULT_AUTOPILOT_SCHEDULER_TICK_SECONDS,
            env,
            minimum=5,
            maximum=MAX_AUTOPILOT_SCHEDULER_TICK_SECONDS,
            warnings=warnings,
        ),
        autopilot_startup_run_dry_run=bool_env(
            "AUTOPILOT_STARTUP_RUN_DRY_RUN",
            False,
            env,
            warnings=warnings,
        ),
        autopilot_export_root=path_env(
            "AUTOPILOT_EXPORT_ROOT",
            DEFAULT_AUTOPILOT_EXPORT_ROOT,
            env,
        ),
        beets_import_lock_path=(
            Path(lock_path)
            if (lock_path := optional_env("BEETS_IMPORT_LOCK_PATH", env))
            else None
        ),
        warnings=tuple(warnings),
    )


def optional_env(name: str, environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    value = env.get(name)
    if value is None:
        return None

    value = value.strip()
    return value or None


def path_env(
    name: str,
    default: Path,
    environ: Mapping[str, str] | None = None,
) -> Path:
    value = optional_env(name, environ)
    return Path(value) if value is not None else default


def int_env(
    name: str,
    default: int,
    environ: Mapping[str, str] | None = None,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    warnings: list[str] | None = None,
) -> int:
    value = optional_env(name, environ)
    if value is None:
        return default

    try:
        parsed = int(value)
    except ValueError:
        if warnings is not None:
            warnings.append(f"Invalid integer for {name}={value!r}; using {default}")
        return default

    if minimum is not None and parsed < minimum:
        if warnings is not None:
            warnings.append(f"{name}={parsed} is below {minimum}; using {minimum}")
        return minimum
    if maximum is not None and parsed > maximum:
        if warnings is not None:
            warnings.append(f"{name}={parsed} exceeds {maximum}; using {maximum}")
        return maximum
    return parsed


def bool_env(
    name: str,
    default: bool,
    environ: Mapping[str, str] | None = None,
    *,
    warnings: list[str] | None = None,
) -> bool:
    value = optional_env(name, environ)
    if value is None:
        return default

    normalized = value.casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    if warnings is not None:
        warnings.append(f"Invalid boolean for {name}={value!r}; using {default}")
    return default


def default_staging_path(name: str) -> Path:
    return DEFAULT_STAGING_BASE / f"crate-lynx-{name}"


def resolve_staging_path(
    specific_env_var: str,
    name: str,
    environ: Mapping[str, str] | None = None,
) -> Path:
    configured_path = optional_env(specific_env_var, environ)
    if configured_path is not None:
        return Path(configured_path)

    configured_root = optional_env(CRATE_LYNX_STAGING_DIR_ENV, environ)
    if configured_root is not None:
        return Path(configured_root) / name

    return default_staging_path(name)
