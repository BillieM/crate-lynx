from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.m3u.exporter import (
    DEFAULT_M3U_EXPORT_FORMATS,
    SUPPORTED_M3U_EXPORT_FORMATS,
    build_m3u_export_package,
)
from app.m3u.generator import SUPPORTED_M3U_EXPORT_PATH_FORMATS
from app.m3u.store import M3uExportProfileStore
from app.sonic.models import generated_playlists_table

DEFAULT_AUTOPILOT_EXPORT_ROOT = "/data/exports/autopilot"
SUPPORTED_EXPORT_SCOPES = frozenset({"leaf_only", "all"})
SUPPORTED_EXPORT_CONFIG_KEYS = frozenset(
    {"enabled", "profile_id", "formats", "path_format", "scope"}
)


@dataclass(frozen=True, slots=True)
class RecipeExportConfig:
    enabled: bool
    profile_id: int
    formats: tuple[str, ...]
    path_format: str
    scope: str


@dataclass(frozen=True, slots=True)
class RecipeExportResult:
    recipe_id: int
    run_id: int
    directory: Path
    playlist_count: int
    file_count: int
    exported_track_count: int
    skipped_track_count: int


def normalize_recipe_export_config(
    raw: dict[str, Any] | None,
) -> RecipeExportConfig | None:
    if raw is None:
        return None
    unknown = set(raw) - SUPPORTED_EXPORT_CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"Unsupported autopilot export config field(s): {sorted(unknown)}"
        )
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("Autopilot export enabled must be a boolean")
    if not enabled:
        return None
    profile_id = raw.get("profile_id")
    if (
        not isinstance(profile_id, int)
        or isinstance(profile_id, bool)
        or profile_id <= 0
    ):
        raise ValueError("Autopilot export profile_id must be a positive integer")
    raw_formats = raw.get("formats", list(DEFAULT_M3U_EXPORT_FORMATS))
    if not isinstance(raw_formats, list) or not raw_formats:
        raise ValueError("Autopilot export formats must be a non-empty list")
    formats: list[str] = []
    for value in raw_formats:
        if not isinstance(value, str) or value not in SUPPORTED_M3U_EXPORT_FORMATS:
            raise ValueError(f"Unsupported autopilot export format: {value!r}")
        if value not in formats:
            formats.append(value)
    path_format = raw.get("path_format", "absolute")
    if path_format not in SUPPORTED_M3U_EXPORT_PATH_FORMATS:
        raise ValueError(f"Unsupported autopilot export path format: {path_format!r}")
    scope = raw.get("scope", "leaf_only")
    if scope not in SUPPORTED_EXPORT_SCOPES:
        raise ValueError(f"Unsupported autopilot export scope: {scope!r}")
    return RecipeExportConfig(
        enabled=True,
        profile_id=profile_id,
        formats=tuple(formats),
        path_format=path_format,
        scope=scope,
    )


def validate_recipe_export_config(
    *,
    engine: Engine,
    raw: dict[str, Any] | None,
) -> dict[str, Any] | None:
    config = normalize_recipe_export_config(raw)
    if config is None:
        return None if raw is None else {"enabled": False}
    profile = M3uExportProfileStore(engine=engine).get_profile(config.profile_id)
    if profile is None:
        raise ValueError(f"M3U export profile not found: {config.profile_id}")
    return {
        "enabled": True,
        "profile_id": config.profile_id,
        "formats": list(config.formats),
        "path_format": config.path_format,
        "scope": config.scope,
    }


def refresh_recipe_exports(
    *,
    engine: Engine,
    export_config: dict[str, Any] | None,
    recipe_id: int,
    run_id: int,
    root: Path | str | None = None,
    lease_checkpoint: Callable[[], None] | None = None,
) -> RecipeExportResult | None:
    config = normalize_recipe_export_config(export_config)
    if config is None:
        return None
    profile = M3uExportProfileStore(engine=engine).get_profile(config.profile_id)
    if profile is None:
        raise ValueError(f"M3U export profile not found: {config.profile_id}")

    generated_playlist_ids = _generated_playlist_ids(
        engine=engine,
        run_id=run_id,
        scope=config.scope,
    )
    package = build_m3u_export_package(
        engine=engine,
        formats=config.formats,
        generated_playlist_ids=generated_playlist_ids,
        generated_run_ids=[],
        library_path=profile.library_path,
        path_format=config.path_format,
        playlist_ids=[],
    )

    checkpoint = lease_checkpoint or (lambda: None)
    checkpoint()
    export_root = Path(
        root
        if root is not None
        else os.environ.get("AUTOPILOT_EXPORT_ROOT", DEFAULT_AUTOPILOT_EXPORT_ROOT)
    ).expanduser()
    export_root.mkdir(parents=True, exist_ok=True)
    export_root = export_root.resolve()
    target = _safe_recipe_directory(export_root, recipe_id)
    version_directory = Path(
        tempfile.mkdtemp(prefix=f".recipe-{recipe_id}-", dir=export_root)
    )
    file_count = 0
    try:
        for playlist in package.playlists:
            for export_format in config.formats:
                filename = (
                    playlist.filename_m3u
                    if export_format == "m3u"
                    else playlist.filename_m3u8
                )
                output = _safe_child(version_directory, filename)
                output.write_text(playlist.rendered.content, encoding="utf-8")
                file_count += 1
        _atomic_directory_link_swap(
            root=export_root,
            target=target,
            version_directory=version_directory,
            lease_checkpoint=checkpoint,
        )
    except Exception:
        shutil.rmtree(version_directory, ignore_errors=True)
        raise
    checkpoint()

    return RecipeExportResult(
        recipe_id=recipe_id,
        run_id=run_id,
        directory=target,
        playlist_count=len(package.playlists),
        file_count=file_count,
        exported_track_count=package.total_exported_track_count,
        skipped_track_count=package.total_skipped_track_count,
    )


def _generated_playlist_ids(*, engine: Engine, run_id: int, scope: str) -> list[int]:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(
                    generated_playlists_table.c.id,
                    generated_playlists_table.c.parent_playlist_id,
                )
                .where(generated_playlists_table.c.run_id == run_id)
                .order_by(
                    generated_playlists_table.c.depth.asc(),
                    generated_playlists_table.c.position.asc(),
                    generated_playlists_table.c.id.asc(),
                )
            )
            .mappings()
            .all()
        )
    if scope == "all":
        return [int(row["id"]) for row in rows]
    parent_ids = {
        int(row["parent_playlist_id"])
        for row in rows
        if row["parent_playlist_id"] is not None
    }
    return [int(row["id"]) for row in rows if int(row["id"]) not in parent_ids]


def _safe_recipe_directory(root: Path, recipe_id: int) -> Path:
    if recipe_id <= 0:
        raise ValueError("Recipe id must be positive")
    return _safe_child(root, f"recipe-{recipe_id}")


def _safe_child(root: Path, name: str) -> Path:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(f"Unsafe export path component: {name!r}")
    candidate = root / name
    candidate.parent.resolve().relative_to(root.resolve())
    return candidate


def _atomic_directory_link_swap(
    *,
    root: Path,
    target: Path,
    version_directory: Path,
    lease_checkpoint: Callable[[], None],
) -> None:
    lease_checkpoint()
    previous_version: Path | None = None
    if target.is_symlink():
        try:
            previous_version = target.resolve(strict=True)
            previous_version.relative_to(root)
        except (OSError, ValueError):
            previous_version = None
    elif target.exists():
        legacy = _safe_child(root, f".recipe-legacy-{uuid.uuid4().hex}")
        os.replace(target, legacy)
        previous_version = legacy

    temporary_link = _safe_child(root, f".recipe-link-{uuid.uuid4().hex}")
    os.symlink(version_directory.name, temporary_link, target_is_directory=True)
    try:
        lease_checkpoint()
        os.replace(temporary_link, target)
    except Exception:
        temporary_link.unlink(missing_ok=True)
        raise

    if (
        previous_version is not None
        and previous_version != version_directory
        and previous_version.exists()
    ):
        shutil.rmtree(previous_version, ignore_errors=True)
