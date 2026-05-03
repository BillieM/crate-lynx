from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, select

from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.streaming.models import playlist_membership_table, streaming_tracks_table


def generate_m3u(playlist_id: int, base_path: Path | str) -> str:
    """Generate M3U contents for a playlist."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for M3U generation")

    base_path = Path(base_path).resolve()
    engine = create_engine(database_url)
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


def _format_duration_seconds(duration_ms: int | None) -> int:
    if duration_ms is None:
        return -1

    return duration_ms // 1000
