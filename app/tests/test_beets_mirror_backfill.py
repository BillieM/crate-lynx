import logging
from pathlib import Path
import sqlite3
from typing import Any

from beets.library import Album, Item
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

from app.ingestion import beets_mirror_backfill
from app.ingestion.beets_mirror import (
    beets_album_attributes_table,
    beets_albums_table,
    beets_item_attributes_table,
    beets_items_table,
    metadata as beets_mirror_metadata,
)
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata


def test_beets_mirror_backfill_command_defaults_to_dry_run(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    beets_library = tmp_path / "library.db"
    database_path = tmp_path / "app.db"
    engine = _create_app_engine(database_path)
    _create_beets_library(
        beets_library,
        items=[{"id": 1, "path": b"/music/Artist/Track.mp3", "title": "Track"}],
    )
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("BEETS_LIBRARY", str(beets_library))

    with caplog.at_level(
        logging.INFO,
        logger="app.ingestion.beets_mirror_backfill",
    ):
        beets_mirror_backfill.main([])

    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.ingestion.beets_mirror_backfill"
    ] == [
        "DRY-RUN: 1 action(s)",
        "- inserted beets_mirror item beets_id=1",
    ]
    with engine.connect() as connection:
        assert connection.execute(select(beets_items_table)).all() == []


def test_beets_mirror_backfill_dry_run_reports_without_writing(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_app_engine(tmp_path / "app.db")
    _create_beets_library(
        beets_library,
        items=[
            {"id": 1, "path": b"/music/Artist/Track.mp3", "title": "New"},
            {"id": 2, "path": b"/music/Artist/Existing.mp3", "title": "Updated"},
        ],
        albums=[{"id": 7, "album": "Updated Album"}],
    )
    with engine.begin() as connection:
        connection.execute(
            beets_items_table.insert().values(
                beets_id=2,
                path="/music/Artist/Existing.mp3",
                title="Old",
            )
        )
        connection.execute(
            beets_albums_table.insert().values(
                beets_album_id=7,
                album="Old Album",
            )
        )

        actions = beets_mirror_backfill.backfill_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=False,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "updated beets_mirror item beets_id=2",
        "updated beets_mirror album beets_album_id=7",
    ]
    with engine.connect() as connection:
        items = connection.execute(select(beets_items_table)).mappings().all()
        album = connection.execute(select(beets_albums_table)).mappings().one()

    assert [(row["beets_id"], row["title"]) for row in items] == [(2, "Old")]
    assert album["album"] == "Old Album"


def test_beets_mirror_backfill_apply_mirrors_beets_tables_only(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_app_engine(tmp_path / "app.db")
    _create_beets_library(
        beets_library,
        items=[
            {
                "id": 1,
                "path": b"/music/Artist/Track.mp3",
                "album_id": 7,
                "title": "Track",
                "artist": "Artist",
            }
        ],
        albums=[{"id": 7, "album": "Album", "albumartist": "Artist"}],
        item_attributes=[(1, "mood", "bright")],
        album_attributes=[(7, "source", "bandcamp")],
    )

    with engine.begin() as connection:
        actions = beets_mirror_backfill.backfill_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=True,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "inserted beets_mirror album beets_album_id=7",
    ]
    with engine.connect() as connection:
        item = connection.execute(select(beets_items_table)).mappings().one()
        album = connection.execute(select(beets_albums_table)).mappings().one()
        item_attributes = (
            connection.execute(select(beets_item_attributes_table)).mappings().all()
        )
        album_attributes = (
            connection.execute(select(beets_album_attributes_table)).mappings().all()
        )
        local_tracks = connection.execute(select(local_tracks_table)).all()

    assert item["beets_id"] == 1
    assert item["path"] == "/music/Artist/Track.mp3"
    assert item["album_id"] == 7
    assert item["title"] == "Track"
    assert item["artist"] == "Artist"
    assert album["beets_album_id"] == 7
    assert album["album"] == "Album"
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in item_attributes
    ] == [(1, "mood", "bright")]
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in album_attributes
    ] == [(7, "source", "bandcamp")]
    assert local_tracks == []


def test_beets_mirror_backfill_updates_partial_mirror_idempotently(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_app_engine(tmp_path / "app.db")
    _create_beets_library(
        beets_library,
        items=[{"id": 1, "path": b"/music/Artist/Track.mp3", "title": "Updated"}],
        albums=[{"id": 7, "album": "Updated Album"}],
        item_attributes=[(1, "mood", "new")],
        album_attributes=[(7, "source", "new")],
    )
    with engine.begin() as connection:
        connection.execute(
            beets_items_table.insert().values(
                beets_id=1,
                path="/music/Artist/Old.mp3",
                title="Old",
            )
        )
        connection.execute(
            beets_albums_table.insert().values(
                beets_album_id=7,
                album="Old Album",
            )
        )
        connection.execute(
            beets_item_attributes_table.insert().values(
                entity_id=1,
                key="old",
                value="remove",
            )
        )
        connection.execute(
            beets_album_attributes_table.insert().values(
                entity_id=7,
                key="old",
                value="remove",
            )
        )

    for _ in range(2):
        with engine.begin() as connection:
            actions = beets_mirror_backfill.backfill_beets_mirror(
                connection,
                beets_library=beets_library,
                apply=True,
            )

        assert actions == [
            "updated beets_mirror item beets_id=1",
            "updated beets_mirror album beets_album_id=7",
        ]

    with engine.connect() as connection:
        item = connection.execute(select(beets_items_table)).mappings().one()
        album = connection.execute(select(beets_albums_table)).mappings().one()
        item_attributes = (
            connection.execute(select(beets_item_attributes_table)).mappings().all()
        )
        album_attributes = (
            connection.execute(select(beets_album_attributes_table)).mappings().all()
        )

    assert item["title"] == "Updated"
    assert album["album"] == "Updated Album"
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in item_attributes
    ] == [(1, "mood", "new")]
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in album_attributes
    ] == [(7, "source", "new")]


def test_beets_mirror_backfill_reports_stale_rows(
    tmp_path: Path,
) -> None:
    beets_library = tmp_path / "library.db"
    engine = _create_app_engine(tmp_path / "app.db")
    _create_beets_library(
        beets_library,
        items=[{"id": 1, "path": b"/music/Artist/Track.mp3", "title": "Current"}],
        albums=[{"id": 7, "album": "Current Album"}],
    )
    with engine.begin() as connection:
        connection.execute(
            beets_items_table.insert().values(
                beets_id=99,
                path="/music/Missing.mp3",
                title="Missing",
            )
        )
        connection.execute(
            beets_albums_table.insert().values(
                beets_album_id=88,
                album="Missing Album",
            )
        )
        connection.execute(
            local_tracks_table.insert().values(
                file_path="Stale.mp3",
                library_root_rel_path="Stale.mp3",
                fingerprint="fp",
                beets_id=77,
            )
        )

        actions = beets_mirror_backfill.backfill_beets_mirror(
            connection,
            beets_library=beets_library,
            apply=False,
        )

    assert actions == [
        "inserted beets_mirror item beets_id=1",
        "inserted beets_mirror album beets_album_id=7",
        "stale_mirror_items beets_id=99 missing from Beets",
        "stale_mirror_albums beets_album_id=88 missing from Beets",
        "stale_local_track_beets_ids local_track_id=1 beets_id=77 missing from Beets",
    ]


def _create_app_engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path}")
    local_tracks_metadata.create_all(engine)
    beets_mirror_metadata.create_all(engine)
    return engine


def _create_beets_library(
    path: Path,
    *,
    items: list[dict[str, Any]],
    albums: list[dict[str, Any]] | None = None,
    item_attributes: list[tuple[int, str, str]] | None = None,
    album_attributes: list[tuple[int, str, str]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(_create_beets_table_sql("items", Item._fields))
        connection.execute(_create_beets_table_sql("albums", Album._fields))
        connection.execute(
            """
            CREATE TABLE item_attributes (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE album_attributes (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT
            )
            """
        )
        for item in items:
            _insert_beets_row(connection, "items", item)
        for album in albums or []:
            _insert_beets_row(connection, "albums", album)
        for entity_id, key, value in item_attributes or []:
            _insert_attribute(connection, "item_attributes", entity_id, key, value)
        for entity_id, key, value in album_attributes or []:
            _insert_attribute(connection, "album_attributes", entity_id, key, value)
        connection.commit()


def _create_beets_table_sql(table_name: str, fields: dict[str, Any]) -> str:
    column_defs = []
    for field_name, field_type in fields.items():
        if field_name == "id":
            column_defs.append("id INTEGER PRIMARY KEY")
        else:
            column_defs.append(f"{field_name} {field_type.sql}")
    return f"CREATE TABLE {table_name} ({', '.join(column_defs)})"


def _insert_beets_row(
    connection: sqlite3.Connection,
    table_name: str,
    values: dict[str, Any],
) -> None:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
        list(values.values()),
    )


def _insert_attribute(
    connection: sqlite3.Connection,
    table_name: str,
    entity_id: int,
    key: str,
    value: str,
) -> None:
    connection.execute(
        f"INSERT INTO {table_name} (entity_id, key, value) VALUES (?, ?, ?)",
        (entity_id, key, value),
    )
