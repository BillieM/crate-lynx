from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Any

from beets.library import Album, Item
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine

from app.ingestion.beets_mirror import (
    beets_album_attributes_table,
    beets_albums_table,
    beets_item_attributes_table,
    beets_items_table,
    metadata as beets_mirror_metadata,
)
from app.ingestion.beets_mirror_sync import (
    BeetsMirrorAlbumRow,
    BeetsMirrorRow,
    decode_beets_path,
    iter_all_albums,
    iter_all_items,
    read_album,
    read_item,
    upsert_album,
    upsert_item,
)


def test_beets_mirror_sync_round_trips_items_albums_and_attributes(
    tmp_path: Path,
) -> None:
    sqlite_path = tmp_path / "library.db"
    app_engine = _create_app_engine(tmp_path)
    timestamp = 1_714_564_800.0

    with sqlite3.connect(sqlite_path) as sqlite_conn:
        _create_beets_sqlite_schema(sqlite_conn)
        _insert_beets_item(
            sqlite_conn,
            id=1,
            path=b"/music/Artist/Track.mp3",
            album_id=7,
            title="Track",
            artist="Artist",
            album="Album",
            track=3,
            comp=0,
            length=181.5,
            mtime=timestamp,
        )
        _insert_beets_album(
            sqlite_conn,
            id=7,
            artpath=b"/music/Artist/cover.jpg",
            album="Album",
            albumartist="Artist",
            comp=1,
            added=timestamp,
        )
        _insert_attribute(sqlite_conn, "item_attributes", 1, "mood", "bright")
        _insert_attribute(sqlite_conn, "album_attributes", 7, "source", "bandcamp")

        item_row = read_item(sqlite_conn, 1)
        album_row = read_album(sqlite_conn, 7)

    assert item_row == BeetsMirrorRow(
        beets_id=1,
        album_id=7,
        fixed_fields={
            **_empty_fixed_fields(Item._fields),
            "path": "/music/Artist/Track.mp3",
            "album_id": 7,
            "title": "Track",
            "artist": "Artist",
            "album": "Album",
            "track": 3,
            "comp": False,
            "length": 181.5,
            "mtime": datetime.fromtimestamp(timestamp, UTC),
        },
        flex_attributes={"mood": "bright"},
    )
    assert album_row == BeetsMirrorAlbumRow(
        beets_album_id=7,
        fixed_fields={
            **_empty_fixed_fields(Album._fields),
            "artpath": "/music/Artist/cover.jpg",
            "album": "Album",
            "albumartist": "Artist",
            "comp": True,
            "added": datetime.fromtimestamp(timestamp, UTC),
        },
        flex_attributes={"source": "bandcamp"},
    )

    assert item_row is not None
    assert album_row is not None
    with app_engine.begin() as pg_conn:
        assert upsert_item(pg_conn, item_row) == "inserted"
        assert upsert_album(pg_conn, album_row) == "inserted"

    with app_engine.connect() as connection:
        mirrored_item = connection.execute(select(beets_items_table)).mappings().one()
        mirrored_album = connection.execute(select(beets_albums_table)).mappings().one()
        item_attributes = (
            connection.execute(select(beets_item_attributes_table)).mappings().all()
        )
        album_attributes = (
            connection.execute(select(beets_album_attributes_table)).mappings().all()
        )

    assert mirrored_item["beets_id"] == 1
    assert mirrored_item["path"] == "/music/Artist/Track.mp3"
    assert mirrored_item["album_id"] == 7
    assert mirrored_item["title"] == "Track"
    assert mirrored_item["comp"] is False
    assert mirrored_item["track"] == 3
    assert mirrored_item["length"] == 181.5
    assert _as_utc(mirrored_item["mtime"]) == datetime.fromtimestamp(timestamp, UTC)
    assert mirrored_album["beets_album_id"] == 7
    assert mirrored_album["artpath"] == "/music/Artist/cover.jpg"
    assert mirrored_album["comp"] is True
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in item_attributes
    ] == [(1, "mood", "bright")]
    assert [
        (row["entity_id"], row["key"], row["value"]) for row in album_attributes
    ] == [(7, "source", "bandcamp")]


def test_beets_mirror_sync_replaces_attributes_on_reupsert(tmp_path: Path) -> None:
    app_engine = _create_app_engine(tmp_path)

    first_row = BeetsMirrorRow(
        beets_id=1,
        album_id=None,
        fixed_fields={"title": "First"},
        flex_attributes={"mood": "bright", "old": "remove-me"},
    )
    second_row = BeetsMirrorRow(
        beets_id=1,
        album_id=None,
        fixed_fields={"title": "Second"},
        flex_attributes={"mood": "dark"},
    )
    first_album_row = BeetsMirrorAlbumRow(
        beets_album_id=2,
        fixed_fields={"album": "First Album"},
        flex_attributes={"source": "old"},
    )
    second_album_row = BeetsMirrorAlbumRow(
        beets_album_id=2,
        fixed_fields={"album": "Second Album"},
        flex_attributes={"source": "new", "review": "kept"},
    )

    with app_engine.begin() as connection:
        assert upsert_item(connection, first_row) == "inserted"
        assert upsert_item(connection, second_row) == "updated"
        assert upsert_album(connection, first_album_row) == "inserted"
        assert upsert_album(connection, second_album_row) == "updated"

    with app_engine.connect() as connection:
        item = connection.execute(select(beets_items_table)).mappings().one()
        item_attributes = (
            connection.execute(
                select(beets_item_attributes_table).order_by(
                    beets_item_attributes_table.c.key
                )
            )
            .mappings()
            .all()
        )
        album = connection.execute(select(beets_albums_table)).mappings().one()
        album_attributes = (
            connection.execute(
                select(beets_album_attributes_table).order_by(
                    beets_album_attributes_table.c.key
                )
            )
            .mappings()
            .all()
        )

    assert item["title"] == "Second"
    assert [(row["key"], row["value"]) for row in item_attributes] == [("mood", "dark")]
    assert album["album"] == "Second Album"
    assert [(row["key"], row["value"]) for row in album_attributes] == [
        ("review", "kept"),
        ("source", "new"),
    ]


def test_beets_mirror_sync_handles_missing_rows(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "library.db"

    with sqlite3.connect(sqlite_path) as sqlite_conn:
        _create_beets_sqlite_schema(sqlite_conn)

        assert read_item(sqlite_conn, 404) is None
        assert read_album(sqlite_conn, 404) is None
        assert list(iter_all_items(sqlite_conn)) == []
        assert list(iter_all_albums(sqlite_conn)) == []


def test_beets_mirror_sync_coerces_beets_sqlite_types(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "library.db"
    timestamp = 1_714_568_400.25
    raw_path = b"/music/Artist/invalid-\xff.mp3"

    with sqlite3.connect(sqlite_path) as sqlite_conn:
        _create_beets_sqlite_schema(sqlite_conn)
        _insert_beets_item(
            sqlite_conn,
            id=1,
            path=raw_path,
            album_id=None,
            comp=1,
            track="07",
            mtime=timestamp,
        )

        row = read_item(sqlite_conn, 1)

    assert row is not None
    assert row.fixed_fields["path"] == raw_path.decode(
        "utf-8", errors="surrogateescape"
    )
    assert (
        row.fixed_fields["path"].encode("utf-8", errors="surrogateescape") == raw_path
    )
    assert row.fixed_fields["album_id"] is None
    assert row.fixed_fields["comp"] is True
    assert row.fixed_fields["track"] == 7
    assert row.fixed_fields["mtime"] == datetime.fromtimestamp(timestamp, UTC)


def test_decode_beets_path_round_trips_bytes_and_str_paths() -> None:
    raw_path = b"/music/Artist/invalid-\xff.mp3"
    decoded_path = decode_beets_path(raw_path)

    assert decoded_path.encode("utf-8", errors="surrogateescape") == raw_path
    assert decode_beets_path("/music/Artist/Track.mp3") == "/music/Artist/Track.mp3"


def _create_app_engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    beets_mirror_metadata.create_all(engine)
    return engine


def _create_beets_sqlite_schema(sqlite_conn: sqlite3.Connection) -> None:
    sqlite_conn.execute(_create_table_sql("items", Item._fields))
    sqlite_conn.execute(_create_table_sql("albums", Album._fields))
    sqlite_conn.execute(
        """
        CREATE TABLE item_attributes (
            id INTEGER PRIMARY KEY,
            entity_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT
        )
        """
    )
    sqlite_conn.execute(
        """
        CREATE TABLE album_attributes (
            id INTEGER PRIMARY KEY,
            entity_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT
        )
        """
    )
    sqlite_conn.commit()


def _create_table_sql(table_name: str, fields: dict[str, Any]) -> str:
    column_defs = []
    for field_name, field_type in fields.items():
        if field_name == "id":
            column_defs.append("id INTEGER PRIMARY KEY")
        else:
            column_defs.append(f"{field_name} {field_type.sql}")
    return f"CREATE TABLE {table_name} ({', '.join(column_defs)})"


def _insert_beets_item(sqlite_conn: sqlite3.Connection, **values: Any) -> None:
    _insert_sqlite_row(sqlite_conn, "items", values)


def _insert_beets_album(sqlite_conn: sqlite3.Connection, **values: Any) -> None:
    _insert_sqlite_row(sqlite_conn, "albums", values)


def _insert_sqlite_row(
    sqlite_conn: sqlite3.Connection,
    table_name: str,
    values: dict[str, Any],
) -> None:
    placeholders = ", ".join("?" for _ in values)
    columns = ", ".join(values)
    sqlite_conn.execute(
        f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
        list(values.values()),
    )
    sqlite_conn.commit()


def _insert_attribute(
    sqlite_conn: sqlite3.Connection,
    table_name: str,
    entity_id: int,
    key: str,
    value: str,
) -> None:
    sqlite_conn.execute(
        f"INSERT INTO {table_name} (entity_id, key, value) VALUES (?, ?, ?)",
        (entity_id, key, value),
    )
    sqlite_conn.commit()


def _empty_fixed_fields(fields: dict[str, Any]) -> dict[str, None]:
    return {field_name: None for field_name in fields if field_name != "id"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
