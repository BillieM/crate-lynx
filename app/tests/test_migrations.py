from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from beets.library import Album, Item
from sqlalchemy import create_engine, insert, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.schema import build_app_metadata
from app.streaming.models import (
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_app_metadata_matches_migrated_schema(
    migrated_database: tuple[str, Engine],
) -> None:
    _, engine = migrated_database

    with engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        diff = compare_metadata(migration_context, build_app_metadata())

    assert diff == []


def test_beets_mirror_migration_matches_beets_field_set(
    migrated_database: tuple[str, Engine],
) -> None:
    _, engine = migrated_database

    inspector = inspect(engine)

    item_columns = {column["name"] for column in inspector.get_columns("beets_items")}
    album_columns = {column["name"] for column in inspector.get_columns("beets_albums")}

    assert item_columns == _beets_column_names(Item._fields, id_column_name="beets_id")
    assert album_columns == _beets_column_names(
        Album._fields,
        id_column_name="beets_album_id",
    )


def _beets_column_names(fields: dict[str, object], *, id_column_name: str) -> set[str]:
    return {
        id_column_name if field_name == "id" else field_name for field_name in fields
    }


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "db" / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "db"))
    return config


def test_selected_for_sync_migration_backfills_playlists_with_memberships(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = _alembic_config()
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


def test_schema_integrity_migration_deduplicates_provider_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'schema-integrity.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = _alembic_config()
    command.upgrade(alembic_config, "b9c2f4a8e7d1")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO streaming_accounts
                    (id, provider, display_name, auth_token_blob, auth_state)
                VALUES
                    (1, 'youtube_music', 'Listener', 'encrypted-token', 'connected')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO streaming_playlists
                    (id, account_id, provider_playlist_id, title, selected_for_sync)
                VALUES
                    (10, 1, 'PL1', 'Kept playlist', FALSE),
                    (11, 1, 'PL1', 'Duplicate playlist', FALSE)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO streaming_tracks
                    (id, provider_track_id, title, artist)
                VALUES
                    (20, 'track-1', 'Kept track', 'Artist'),
                    (21, 'track-1', 'Duplicate track', 'Artist')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO playlist_membership
                    (playlist_id, streaming_track_id, position)
                VALUES
                    (11, 21, 1)
                """
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        playlists = list(
            connection.execute(
                text("SELECT id FROM streaming_playlists ORDER BY id")
            ).scalars()
        )
        tracks = list(
            connection.execute(
                text("SELECT id FROM streaming_tracks ORDER BY id")
            ).scalars()
        )
        membership = (
            connection.execute(
                text(
                    """
                    SELECT playlist_id, streaming_track_id
                    FROM playlist_membership
                    """
                )
            )
            .mappings()
            .one()
        )

    with engine.begin() as connection:
        try:
            connection.execute(
                text(
                    """
                    INSERT INTO streaming_tracks
                        (provider_track_id, title, artist)
                    VALUES
                        ('track-1', 'Duplicate rejected', 'Artist')
                    """
                )
            )
        except IntegrityError:
            pass
        else:
            raise AssertionError("duplicate provider_track_id was accepted")

    assert playlists == [10]
    assert tracks == [20]
    assert dict(membership) == {
        "playlist_id": 10,
        "streaming_track_id": 20,
    }


def test_local_track_beets_id_migration_deduplicates_and_enforces_unique(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'local-track-beets-id.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = _alembic_config()
    command.upgrade(alembic_config, "c6d5f8a1b2c3")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO local_tracks
                    (id, file_path, library_root_rel_path, fingerprint, beets_id)
                VALUES
                    (1, 'kept.mp3', 'kept.mp3', 'old-fp', 42),
                    (2, 'duplicate.mp3', 'duplicate.mp3', 'duplicate-fp', 42),
                    (3, 'legacy-one.mp3', 'legacy-one.mp3', NULL, NULL),
                    (4, 'legacy-two.mp3', 'legacy-two.mp3', NULL, NULL)
                """
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                    SELECT id, file_path, beets_id
                    FROM local_tracks
                    ORDER BY id
                    """
                )
            )
            .mappings()
            .all()
        )

    with engine.begin() as connection:
        try:
            connection.execute(
                text(
                    """
                    INSERT INTO local_tracks
                        (file_path, library_root_rel_path, fingerprint, beets_id)
                    VALUES
                        ('rejected.mp3', 'rejected.mp3', NULL, 42)
                    """
                )
            )
        except IntegrityError:
            pass
        else:
            raise AssertionError("duplicate beets_id was accepted")

        connection.execute(
            text(
                """
                INSERT INTO local_tracks
                    (file_path, library_root_rel_path, fingerprint, beets_id)
                VALUES
                    ('legacy-three.mp3', 'legacy-three.mp3', NULL, NULL)
                """
            )
        )

    assert [dict(row) for row in rows] == [
        {"id": 1, "file_path": "kept.mp3", "beets_id": 42},
        {"id": 3, "file_path": "legacy-one.mp3", "beets_id": None},
        {"id": 4, "file_path": "legacy-two.mp3", "beets_id": None},
    ]


def test_remove_streaming_fingerprints_migration_normalizes_acoustic_suggestions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'remove-fingerprints.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = _alembic_config()
    command.upgrade(alembic_config, "f8a3d2c1b0e4")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO local_tracks
                    (id, file_path, library_root_rel_path, fingerprint, beets_id)
                VALUES
                    (1, 'one.mp3', 'one.mp3', 'local-fp', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO streaming_tracks
                    (
                        id, provider_track_id, title, artist, fingerprint,
                        fingerprint_duration_seconds, fingerprinted_at
                    )
                VALUES
                    (1, 'track-1', 'Track 1', 'Artist 1', 'stream-fp', 200.5, '2026-05-04 12:00:00'),
                    (2, 'track-2', 'Track 2', 'Artist 2', NULL, NULL, NULL),
                    (3, 'track-3', 'Track 3', 'Artist 3', NULL, NULL, NULL)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO suggested_links
                    (local_track_id, streaming_track_id, match_method, score, status)
                VALUES
                    (1, 1, 'acoustic', 0.9, 'pending'),
                    (1, 2, 'acoustic', 0.9, 'approved'),
                    (1, 3, 'acoustic', 0.9, 'rejected')
                """
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        streaming_columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info(streaming_tracks)"))
            .mappings()
            .all()
        }
        suggestions = (
            connection.execute(
                text(
                    """
                    SELECT streaming_track_id, match_method, status
                    FROM suggested_links
                    ORDER BY streaming_track_id
                    """
                )
            )
            .mappings()
            .all()
        )

    assert "fingerprint" not in streaming_columns
    assert "fingerprint_duration_seconds" not in streaming_columns
    assert "fingerprinted_at" not in streaming_columns
    assert [dict(row) for row in suggestions] == [
        {"streaming_track_id": 2, "match_method": "manual", "status": "approved"},
        {"streaming_track_id": 3, "match_method": "manual", "status": "rejected"},
    ]


def test_ingest_folders_migration_seeds_default_unique_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'ingest_folders.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = _alembic_config()
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


def test_failed_ingestion_cleanup_migration_removes_non_audio_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'failed-ingestion-cleanup.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = _alembic_config()
    command.upgrade(alembic_config, "e17a4c9b2d01")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO failed_ingestion_attempts
                    (source_path, filename, fingerprint, failure_reason)
                VALUES
                    ('/ingestion/.DS_Store', '.DS_Store', NULL, 'Unsupported audio format'),
                    ('/soulseek/2f940acf775f48998bf67a0866d66d56',
                     '2f940acf775f48998bf67a0866d66d56', NULL, 'Unsupported audio format'),
                    ('/ingestion/cover.jpg', 'cover.jpg', NULL, 'Unsupported audio format'),
                    ('/ingestion/track.mp3', 'track.mp3', NULL, 'Beets import failed'),
                    ('/ingestion/album.FLAC', 'album.FLAC', NULL, 'Beets import failed')
                """
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        filenames = [
            row["filename"]
            for row in connection.execute(
                text(
                    """
                    SELECT filename
                    FROM failed_ingestion_attempts
                    ORDER BY id
                    """
                )
            ).mappings()
        ]

    assert filenames == ["track.mp3", "album.FLAC"]
