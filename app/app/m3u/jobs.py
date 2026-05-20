from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import logging
import os
from pathlib import Path

from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.core.db import create_database_engine
from app.m3u.generator import get_m3u_output_dir, write_m3u
from app.relationships.resolver import StreamingRelationshipResolver
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    playlist_membership_table,
    streaming_playlists_table,
)


logger = logging.getLogger(__name__)

DEFAULT_M3U_QUEUE_NAME = "m3u"
DEFAULT_M3U_JOB_TIMEOUT = "10m"


@dataclass(slots=True)
class M3uRegenerationJobEnqueuer:
    redis_url: str
    queue_name: str = DEFAULT_M3U_QUEUE_NAME
    job_timeout: str = DEFAULT_M3U_JOB_TIMEOUT

    def enqueue_playlists(self, playlist_ids: Iterable[int]) -> list[str]:
        resolved_playlist_ids = _normalize_ids(playlist_ids)
        if not resolved_playlist_ids:
            return []

        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        return [
            queue.enqueue(
                "app.m3u.jobs.run_m3u_regeneration_job",
                playlist_id,
                job_timeout=self.job_timeout,
            ).id
            for playlist_id in resolved_playlist_ids
        ]


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
    resolved_track_ids = _normalize_ids(streaming_track_ids)
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


def run_m3u_regeneration_job(playlist_id: int) -> str | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for M3U regeneration")

    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            playlist = (
                connection.execute(
                    select(
                        streaming_playlists_table.c.id,
                        streaming_playlists_table.c.title,
                        streaming_playlists_table.c.sync_mode,
                    ).where(streaming_playlists_table.c.id == playlist_id)
                )
                .mappings()
                .one_or_none()
            )

        if playlist is None:
            logger.warning(
                "Skipping M3U regeneration for missing playlist_id=%s", playlist_id
            )
            return None

        if playlist["sync_mode"] != PLAYLIST_SYNC_MODE_FULL:
            logger.info(
                "Skipping M3U regeneration for non-full playlist_id=%s",
                playlist_id,
            )
            return None

        output_path = write_m3u(
            playlist_id,
            playlist["title"],
            base_path=Path(os.environ.get("LIBRARY_ROOT", "/nas/media/music")),
            output_dir=get_m3u_output_dir(),
            engine=engine,
        )
        return str(output_path)
    finally:
        engine.dispose()


def _normalize_ids(ids: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({int(identifier) for identifier in ids}))
