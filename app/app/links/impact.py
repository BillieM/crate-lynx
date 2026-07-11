from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.relationships.resolver import StreamingRelationshipResolver
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    playlist_membership_table,
    streaming_playlists_table,
)


def affected_full_sync_playlist_ids_for_streaming_track(
    connection: Connection,
    streaming_track_id: int,
) -> tuple[int, ...]:
    resolver = StreamingRelationshipResolver(connection)
    return affected_full_sync_playlist_ids_for_streaming_tracks(
        connection,
        resolver.equivalent_group_track_ids(streaming_track_id),
    )


def affected_full_sync_playlist_ids_for_equivalence(
    connection: Connection,
    first_track_id: int,
    second_track_id: int,
) -> tuple[int, ...]:
    resolver = StreamingRelationshipResolver(connection)
    return affected_full_sync_playlist_ids_for_streaming_tracks(
        connection,
        (
            *resolver.equivalent_group_track_ids(first_track_id),
            *resolver.equivalent_group_track_ids(second_track_id),
        ),
    )


def affected_full_sync_playlist_ids_for_streaming_tracks(
    connection: Connection,
    streaming_track_ids: Iterable[int],
) -> tuple[int, ...]:
    resolved_track_ids = tuple(
        sorted({int(identifier) for identifier in streaming_track_ids})
    )
    if not resolved_track_ids:
        return ()

    rows = connection.execute(
        select(streaming_playlists_table.c.id)
        .select_from(
            streaming_playlists_table.join(
                playlist_membership_table,
                playlist_membership_table.c.playlist_id
                == streaming_playlists_table.c.id,
            )
        )
        .where(playlist_membership_table.c.streaming_track_id.in_(resolved_track_ids))
        .where(streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL)
        .distinct()
        .order_by(streaming_playlists_table.c.id.asc())
    ).scalars()
    return tuple(int(playlist_id) for playlist_id in rows)
