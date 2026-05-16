from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.sql.elements import ColumnElement

from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)

ACTIVE_MATCHING_PLAYLIST_SYNC_MODES = (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
)


def active_playlist_streaming_track_filter() -> ColumnElement[bool]:
    return (
        select(playlist_membership_table.c.id)
        .select_from(
            playlist_membership_table.join(
                streaming_playlists_table,
                streaming_playlists_table.c.id
                == playlist_membership_table.c.playlist_id,
            )
        )
        .where(
            playlist_membership_table.c.streaming_track_id
            == streaming_tracks_table.c.id,
            streaming_playlists_table.c.sync_mode.in_(
                ACTIVE_MATCHING_PLAYLIST_SYNC_MODES
            ),
        )
        .exists()
    )
