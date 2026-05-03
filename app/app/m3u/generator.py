from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, select

from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.streaming.models import playlist_membership_table


def generate_m3u(playlist_id: int, base_path: Path | str) -> str:
    """Generate M3U contents for a playlist."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for M3U generation")

    base_path = Path(base_path).resolve()
    engine = create_engine(database_url)
    query = (
        select(local_tracks_table.c.file_path)
        .select_from(
            playlist_membership_table.join(
                final_links_table,
                final_links_table.c.streaming_track_id
                == playlist_membership_table.c.streaming_track_id,
            ).join(
                local_tracks_table,
                local_tracks_table.c.id == final_links_table.c.local_track_id,
            )
        )
        .where(playlist_membership_table.c.playlist_id == playlist_id)
        .order_by(playlist_membership_table.c.position.asc())
    )

    with engine.connect() as connection:
        rows = connection.execute(query).scalars().all()

    resolved_paths = [
        str((base_path / Path(file_path)).resolve()) for file_path in rows
    ]
    return "\n".join(resolved_paths)
