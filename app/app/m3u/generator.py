from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.core.paths import default_staging_path, resolve_staging_path
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.streaming.models import (
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)

DEFAULT_M3U_OUTPUT_DIR = default_staging_path("m3u")


def get_m3u_output_dir() -> Path:
    return resolve_staging_path("M3U_OUTPUT_DIR", "m3u")


def generate_m3u(
    playlist_id: int,
    base_path: Path | str,
    *,
    engine: Engine | None = None,
) -> str:
    """Generate M3U contents for a playlist."""
    base_path = Path(base_path).resolve()
    engine = engine or create_database_engine()
    query = (
        select(
            local_tracks_table.c.file_path,
            streaming_tracks_table.c.artist,
            streaming_tracks_table.c.title,
            streaming_tracks_table.c.duration_ms,
        )
        .select_from(
            playlist_membership_table.join(
                final_links_table,
                final_links_table.c.streaming_track_id
                == playlist_membership_table.c.streaming_track_id,
            )
            .join(
                streaming_tracks_table,
                streaming_tracks_table.c.id
                == playlist_membership_table.c.streaming_track_id,
            )
            .join(
                local_tracks_table,
                local_tracks_table.c.id == final_links_table.c.local_track_id,
            )
        )
        .where(playlist_membership_table.c.playlist_id == playlist_id)
        .order_by(playlist_membership_table.c.position.asc())
    )

    with engine.connect() as connection:
        rows = connection.execute(query).mappings().all()

    lines = ["#EXTM3U"]
    for row in rows:
        duration_seconds = _format_duration_seconds(row["duration_ms"])
        resolved_path = str((base_path / Path(row["file_path"])).resolve())
        lines.append(f"#EXTINF:{duration_seconds},{row['artist']} - {row['title']}")
        lines.append(resolved_path)

    return "\n".join(lines)


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
