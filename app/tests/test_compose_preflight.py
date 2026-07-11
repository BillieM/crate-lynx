from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from app.core.compose_preflight import collect_preflight_errors


def _valid_environment(root: Path) -> dict[str, str]:
    paths = {
        "LIBRARY_ROOT": root / "library",
        "LOCAL_DEDUPE_QUARANTINE_ROOT": root / "quarantine",
        "CRATE_LYNX_STAGING_DIR": root / "staging",
        "INGESTION_ROOT": root / "ingestion",
        "BEETS_LIBRARY": root / "app-data" / "library.db",
        "BEETS_IMPORT_LOCK_PATH": root / "app-data" / "library.db.import.lock",
    }
    for name, path in paths.items():
        directory = (
            path.parent if name in {"BEETS_LIBRARY", "BEETS_IMPORT_LOCK_PATH"} else path
        )
        directory.mkdir(parents=True, exist_ok=True)

    return {
        "DATABASE_URL": "postgresql+psycopg://user:password@db/crate_lynx",
        "REDIS_URL": "redis://redis:6379/0",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        **{name: str(path) for name, path in paths.items()},
    }


def test_compose_preflight_accepts_complete_core_configuration(tmp_path: Path) -> None:
    assert collect_preflight_errors(_valid_environment(tmp_path)) == ()


def test_compose_preflight_rejects_invalid_secret_and_worker_bounds(
    tmp_path: Path,
) -> None:
    environ = _valid_environment(tmp_path)
    environ["TOKEN_ENCRYPTION_KEY"] = "not-a-fernet-key"
    environ["INGESTION_WORKER_COUNT"] = "0"
    environ["SONIC_WORKER_COUNT"] = "many"

    errors = collect_preflight_errors(environ)

    assert "TOKEN_ENCRYPTION_KEY must be a valid Fernet key" in errors
    assert "INGESTION_WORKER_COUNT=0 is below 1; using 1" in errors
    assert "Invalid integer for SONIC_WORKER_COUNT='many'; using 2" in errors


def test_compose_preflight_requires_complete_valid_soulseek_configuration(
    tmp_path: Path,
) -> None:
    environ = _valid_environment(tmp_path)
    environ["SLSKD_BASE_URL"] = "http://slskd:5030"
    assert collect_preflight_errors(environ, check_paths=False) == (
        "SLSKD_BASE_URL and SLSKD_API_KEY must be configured together",
    )

    environ["SLSKD_API_KEY"] = "secret"
    environ["SLSKD_RESPONSE_LIMIT"] = "0"
    errors = collect_preflight_errors(environ, check_paths=False)
    assert "SLSKD_RESPONSE_LIMIT must be between 1 and 10000; got 0" in errors
    assert "SLSKD_WEBHOOK_TOKEN must be configured when Soulseek is enabled" in errors


def test_compose_preflight_reports_missing_mounted_directory(tmp_path: Path) -> None:
    environ = _valid_environment(tmp_path)
    missing_path = tmp_path / "missing-library"
    environ["LIBRARY_ROOT"] = str(missing_path)

    assert (
        f"LIBRARY_ROOT directory does not exist: {missing_path}"
        in collect_preflight_errors(environ)
    )
