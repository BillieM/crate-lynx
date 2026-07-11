from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from cryptography.fernet import Fernet

from app.core.config import load_runtime_config, optional_env
from app.soulseek.config import SoulseekConfigurationError, load_slskd_config


def collect_preflight_errors(
    environ: Mapping[str, str] | None = None,
    *,
    check_paths: bool = True,
) -> tuple[str, ...]:
    env = os.environ if environ is None else environ
    errors: list[str] = []
    config = load_runtime_config(env)

    for name, value in (
        ("DATABASE_URL", config.database_url),
        ("REDIS_URL", config.redis_url),
        ("TOKEN_ENCRYPTION_KEY", config.token_encryption_key),
    ):
        if value is None:
            errors.append(f"{name} must be configured")

    if config.token_encryption_key is not None:
        try:
            Fernet(config.token_encryption_key.encode("utf-8"))
        except (TypeError, ValueError):
            errors.append("TOKEN_ENCRYPTION_KEY must be a valid Fernet key")

    errors.extend(config.warnings)
    _validate_slskd(env, errors)

    if check_paths:
        _validate_paths(env, config.beets_import_lock_path, errors)

    return tuple(errors)


def _validate_slskd(env: Mapping[str, str], errors: list[str]) -> None:
    base_url = optional_env("SLSKD_BASE_URL", env)
    api_key = optional_env("SLSKD_API_KEY", env)
    if bool(base_url) != bool(api_key):
        errors.append("SLSKD_BASE_URL and SLSKD_API_KEY must be configured together")
        return
    if base_url is None:
        return

    try:
        load_slskd_config(env)
    except SoulseekConfigurationError as exc:
        errors.append(str(exc))

    if optional_env("SLSKD_WEBHOOK_TOKEN", env) is None:
        errors.append("SLSKD_WEBHOOK_TOKEN must be configured when Soulseek is enabled")


def _validate_paths(
    env: Mapping[str, str],
    beets_import_lock_path: Path | None,
    errors: list[str],
) -> None:
    beets_library = Path(optional_env("BEETS_LIBRARY", env) or "/data/beets/library.db")
    lock_path = beets_import_lock_path or beets_library.with_name(
        f"{beets_library.name}.import.lock"
    )
    directory_paths = {
        "LIBRARY_ROOT": Path(optional_env("LIBRARY_ROOT", env) or "/nas/media/music"),
        "LOCAL_DEDUPE_QUARANTINE_ROOT": Path(
            optional_env("LOCAL_DEDUPE_QUARANTINE_ROOT", env)
            or "/nas/cratelynx/dedupe-quarantine"
        ),
        "CRATE_LYNX_STAGING_DIR": Path(
            optional_env("CRATE_LYNX_STAGING_DIR", env) or "/nas/cratelynx/staging"
        ),
        "INGESTION_ROOT": Path(
            optional_env("INGESTION_ROOT", env) or "/nas/cratelynx/music-in"
        ),
        "BEETS_LIBRARY parent": beets_library.parent,
        "BEETS_IMPORT_LOCK_PATH parent": lock_path.parent,
    }
    if optional_env("SLSKD_BASE_URL", env):
        directory_paths["SLSKD_DOWNLOADS_APP_ROOT"] = Path(
            optional_env("SLSKD_DOWNLOADS_APP_ROOT", env) or "/nas/soulseek/downloads"
        )

    for name, path in directory_paths.items():
        if not path.is_absolute():
            errors.append(f"{name} must resolve to an absolute container path: {path}")
        elif not path.is_dir():
            errors.append(f"{name} directory does not exist: {path}")
        elif not os.access(path, os.W_OK | os.X_OK):
            errors.append(f"{name} directory is not writable: {path}")


def main() -> int:
    errors = collect_preflight_errors()
    if errors:
        print("Crate Lynx configuration preflight failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Crate Lynx configuration preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
