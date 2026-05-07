from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from beets.dbcore import types as beets_types
from beets.library import Album, DateType, Item, PathType
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects import postgresql, sqlite

from app.ingestion.beets_mirror import (
    beets_album_attributes_table,
    beets_albums_table,
    beets_item_attributes_table,
    beets_items_table,
)


@dataclass(frozen=True)
class BeetsMirrorRow:
    beets_id: int
    album_id: int | None
    fixed_fields: dict[str, Any]
    flex_attributes: dict[str, str]

    def __post_init__(self) -> None:
        _validate_fixed_fields(
            self.fixed_fields,
            allowed_fields=Item._fields,
            entity_name="item",
        )
        _validate_explicit_id(
            self.fixed_fields,
            field_name="id",
            expected_id=self.beets_id,
            entity_name="item",
        )
        if "album_id" in self.fixed_fields:
            fixed_album_id = _coerce_optional_int(self.fixed_fields["album_id"])
            if fixed_album_id != self.album_id:
                raise ValueError("item fixed_fields album_id must match album_id")


@dataclass(frozen=True)
class BeetsMirrorAlbumRow:
    beets_album_id: int
    fixed_fields: dict[str, Any]
    flex_attributes: dict[str, str]

    def __post_init__(self) -> None:
        _validate_fixed_fields(
            self.fixed_fields,
            allowed_fields=Album._fields,
            entity_name="album",
        )
        _validate_explicit_id(
            self.fixed_fields,
            field_name="id",
            expected_id=self.beets_album_id,
            entity_name="album",
        )


@dataclass(frozen=True)
class BeetsMirrorCounts:
    items_inserted: int
    items_updated: int
    items_skipped: int
    albums_inserted: int
    albums_updated: int
    albums_skipped: int
    missing_in_beets: int
    stale_items: int


def decode_beets_path(raw_path: bytes | str) -> str:
    if isinstance(raw_path, bytes):
        return raw_path.decode("utf-8", errors="surrogateescape")
    return raw_path


def read_item(sqlite_conn, beets_id: int) -> BeetsMirrorRow | None:
    row = _fetch_one(sqlite_conn, "items", beets_id)
    if row is None:
        return None

    return _item_row_from_sqlite(sqlite_conn, row)


def read_album(sqlite_conn, beets_album_id: int) -> BeetsMirrorAlbumRow | None:
    row = _fetch_one(sqlite_conn, "albums", beets_album_id)
    if row is None:
        return None

    return _album_row_from_sqlite(sqlite_conn, row)


def iter_all_items(sqlite_conn) -> Iterator[BeetsMirrorRow]:
    for row in _fetch_all(sqlite_conn, "items"):
        yield _item_row_from_sqlite(sqlite_conn, row)


def iter_all_albums(sqlite_conn) -> Iterator[BeetsMirrorAlbumRow]:
    for row in _fetch_all(sqlite_conn, "albums"):
        yield _album_row_from_sqlite(sqlite_conn, row)


def upsert_item(pg_conn, row: BeetsMirrorRow) -> Literal["inserted", "updated"]:
    status: Literal["inserted", "updated"] = (
        "updated" if _item_exists(pg_conn, row.beets_id) else "inserted"
    )
    values = _item_values(row)
    pg_conn.execute(_upsert_statement(pg_conn, beets_items_table, values, "beets_id"))
    _replace_attributes(
        pg_conn,
        beets_item_attributes_table,
        entity_id=row.beets_id,
        attributes=row.flex_attributes,
    )
    return status


def upsert_album(pg_conn, row: BeetsMirrorAlbumRow) -> Literal["inserted", "updated"]:
    status: Literal["inserted", "updated"] = (
        "updated" if _album_exists(pg_conn, row.beets_album_id) else "inserted"
    )
    values = _album_values(row)
    pg_conn.execute(
        _upsert_statement(pg_conn, beets_albums_table, values, "beets_album_id")
    )
    _replace_attributes(
        pg_conn,
        beets_album_attributes_table,
        entity_id=row.beets_album_id,
        attributes=row.flex_attributes,
    )
    return status


def _fetch_one(sqlite_conn, table_name: str, entity_id: int) -> dict[str, Any] | None:
    cursor = sqlite_conn.execute(
        f"SELECT * FROM {table_name} WHERE id = ?",
        (entity_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_dict(cursor, row)


def _fetch_all(sqlite_conn, table_name: str) -> Iterator[dict[str, Any]]:
    cursor = sqlite_conn.execute(f"SELECT * FROM {table_name} ORDER BY id")
    for row in cursor.fetchall():
        yield _row_dict(cursor, row)


def _row_dict(cursor, row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)

    column_names = [description[0] for description in cursor.description]
    return dict(zip(column_names, row, strict=True))


def _item_row_from_sqlite(sqlite_conn, row: Mapping[str, Any]) -> BeetsMirrorRow:
    fixed_fields = _fixed_fields_from_sqlite(row, Item._fields)
    beets_id = _required_int(row["id"], field_name="id")
    album_id = _coerce_optional_int(fixed_fields.get("album_id"))

    return BeetsMirrorRow(
        beets_id=beets_id,
        album_id=album_id,
        fixed_fields=fixed_fields,
        flex_attributes=_read_attributes(sqlite_conn, "item_attributes", beets_id),
    )


def _album_row_from_sqlite(sqlite_conn, row: Mapping[str, Any]) -> BeetsMirrorAlbumRow:
    beets_album_id = _required_int(row["id"], field_name="id")
    return BeetsMirrorAlbumRow(
        beets_album_id=beets_album_id,
        fixed_fields=_fixed_fields_from_sqlite(row, Album._fields),
        flex_attributes=_read_attributes(
            sqlite_conn,
            "album_attributes",
            beets_album_id,
        ),
    )


def _fixed_fields_from_sqlite(
    row: Mapping[str, Any],
    fields: Mapping[str, beets_types.Type],
) -> dict[str, Any]:
    fixed_fields: dict[str, Any] = {}
    for field_name, field_type in fields.items():
        if field_name == "id":
            continue
        raw_value = row[field_name] if field_name in row else None
        fixed_fields[field_name] = _coerce_fixed_value(raw_value, field_type)

    return fixed_fields


def _read_attributes(
    sqlite_conn,
    table_name: str,
    entity_id: int,
) -> dict[str, str]:
    if not _sqlite_table_exists(sqlite_conn, table_name):
        return {}

    rows = sqlite_conn.execute(
        f"SELECT key, value FROM {table_name} WHERE entity_id = ? ORDER BY key",
        (entity_id,),
    ).fetchall()
    return {str(key): "" if value is None else str(value) for key, value in rows}


def _sqlite_table_exists(sqlite_conn, table_name: str) -> bool:
    row = sqlite_conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _coerce_fixed_value(
    raw_value: Any,
    field_type: beets_types.Type,
) -> Any:
    if raw_value is None:
        return None
    if isinstance(raw_value, memoryview):
        raw_value = bytes(raw_value)

    match field_type:
        case DateType():
            return datetime.fromtimestamp(float(raw_value), UTC)
        case PathType():
            if isinstance(raw_value, bytes):
                return decode_beets_path(raw_value)
            return str(raw_value)
        case beets_types.Boolean():
            return _coerce_bool(raw_value)
        case beets_types.BaseInteger():
            return int(round(float(raw_value)))
        case beets_types.BaseFloat():
            return float(raw_value)
        case beets_types.BaseString():
            if isinstance(raw_value, bytes):
                return raw_value.decode("utf-8", errors="surrogateescape")
            return str(raw_value)
        case _:
            raise TypeError(f"Unsupported Beets field type: {field_type!r}")


def _coerce_bool(raw_value: Any) -> bool:
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"0", "false", "f", "no", "n", "off", ""}:
            return False
        return True
    if isinstance(raw_value, bytes):
        return _coerce_bool(raw_value.decode("utf-8", errors="ignore"))
    return bool(raw_value)


def _required_int(raw_value: Any, *, field_name: str) -> int:
    value = _coerce_optional_int(raw_value)
    if value is None:
        raise ValueError(f"Beets {field_name} is required")
    return value


def _coerce_optional_int(raw_value: Any) -> int | None:
    if raw_value is None:
        return None
    return int(round(float(raw_value)))


def _validate_fixed_fields(
    fixed_fields: Mapping[str, Any],
    *,
    allowed_fields: Mapping[str, beets_types.Type],
    entity_name: str,
) -> None:
    unknown_fields = set(fixed_fields) - set(allowed_fields)
    if unknown_fields:
        joined = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unknown Beets {entity_name} fixed field(s): {joined}")


def _validate_explicit_id(
    fixed_fields: Mapping[str, Any],
    *,
    field_name: str,
    expected_id: int,
    entity_name: str,
) -> None:
    if field_name not in fixed_fields:
        return
    fixed_id = _required_int(fixed_fields[field_name], field_name=field_name)
    if fixed_id != expected_id:
        raise ValueError(f"Beets {entity_name} fixed_fields id must match row id")


def _item_values(row: BeetsMirrorRow) -> dict[str, Any]:
    values = {"beets_id": row.beets_id}
    for field_name in Item._fields:
        if field_name == "id":
            continue
        values[field_name] = row.fixed_fields.get(field_name)
    values["album_id"] = row.album_id
    return values


def _album_values(row: BeetsMirrorAlbumRow) -> dict[str, Any]:
    values = {"beets_album_id": row.beets_album_id}
    for field_name in Album._fields:
        if field_name == "id":
            continue
        values[field_name] = row.fixed_fields.get(field_name)
    return values


def _item_exists(pg_conn, beets_id: int) -> bool:
    return (
        pg_conn.execute(
            select(beets_items_table.c.beets_id).where(
                beets_items_table.c.beets_id == beets_id
            )
        ).first()
        is not None
    )


def _album_exists(pg_conn, beets_album_id: int) -> bool:
    return (
        pg_conn.execute(
            select(beets_albums_table.c.beets_album_id).where(
                beets_albums_table.c.beets_album_id == beets_album_id
            )
        ).first()
        is not None
    )


def _upsert_statement(pg_conn, table, values: dict[str, Any], pk_column: str):
    if pg_conn.dialect.name == "postgresql":
        statement = postgresql.insert(table).values(**values)
    elif pg_conn.dialect.name == "sqlite":
        statement = sqlite.insert(table).values(**values)
    else:
        statement = insert(table).values(**values)

    excluded = statement.excluded
    update_values = {
        column.name: getattr(excluded, column.name)
        for column in table.columns
        if column.name != pk_column
    }
    return statement.on_conflict_do_update(
        index_elements=[pk_column],
        set_=update_values,
    )


def _replace_attributes(
    pg_conn,
    attributes_table,
    *,
    entity_id: int,
    attributes: Mapping[str, str],
) -> None:
    pg_conn.execute(
        delete(attributes_table).where(attributes_table.c.entity_id == entity_id)
    )
    if not attributes:
        return

    pg_conn.execute(
        attributes_table.insert(),
        [
            {"entity_id": entity_id, "key": key, "value": value}
            for key, value in sorted(attributes.items())
        ],
    )
