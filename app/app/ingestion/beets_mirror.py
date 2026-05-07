from __future__ import annotations

from collections.abc import Mapping

from beets.dbcore import types as beets_types
from beets.library import Album, DateType, Item, PathType
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.sql.type_api import TypeEngine

metadata = MetaData()


def column_type_for_beets_field(field_type: beets_types.Type) -> TypeEngine:
    match field_type:
        case DateType():
            return DateTime(timezone=True)
        case PathType():
            return Text()
        case beets_types.BaseString():
            return Text()
        case beets_types.Boolean():
            return Boolean()
        case beets_types.BaseInteger():
            return Integer()
        case beets_types.BaseFloat():
            return Float()
        case _:
            raise TypeError(f"Unsupported Beets field type: {field_type!r}")


def _columns_for_beets_fields(
    fields: Mapping[str, beets_types.Type], *, id_column_name: str
) -> list[Column]:
    columns: list[Column] = []
    for field_name, field_type in fields.items():
        is_id_field = field_name == "id"
        columns.append(
            Column(
                id_column_name if is_id_field else field_name,
                column_type_for_beets_field(field_type),
                primary_key=is_id_field,
                nullable=not is_id_field,
            )
        )

    return columns


beets_items_table = Table(
    "beets_items",
    metadata,
    *_columns_for_beets_fields(Item._fields, id_column_name="beets_id"),
)

beets_albums_table = Table(
    "beets_albums",
    metadata,
    *_columns_for_beets_fields(Album._fields, id_column_name="beets_album_id"),
)

beets_item_attributes_table = Table(
    "beets_item_attributes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "entity_id",
        Integer,
        ForeignKey("beets_items.beets_id"),
        nullable=False,
    ),
    Column("key", Text, nullable=False),
    Column("value", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint("entity_id", "key"),
)

beets_album_attributes_table = Table(
    "beets_album_attributes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "entity_id",
        Integer,
        ForeignKey("beets_albums.beets_album_id"),
        nullable=False,
    ),
    Column("key", Text, nullable=False),
    Column("value", Text, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint("entity_id", "key"),
)
