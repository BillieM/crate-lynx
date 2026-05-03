from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, select

from app.streaming.models import (
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


def test_selected_for_sync_migration_backfills_playlists_with_memberships(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = Config("db/alembic.ini")
    command.upgrade(alembic_config, "7a90b6dfc1e2")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Listener",
                auth_token_blob="encrypted-token",
                auth_state="connected",
            )
        ).inserted_primary_key[0]
        playlist_with_membership_id = connection.execute(
            insert(streaming_playlists_table).values(
                account_id=account_id,
                provider_playlist_id="PL1",
                title="Synced Mix",
            )
        ).inserted_primary_key[0]
        playlist_without_membership_id = connection.execute(
            insert(streaming_playlists_table).values(
                account_id=account_id,
                provider_playlist_id="PL2",
                title="Discovered Mix",
            )
        ).inserted_primary_key[0]
        track_id = connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="track-1",
                title="Track 1",
                artist="Artist 1",
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=playlist_with_membership_id,
                streaming_track_id=track_id,
                position=1,
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        rows = {
            row["id"]: row["selected_for_sync"]
            for row in connection.execute(
                select(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.selected_for_sync,
                )
            ).mappings()
        }

    assert rows == {
        playlist_with_membership_id: True,
        playlist_without_membership_id: False,
    }
