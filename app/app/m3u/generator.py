from __future__ import annotations

from dataclasses import dataclass
import ntpath
import posixpath
import re
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.core.paths import default_staging_path, resolve_staging_path
from app.local_tracks.store import local_tracks_table
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)

DEFAULT_M3U_OUTPUT_DIR = default_staging_path("m3u")
M3uExportPathFormat = Literal["absolute", "file_url"]
M3U_EXPORT_PATH_FORMAT_ABSOLUTE: M3uExportPathFormat = "absolute"
M3U_EXPORT_PATH_FORMAT_FILE_URL: M3uExportPathFormat = "file_url"
DEFAULT_M3U_EXPORT_PATH_FORMAT: M3uExportPathFormat = M3U_EXPORT_PATH_FORMAT_ABSOLUTE
SUPPORTED_M3U_EXPORT_PATH_FORMATS = frozenset(
    (M3U_EXPORT_PATH_FORMAT_ABSOLUTE, M3U_EXPORT_PATH_FORMAT_FILE_URL)
)


class InvalidM3uExportPathFormatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class M3uPlaylistExport:
    content: str
    exported_track_count: int
    skipped_track_count: int
    sample_path: str | None


def get_m3u_output_dir() -> Path:
    return resolve_staging_path("M3U_OUTPUT_DIR", "m3u")


def generate_m3u(
    playlist_id: int,
    base_path: Path | str,
    *,
    engine: Engine | None = None,
) -> str:
    """Generate M3U contents for a playlist."""
    return build_m3u_playlist_export(
        playlist_id,
        base_path,
        engine=engine,
    ).content


def build_m3u_playlist_export(
    playlist_id: int,
    base_path: Path | str,
    *,
    include_extinf: bool = True,
    path_format: str = DEFAULT_M3U_EXPORT_PATH_FORMAT,
    engine: Engine | None = None,
) -> M3uPlaylistExport:
    """Generate M3U contents and preview counts for a playlist."""
    base_path = str(base_path)
    export_path_format = normalize_m3u_export_path_format(path_format)
    engine = engine or create_database_engine()
    query = (
        select(
            streaming_tracks_table.c.id.label("streaming_track_id"),
            streaming_tracks_table.c.artist,
            streaming_tracks_table.c.title,
            streaming_tracks_table.c.duration_ms,
        )
        .select_from(
            playlist_membership_table.join(
                streaming_tracks_table,
                streaming_tracks_table.c.id
                == playlist_membership_table.c.streaming_track_id,
            )
        )
        .where(playlist_membership_table.c.playlist_id == playlist_id)
        .order_by(playlist_membership_table.c.position.asc())
    )

    with engine.connect() as connection:
        from app.relationships.resolver import StreamingRelationshipResolver

        resolver = StreamingRelationshipResolver(connection)
        rows = connection.execute(query).mappings().all()
        resolved_links_by_track_id = {}
        for row in rows:
            streaming_track_id = int(row["streaming_track_id"])
            resolved_link = resolver.resolve(streaming_track_id)
            if resolved_link is not None:
                resolved_links_by_track_id[streaming_track_id] = resolved_link

        local_track_ids = {
            resolved_link.local_track_id
            for resolved_link in resolved_links_by_track_id.values()
        }
        local_paths_by_id = {}
        if local_track_ids:
            local_paths_by_id = {
                int(row["id"]): row["library_root_rel_path"]
                for row in connection.execute(
                    select(
                        local_tracks_table.c.id,
                        local_tracks_table.c.library_root_rel_path,
                    ).where(local_tracks_table.c.id.in_(local_track_ids))
                ).mappings()
            }

    lines = ["#EXTM3U"]
    exported_track_count = 0
    skipped_track_count = 0
    sample_path = None
    for row in rows:
        resolved_link = resolved_links_by_track_id.get(int(row["streaming_track_id"]))
        if resolved_link is None:
            skipped_track_count += 1
            continue

        local_path = local_paths_by_id.get(resolved_link.local_track_id)
        if local_path is None:
            skipped_track_count += 1
            continue

        duration_seconds = _format_duration_seconds(row["duration_ms"])
        resolved_path = format_export_audio_path(base_path, local_path)
        rendered_path = format_m3u_entry_path(resolved_path, export_path_format)
        sample_path = sample_path or rendered_path
        exported_track_count += 1
        if include_extinf:
            lines.append(f"#EXTINF:{duration_seconds},{row['artist']} - {row['title']}")
        lines.append(rendered_path)

    return M3uPlaylistExport(
        content="\n".join(lines),
        exported_track_count=exported_track_count,
        skipped_track_count=skipped_track_count,
        sample_path=sample_path,
    )


def build_m3u_filename(title: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-")
    if not sanitized:
        sanitized = "playlist"
    return f"{sanitized}.m3u"


def write_m3u(
    playlist_id: int,
    playlist_title: str,
    base_path: Path | str,
    output_dir: Path | str | None = None,
    *,
    engine: Engine | None = None,
) -> Path:
    resolved_output_dir = Path(output_dir or get_m3u_output_dir()).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = resolved_output_dir / build_m3u_filename(playlist_title)
    output_path.write_text(
        generate_m3u(playlist_id, base_path, engine=engine),
        encoding="utf-8",
    )
    return output_path


def regenerate_m3us_for_streaming_track(
    streaming_track_id: int,
    *,
    engine: Engine | None = None,
    base_path: Path | str,
    output_dir: Path | str | None = None,
) -> list[Path]:
    engine = engine or create_database_engine()
    query = (
        select(
            streaming_playlists_table.c.id,
            streaming_playlists_table.c.title,
        )
        .select_from(
            streaming_playlists_table.join(
                playlist_membership_table,
                playlist_membership_table.c.playlist_id
                == streaming_playlists_table.c.id,
            )
        )
        .where(playlist_membership_table.c.streaming_track_id == streaming_track_id)
        .where(streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL)
        .distinct()
        .order_by(streaming_playlists_table.c.id.asc())
    )

    with engine.connect() as connection:
        playlists = connection.execute(query).mappings().all()

    return [
        write_m3u(
            playlist["id"],
            playlist["title"],
            base_path=base_path,
            output_dir=output_dir,
            engine=engine,
        )
        for playlist in playlists
    ]


def _format_duration_seconds(duration_ms: int | None) -> int:
    if duration_ms is None:
        return -1

    return duration_ms // 1000


def format_export_audio_path(base_path: Path | str, relative_path: str) -> str:
    base_path_value = str(base_path)
    relative_parts = _relative_path_parts(relative_path)
    if _is_windows_absolute_path(base_path_value):
        return ntpath.normpath(ntpath.join(base_path_value, *relative_parts))

    return posixpath.normpath(posixpath.join(base_path_value, *relative_parts))


def format_m3u_entry_path(audio_path: str, path_format: str) -> str:
    export_path_format = normalize_m3u_export_path_format(path_format)
    if export_path_format == M3U_EXPORT_PATH_FORMAT_FILE_URL:
        return format_file_url(audio_path)

    return audio_path


def format_file_url(path: str) -> str:
    if path.startswith("\\\\"):
        normalized_unc_path = path.replace("\\", "/").lstrip("/")
        host, _, share_path = normalized_unc_path.partition("/")
        return f"file://{quote(host, safe='')}/{quote(share_path, safe='/-._~')}"

    if _is_windows_absolute_path(path):
        normalized_windows_path = path.replace("\\", "/")
        return f"file:///{quote(normalized_windows_path, safe='/:._~-')}"

    return f"file://localhost{quote(path, safe='/-._~')}"


def normalize_m3u_export_path_format(path_format: str) -> M3uExportPathFormat:
    if path_format not in SUPPORTED_M3U_EXPORT_PATH_FORMATS:
        raise InvalidM3uExportPathFormatError(
            f"Unsupported M3U export path format: {path_format}"
        )

    return cast(M3uExportPathFormat, path_format)


def _relative_path_parts(relative_path: str) -> tuple[str, ...]:
    normalized = relative_path.replace("\\", "/")
    return tuple(part for part in normalized.split("/") if part not in ("", ".", "/"))


def _is_windows_absolute_path(path: str) -> bool:
    drive, tail = ntpath.splitdrive(path)
    return bool(drive and tail.startswith(("\\", "/"))) or path.startswith("\\\\")
