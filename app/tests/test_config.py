from __future__ import annotations

from pathlib import Path

from app.core.config import load_runtime_config, resolve_staging_path


def test_runtime_config_strips_optional_values_and_resolves_paths() -> None:
    config = load_runtime_config(
        {
            "DATABASE_URL": " sqlite:///crate-lynx.db ",
            "REDIS_URL": " redis://redis:6379/0 ",
            "TOKEN_ENCRYPTION_KEY": " key ",
            "INGESTION_ROOT": " /tmp/incoming ",
            "INGESTION_STABILITY_WORKERS": "2",
            "INGESTION_WORKER_COUNT": "3",
            "SONIC_WORKER_COUNT": "4",
            "BEETS_IMPORT_LOCK_PATH": " /tmp/beets.lock ",
        }
    )

    assert config.database_url == "sqlite:///crate-lynx.db"
    assert config.redis_url == "redis://redis:6379/0"
    assert config.token_encryption_key == "key"
    assert config.ingestion_root == Path("/tmp/incoming")
    assert config.ingestion_stability_workers == 2
    assert config.ingestion_worker_count == 3
    assert config.sonic_worker_count == 4
    assert config.beets_import_lock_path == Path("/tmp/beets.lock")
    assert config.warnings == ()


def test_runtime_config_defaults_blank_values_and_invalid_worker_count() -> None:
    config = load_runtime_config(
        {
            "DATABASE_URL": "",
            "REDIS_URL": " ",
            "INGESTION_ROOT": "",
            "INGESTION_STABILITY_WORKERS": "many",
        }
    )

    assert config.database_url is None
    assert config.redis_url is None
    assert config.ingestion_root == Path("/nas/cratelynx/music-in")
    assert config.ingestion_stability_workers == 4
    assert config.ingestion_worker_count == 1
    assert config.sonic_worker_count == 2
    assert config.beets_import_lock_path is None
    assert config.warnings == (
        "Invalid integer for INGESTION_STABILITY_WORKERS='many'; using 4",
    )


def test_runtime_config_clamps_worker_count_to_one() -> None:
    config = load_runtime_config({"INGESTION_STABILITY_WORKERS": "0"})

    assert config.ingestion_stability_workers == 1
    assert config.warnings == ("INGESTION_STABILITY_WORKERS=0 is below 1; using 1",)


def test_runtime_config_bounds_all_worker_counts_with_explicit_warnings() -> None:
    config = load_runtime_config(
        {
            "INGESTION_STABILITY_WORKERS": "65",
            "INGESTION_WORKER_COUNT": "0",
            "SONIC_WORKER_COUNT": "33",
        }
    )

    assert config.ingestion_stability_workers == 64
    assert config.ingestion_worker_count == 1
    assert config.sonic_worker_count == 32
    assert config.warnings == (
        "INGESTION_STABILITY_WORKERS=65 exceeds 64; using 64",
        "INGESTION_WORKER_COUNT=0 is below 1; using 1",
        "SONIC_WORKER_COUNT=33 exceeds 32; using 32",
    )


def test_resolve_staging_path_prefers_specific_env_then_shared_root() -> None:
    assert resolve_staging_path(
        "INGESTION_STAGING_ROOT",
        "ingestion-staging",
        {
            "INGESTION_STAGING_ROOT": "/tmp/specific",
            "CRATE_LYNX_STAGING_DIR": "/tmp/root",
        },
    ) == Path("/tmp/specific")
    assert resolve_staging_path(
        "INGESTION_STAGING_ROOT",
        "ingestion-staging",
        {"CRATE_LYNX_STAGING_DIR": "/tmp/root"},
    ) == Path("/tmp/root/ingestion-staging")
    assert resolve_staging_path(
        "INGESTION_STAGING_ROOT",
        "ingestion-staging",
        {},
    ) == Path("/tmp/crate-lynx-ingestion-staging")
