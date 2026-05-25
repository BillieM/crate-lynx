from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    or_,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.core.tables import (
    failed_ingestion_attempts_view,
    final_links_view,
    suggested_links_view,
    streaming_tracks_view,
)

metadata = MetaData()

local_tracks_table = Table(
    "local_tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("file_path", String, nullable=False),
    Column("library_root_rel_path", String, nullable=False),
    Column("fingerprint", String, nullable=True),
    Column("beets_id", Integer, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    UniqueConstraint("beets_id", name="uq_local_tracks_beets_id"),
    Index("ix_local_tracks_fingerprint", "fingerprint", postgresql_using="hash"),
    Index("ix_local_tracks_beets_id", "beets_id"),
)

SUGGESTED_LINK_STATUS_PENDING = "pending"


@dataclass(slots=True)
class PersistedLocalTrack:
    id: int
    file_path: str


@dataclass(frozen=True, slots=True)
class MetadataFieldRecord:
    key: str
    value: str | None


@dataclass(frozen=True, slots=True)
class StreamingTrackSummaryRecord:
    streaming_track_id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class LocalTrackSearchResultRecord:
    id: int
    title: str | None
    artist: str | None
    album: str | None
    file_path: str
    library_root_rel_path: str
    link_status: str
    final_link_id: int | None


@dataclass(frozen=True, slots=True)
class LocalTrackFinalLinkRecord:
    id: int
    streaming_track_id: int
    approved_at: datetime
    streaming_track: StreamingTrackSummaryRecord


@dataclass(frozen=True, slots=True)
class LocalTrackSuggestionRecord:
    id: int
    streaming_track_id: int
    match_method: str
    score: float
    status: str
    created_at: datetime
    streaming_track: StreamingTrackSummaryRecord


@dataclass(frozen=True, slots=True)
class LocalTrackFailedIngestionRecord:
    id: int
    source_path: str
    filename: str
    failure_reason: str
    failed_at: datetime


@dataclass(frozen=True, slots=True)
class LocalTrackDetailRecord:
    id: int
    file_path: str
    library_root_rel_path: str
    fingerprint: str | None
    beets_id: int | None
    created_at: datetime
    updated_at: datetime
    link_status: str
    title: str | None
    artist: str | None
    album: str | None
    duration_ms: int | None
    final_link: LocalTrackFinalLinkRecord | None
    pending_suggestions: list[LocalTrackSuggestionRecord]
    beets_item: BeetsItemDetailRecord | None
    beets_album: BeetsAlbumDetailRecord | None
    failed_ingestion_attempts: list[LocalTrackFailedIngestionRecord]


@dataclass(frozen=True, slots=True)
class BeetsItemDetailRecord:
    beets_id: int
    fields: list[MetadataFieldRecord]
    attributes: list[MetadataFieldRecord]


@dataclass(frozen=True, slots=True)
class BeetsAlbumDetailRecord:
    beets_album_id: int
    fields: list[MetadataFieldRecord]
    attributes: list[MetadataFieldRecord]


@dataclass(frozen=True, slots=True)
class BeetsMirrorTables:
    items: Table
    item_attributes: Table
    albums: Table
    album_attributes: Table


class LocalTrackStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def persist(
        self,
        *,
        library_root: Path | str,
        library_path: Path | str,
        fingerprint: str | None,
        beets_id: int | None,
    ) -> PersistedLocalTrack:
        relative_path = _relative_library_path(library_root, library_path)

        with self._engine.begin() as connection:
            statement = _conflict_insert(
                local_tracks_table,
                connection.dialect.name,
            ).values(
                file_path=relative_path,
                library_root_rel_path=relative_path,
                fingerprint=fingerprint,
                beets_id=beets_id,
            )
            row = (
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=[local_tracks_table.c.beets_id],
                        set_={
                            "file_path": statement.excluded.file_path,
                            "library_root_rel_path": (
                                statement.excluded.library_root_rel_path
                            ),
                            "fingerprint": statement.excluded.fingerprint,
                            "updated_at": func.now(),
                        },
                    ).returning(
                        local_tracks_table.c.id,
                        local_tracks_table.c.file_path,
                    )
                )
                .mappings()
                .one()
            )

        return PersistedLocalTrack(id=row["id"], file_path=row["file_path"])

    def get_detail(self, local_track_id: int) -> LocalTrackDetailRecord | None:
        beets_tables = _beets_mirror_tables()
        with self._engine.connect() as connection:
            local_track = (
                connection.execute(
                    select(
                        local_tracks_table.c.id,
                        local_tracks_table.c.file_path,
                        local_tracks_table.c.library_root_rel_path,
                        local_tracks_table.c.fingerprint,
                        local_tracks_table.c.beets_id,
                        local_tracks_table.c.created_at,
                        local_tracks_table.c.updated_at,
                        beets_tables.items.c.title,
                        beets_tables.items.c.artist,
                        beets_tables.items.c.album,
                        beets_tables.items.c.length,
                    )
                    .where(local_tracks_table.c.id == local_track_id)
                    .select_from(
                        local_tracks_table.outerjoin(
                            beets_tables.items,
                            beets_tables.items.c.beets_id
                            == local_tracks_table.c.beets_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )

            if local_track is None:
                return None

            final_link_row = (
                connection.execute(
                    select(
                        final_links_view.c.id,
                        final_links_view.c.streaming_track_id,
                        final_links_view.c.approved_at,
                        streaming_tracks_view.c.provider_track_id,
                        streaming_tracks_view.c.title,
                        streaming_tracks_view.c.artist,
                        streaming_tracks_view.c.album,
                        streaming_tracks_view.c.year,
                        streaming_tracks_view.c.isrc,
                        streaming_tracks_view.c.duration_ms,
                    )
                    .select_from(
                        final_links_view.join(
                            streaming_tracks_view,
                            streaming_tracks_view.c.id
                            == final_links_view.c.streaming_track_id,
                        )
                    )
                    .where(final_links_view.c.local_track_id == local_track_id)
                )
                .mappings()
                .one_or_none()
            )
            suggestion_rows = (
                connection.execute(
                    select(
                        suggested_links_view.c.id,
                        suggested_links_view.c.streaming_track_id,
                        suggested_links_view.c.match_method,
                        suggested_links_view.c.score,
                        suggested_links_view.c.status,
                        suggested_links_view.c.created_at,
                        streaming_tracks_view.c.provider_track_id,
                        streaming_tracks_view.c.title,
                        streaming_tracks_view.c.artist,
                        streaming_tracks_view.c.album,
                        streaming_tracks_view.c.year,
                        streaming_tracks_view.c.isrc,
                        streaming_tracks_view.c.duration_ms,
                    )
                    .select_from(
                        suggested_links_view.join(
                            streaming_tracks_view,
                            streaming_tracks_view.c.id
                            == suggested_links_view.c.streaming_track_id,
                        )
                    )
                    .where(
                        suggested_links_view.c.local_track_id == local_track_id,
                        suggested_links_view.c.status == SUGGESTED_LINK_STATUS_PENDING,
                    )
                    .order_by(
                        suggested_links_view.c.score.desc(),
                        suggested_links_view.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )
            failed_ingestion_rows = (
                connection.execute(
                    select(
                        failed_ingestion_attempts_view.c.id,
                        failed_ingestion_attempts_view.c.source_path,
                        failed_ingestion_attempts_view.c.filename,
                        failed_ingestion_attempts_view.c.failure_reason,
                        failed_ingestion_attempts_view.c.failed_at,
                    )
                    .where(
                        failed_ingestion_attempts_view.c.local_track_id
                        == local_track_id
                    )
                    .order_by(
                        failed_ingestion_attempts_view.c.failed_at.desc(),
                        failed_ingestion_attempts_view.c.id.desc(),
                    )
                )
                .mappings()
                .all()
            )
            beets_item_row = None
            beets_item_attributes = []
            beets_album_row = None
            beets_album_attributes = []
            beets_id = local_track["beets_id"]
            if isinstance(beets_id, int):
                beets_item_row = (
                    connection.execute(
                        select(beets_tables.items).where(
                            beets_tables.items.c.beets_id == beets_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                beets_item_attributes = (
                    connection.execute(
                        select(
                            beets_tables.item_attributes.c.key,
                            beets_tables.item_attributes.c.value,
                        )
                        .where(beets_tables.item_attributes.c.entity_id == beets_id)
                        .order_by(beets_tables.item_attributes.c.key.asc())
                    )
                    .mappings()
                    .all()
                )
                album_id = (
                    beets_item_row["album_id"] if beets_item_row is not None else None
                )
                if isinstance(album_id, int):
                    beets_album_row = (
                        connection.execute(
                            select(beets_tables.albums).where(
                                beets_tables.albums.c.beets_album_id == album_id
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    beets_album_attributes = (
                        connection.execute(
                            select(
                                beets_tables.album_attributes.c.key,
                                beets_tables.album_attributes.c.value,
                            )
                            .where(
                                beets_tables.album_attributes.c.entity_id == album_id
                            )
                            .order_by(beets_tables.album_attributes.c.key.asc())
                        )
                        .mappings()
                        .all()
                    )

        final_link = (
            LocalTrackFinalLinkRecord(
                id=final_link_row["id"],
                streaming_track_id=final_link_row["streaming_track_id"],
                approved_at=final_link_row["approved_at"],
                streaming_track=_streaming_track_summary(final_link_row),
            )
            if final_link_row is not None
            else None
        )
        pending_suggestions = [
            LocalTrackSuggestionRecord(
                id=row["id"],
                streaming_track_id=row["streaming_track_id"],
                match_method=row["match_method"],
                score=row["score"],
                status=row["status"],
                created_at=row["created_at"],
                streaming_track=_streaming_track_summary(row),
            )
            for row in suggestion_rows
        ]

        if final_link is not None:
            link_status = "linked"
        elif pending_suggestions:
            link_status = "pending"
        else:
            link_status = "unlinked"

        return LocalTrackDetailRecord(
            id=local_track["id"],
            file_path=local_track["file_path"],
            library_root_rel_path=local_track["library_root_rel_path"],
            fingerprint=local_track["fingerprint"],
            beets_id=local_track["beets_id"],
            created_at=local_track["created_at"],
            updated_at=local_track["updated_at"],
            link_status=link_status,
            title=local_track["title"],
            artist=local_track["artist"],
            album=local_track["album"],
            duration_ms=(
                int(float(local_track["length"]) * 1000)
                if local_track["length"] is not None
                else None
            ),
            final_link=final_link,
            pending_suggestions=pending_suggestions,
            beets_item=(
                BeetsItemDetailRecord(
                    beets_id=beets_item_row["beets_id"],
                    fields=_metadata_fields(beets_item_row, beets_tables.items),
                    attributes=_attribute_fields(beets_item_attributes),
                )
                if beets_item_row is not None
                else None
            ),
            beets_album=(
                BeetsAlbumDetailRecord(
                    beets_album_id=beets_album_row["beets_album_id"],
                    fields=_metadata_fields(beets_album_row, beets_tables.albums),
                    attributes=_attribute_fields(beets_album_attributes),
                )
                if beets_album_row is not None
                else None
            ),
            failed_ingestion_attempts=[
                LocalTrackFailedIngestionRecord(
                    id=row["id"],
                    source_path=row["source_path"],
                    filename=row["filename"],
                    failure_reason=row["failure_reason"],
                    failed_at=row["failed_at"],
                )
                for row in failed_ingestion_rows
            ],
        )

    def get_file_path(self, local_track_id: int) -> str | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(local_tracks_table.c.file_path).where(
                        local_tracks_table.c.id == local_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        file_path = row["file_path"]
        return file_path if isinstance(file_path, str) else None

    def list_unresolved_local_track_ids(self) -> list[int]:
        query = (
            select(local_tracks_table.c.id)
            .select_from(
                local_tracks_table.outerjoin(
                    final_links_view,
                    final_links_view.c.local_track_id == local_tracks_table.c.id,
                )
            )
            .where(final_links_view.c.id.is_(None))
            .order_by(local_tracks_table.c.id.asc())
        )

        with self._engine.connect() as connection:
            return [int(local_track_id) for local_track_id in connection.scalars(query)]

    def search(
        self, *, query: str = "", limit: int = 20
    ) -> list[LocalTrackSearchResultRecord]:
        beets_tables = _beets_mirror_tables()
        pending_suggestion_ids = (
            select(
                suggested_links_view.c.local_track_id,
                func.min(suggested_links_view.c.id).label("suggestion_id"),
            )
            .where(suggested_links_view.c.status == SUGGESTED_LINK_STATUS_PENDING)
            .group_by(suggested_links_view.c.local_track_id)
            .subquery()
        )
        search_query = (
            select(
                local_tracks_table.c.id,
                local_tracks_table.c.file_path,
                local_tracks_table.c.library_root_rel_path,
                final_links_view.c.id.label("final_link_id"),
                pending_suggestion_ids.c.suggestion_id,
                beets_tables.items.c.title,
                beets_tables.items.c.artist,
                beets_tables.items.c.album,
            )
            .select_from(
                local_tracks_table.outerjoin(
                    beets_tables.items,
                    beets_tables.items.c.beets_id == local_tracks_table.c.beets_id,
                )
                .outerjoin(
                    final_links_view,
                    final_links_view.c.local_track_id == local_tracks_table.c.id,
                )
                .outerjoin(
                    pending_suggestion_ids,
                    pending_suggestion_ids.c.local_track_id == local_tracks_table.c.id,
                )
            )
            .order_by(local_tracks_table.c.id.asc())
            .limit(limit)
        )
        normalized_query = query.strip()
        if normalized_query:
            like_query = f"%{normalized_query}%"
            clauses = [
                local_tracks_table.c.file_path.ilike(like_query),
                local_tracks_table.c.library_root_rel_path.ilike(like_query),
                beets_tables.items.c.title.ilike(like_query),
                beets_tables.items.c.artist.ilike(like_query),
                beets_tables.items.c.album.ilike(like_query),
            ]
            if normalized_query.isdecimal():
                clauses.append(local_tracks_table.c.id == int(normalized_query))
                clauses.append(local_tracks_table.c.beets_id == int(normalized_query))
            search_query = search_query.where(or_(*clauses))

        with self._engine.connect() as connection:
            rows = connection.execute(search_query).mappings().all()

        return [
            LocalTrackSearchResultRecord(
                id=row["id"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                file_path=row["file_path"],
                library_root_rel_path=row["library_root_rel_path"],
                link_status=_link_status(row),
                final_link_id=row["final_link_id"],
            )
            for row in rows
        ]


def _conflict_insert(target_table, dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql_insert(target_table)
    if dialect_name == "sqlite":
        return sqlite_insert(target_table)
    raise ValueError(
        f"Unsupported database dialect for local track upsert: {dialect_name}"
    )


def _relative_library_path(library_root: Path | str, library_path: Path | str) -> str:
    library_root_path = Path(library_root).resolve()
    track_path = Path(library_path).resolve()
    return str(track_path.relative_to(library_root_path))


def _streaming_track_summary(row) -> StreamingTrackSummaryRecord:
    return StreamingTrackSummaryRecord(
        streaming_track_id=row["streaming_track_id"],
        provider_track_id=row["provider_track_id"],
        title=row["title"],
        artist=row["artist"],
        album=row["album"],
        year=row["year"],
        isrc=row["isrc"],
        duration_ms=row["duration_ms"],
    )


def _metadata_fields(row, source_table: Table) -> list[MetadataFieldRecord]:
    return [
        MetadataFieldRecord(
            key=column.name,
            value=_metadata_value(row[column.name]),
        )
        for column in source_table.c
    ]


def _attribute_fields(rows) -> list[MetadataFieldRecord]:
    return [
        MetadataFieldRecord(key=row["key"], value=_metadata_value(row["value"]))
        for row in rows
    ]


def _metadata_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _link_status(row) -> str:
    if row["final_link_id"] is not None:
        return "linked"
    if row["suggestion_id"] is not None:
        return "pending"
    return "unlinked"


def _beets_mirror_tables() -> BeetsMirrorTables:
    from app.ingestion.beets_mirror import (
        beets_album_attributes_table,
        beets_albums_table,
        beets_item_attributes_table,
        beets_items_table,
    )

    return BeetsMirrorTables(
        items=beets_items_table,
        item_attributes=beets_item_attributes_table,
        albums=beets_albums_table,
        album_attributes=beets_album_attributes_table,
    )
