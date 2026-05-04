from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import IntegrityError

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


def test_streaming_track_fingerprint_migration_preserves_existing_tracks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fingerprints.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = Config("db/alembic.ini")
    command.upgrade(alembic_config, "bc4c3e1785d7")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        track_id = connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="track-1",
                title="Track 1",
                artist="Artist 1",
            )
        ).inserted_primary_key[0]

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                    SELECT fingerprint, fingerprint_duration_seconds, fingerprinted_at
                    FROM streaming_tracks
                    WHERE id = :track_id
                    """
                ),
                {"track_id": track_id},
            )
            .mappings()
            .one()
        )

    assert row["fingerprint"] is None
    assert row["fingerprint_duration_seconds"] is None
    assert row["fingerprinted_at"] is None


def test_ingest_folders_migration_seeds_default_unique_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'ingest_folders.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = Config("db/alembic.ini")
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT path, created_at, updated_at
                    FROM ingest_folders
                    ORDER BY id
                    """
                )
            )
            .mappings()
            .all()
        )

    assert [row["path"] for row in rows] == ["/ingestion", "/soulseek"]
    assert all(row["created_at"] is not None for row in rows)
    assert all(row["updated_at"] is not None for row in rows)

    with engine.begin() as connection:
        try:
            connection.execute(
                text("INSERT INTO ingest_folders (path) VALUES (:path)"),
                {"path": "/ingestion"},
            )
        except IntegrityError:
            pass
        else:
            raise AssertionError("duplicate ingest folder path was accepted")
