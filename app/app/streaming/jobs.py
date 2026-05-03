from __future__ import annotations

import os

from app.streaming.store import StreamingAccountStore


def run_youtube_music_sync_job(
    account_id: int,
) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL must be configured for YouTube Music sync jobs"
        )

    StreamingAccountStore(database_url).sync_youtube_music_account(
        account_id=account_id
    )


def run_youtube_music_playlist_metadata_refresh_job(
    account_id: int,
) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL must be configured for YouTube Music sync jobs"
        )

    StreamingAccountStore(database_url).sync_youtube_music_playlists(
        account_id=account_id
    )
