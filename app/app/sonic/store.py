from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any

from sqlalchemy import String, case, cast, delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from app.core.db import create_database_engine
from app.ingestion.beets_mirror import (
    beets_item_attributes_table,
    beets_items_table,
)
from app.local_tracks.store import local_tracks_table
from app.sonic.models import (
    PLAYLIST_GENERATION_STATUS_COMPLETED,
    PLAYLIST_GENERATION_STATUS_FAILED,
    PLAYLIST_GENERATION_STATUS_PENDING,
    PLAYLIST_GENERATION_STATUS_RUNNING,
    SONIC_FEATURE_STATUS_FAILED,
    SONIC_FEATURE_STATUS_PENDING,
    SONIC_FEATURE_STATUS_READY,
    SONIC_SOURCE_ALL_LOCAL,
    SONIC_SOURCE_STREAMING_PLAYLISTS,
    SONIC_TAG_FILTER_ITEM_ATTRIBUTE,
    SONIC_TAG_FILTER_ITEM_FIELD,
    SONIC_TAG_FILTER_MATCH_CONTAINS,
    GeneratedPlaylistRecord,
    GeneratedPlaylistTrackRecord,
    PlaylistGenerationRunRecord,
    SonicFeatureSummaryRecord,
    SonicTrackFeatureRecord,
    generated_playlist_tracks_table,
    generated_playlists_table,
    playlist_generation_runs_table,
    sonic_track_features_table,
)
from app.streaming.models import playlist_membership_table, streaming_playlists_table


class PlaylistGenerationRunNotFoundError(ValueError):
    pass


class GeneratedPlaylistNotFoundError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SonicReadyTrack:
    local_track_id: int
    descriptors: dict[str, Any]
    vector: list[float]


@dataclass(frozen=True, slots=True)
class PersistedGeneratedPlaylist:
    id: int
    client_key: str


class SonicStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def feature_summary(self) -> SonicFeatureSummaryRecord:
        status_case = lambda status: case(  # noqa: E731
            (sonic_track_features_table.c.status == status, 1),
            else_=0,
        )
        query = select(
            func.count(local_tracks_table.c.id).label("total_tracks"),
            func.sum(status_case(SONIC_FEATURE_STATUS_READY)).label("ready_tracks"),
            func.sum(status_case(SONIC_FEATURE_STATUS_PENDING)).label("pending_tracks"),
            func.sum(status_case(SONIC_FEATURE_STATUS_FAILED)).label("failed_tracks"),
            func.sum(
                case((sonic_track_features_table.c.id.is_(None), 1), else_=0)
            ).label("missing_tracks"),
        ).select_from(
            local_tracks_table.outerjoin(
                sonic_track_features_table,
                sonic_track_features_table.c.local_track_id == local_tracks_table.c.id,
            )
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one()

        return SonicFeatureSummaryRecord(
            total_tracks=int(row["total_tracks"] or 0),
            ready_tracks=int(row["ready_tracks"] or 0),
            pending_tracks=int(row["pending_tracks"] or 0),
            failed_tracks=int(row["failed_tracks"] or 0),
            missing_tracks=int(row["missing_tracks"] or 0),
        )

    def mark_feature_pending(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        local_track_id: int,
    ) -> SonicTrackFeatureRecord:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            existing_id = connection.execute(
                select(sonic_track_features_table.c.id).where(
                    sonic_track_features_table.c.local_track_id == local_track_id
                )
            ).scalar_one_or_none()
            if existing_id is None:
                result = connection.execute(
                    insert(sonic_track_features_table).values(
                        local_track_id=local_track_id,
                        analyzer_key=analyzer_key,
                        analyzer_version=analyzer_version,
                        status=SONIC_FEATURE_STATUS_PENDING,
                        descriptor_json=None,
                        vector_json=None,
                        failure_detail=None,
                        extracted_at=None,
                        updated_at=now,
                    )
                )
                feature_id = result.inserted_primary_key[0]
            else:
                feature_id = existing_id
                connection.execute(
                    update(sonic_track_features_table)
                    .where(sonic_track_features_table.c.id == feature_id)
                    .values(
                        analyzer_key=analyzer_key,
                        analyzer_version=analyzer_version,
                        status=SONIC_FEATURE_STATUS_PENDING,
                        failure_detail=None,
                        updated_at=now,
                    )
                )

            row = (
                connection.execute(
                    select(sonic_track_features_table).where(
                        sonic_track_features_table.c.id == feature_id
                    )
                )
                .mappings()
                .one()
            )

        return _feature_record(row)

    def persist_feature_success(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        descriptors: dict[str, Any],
        local_track_id: int,
        vector: list[float],
    ) -> SonicTrackFeatureRecord:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            existing_id = connection.execute(
                select(sonic_track_features_table.c.id).where(
                    sonic_track_features_table.c.local_track_id == local_track_id
                )
            ).scalar_one_or_none()
            values = {
                "analyzer_key": analyzer_key,
                "analyzer_version": analyzer_version,
                "status": SONIC_FEATURE_STATUS_READY,
                "descriptor_json": descriptors,
                "vector_json": vector,
                "failure_detail": None,
                "extracted_at": now,
                "updated_at": now,
            }
            if existing_id is None:
                result = connection.execute(
                    insert(sonic_track_features_table).values(
                        local_track_id=local_track_id,
                        **values,
                    )
                )
                feature_id = result.inserted_primary_key[0]
            else:
                feature_id = existing_id
                connection.execute(
                    update(sonic_track_features_table)
                    .where(sonic_track_features_table.c.id == feature_id)
                    .values(**values)
                )

            row = (
                connection.execute(
                    select(sonic_track_features_table).where(
                        sonic_track_features_table.c.id == feature_id
                    )
                )
                .mappings()
                .one()
            )

        return _feature_record(row)

    def persist_feature_failure(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        failure_detail: str,
        local_track_id: int,
    ) -> SonicTrackFeatureRecord:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            existing_id = connection.execute(
                select(sonic_track_features_table.c.id).where(
                    sonic_track_features_table.c.local_track_id == local_track_id
                )
            ).scalar_one_or_none()
            values = {
                "analyzer_key": analyzer_key,
                "analyzer_version": analyzer_version,
                "status": SONIC_FEATURE_STATUS_FAILED,
                "failure_detail": failure_detail,
                "updated_at": now,
            }
            if existing_id is None:
                result = connection.execute(
                    insert(sonic_track_features_table).values(
                        local_track_id=local_track_id,
                        descriptor_json=None,
                        vector_json=None,
                        extracted_at=None,
                        **values,
                    )
                )
                feature_id = result.inserted_primary_key[0]
            else:
                feature_id = existing_id
                connection.execute(
                    update(sonic_track_features_table)
                    .where(sonic_track_features_table.c.id == feature_id)
                    .values(**values)
                )

            row = (
                connection.execute(
                    select(sonic_track_features_table).where(
                        sonic_track_features_table.c.id == feature_id
                    )
                )
                .mappings()
                .one()
            )

        return _feature_record(row)

    def list_missing_feature_track_ids(self, *, limit: int = 100) -> list[int]:
        query = (
            select(local_tracks_table.c.id)
            .select_from(
                local_tracks_table.outerjoin(
                    sonic_track_features_table,
                    sonic_track_features_table.c.local_track_id
                    == local_tracks_table.c.id,
                )
            )
            .where(
                (sonic_track_features_table.c.id.is_(None))
                | (sonic_track_features_table.c.status == SONIC_FEATURE_STATUS_FAILED)
            )
            .order_by(local_tracks_table.c.id.asc())
            .limit(limit)
        )
        with self._engine.connect() as connection:
            return [int(track_id) for track_id in connection.execute(query).scalars()]

    def ready_tracks_for_source(
        self,
        source_filter: dict[str, Any],
    ) -> list[SonicReadyTrack]:
        with self._engine.connect() as connection:
            local_track_ids = _resolve_source_track_ids(connection, source_filter)
            if not local_track_ids:
                return []

            rows = (
                connection.execute(
                    select(
                        sonic_track_features_table.c.local_track_id,
                        sonic_track_features_table.c.descriptor_json,
                        sonic_track_features_table.c.vector_json,
                    )
                    .where(
                        sonic_track_features_table.c.local_track_id.in_(
                            sorted(local_track_ids)
                        ),
                        sonic_track_features_table.c.status
                        == SONIC_FEATURE_STATUS_READY,
                        sonic_track_features_table.c.vector_json.is_not(None),
                    )
                    .order_by(sonic_track_features_table.c.local_track_id.asc())
                )
                .mappings()
                .all()
            )

        return [
            SonicReadyTrack(
                local_track_id=int(row["local_track_id"]),
                descriptors=dict(row["descriptor_json"] or {}),
                vector=[float(value) for value in row["vector_json"]],
            )
            for row in rows
            if isinstance(row["vector_json"], list)
        ]

    def create_generation_run(
        self,
        *,
        generation_config: dict[str, Any],
        source_filter: dict[str, Any],
    ) -> PlaylistGenerationRunRecord:
        with self._engine.begin() as connection:
            result = connection.execute(
                insert(playlist_generation_runs_table).values(
                    status=PLAYLIST_GENERATION_STATUS_PENDING,
                    source_filter_json=source_filter,
                    generation_config_json=generation_config,
                    playlist_count=0,
                    track_count=0,
                )
            )
            run_id = result.inserted_primary_key[0]
            row = (
                connection.execute(
                    select(playlist_generation_runs_table).where(
                        playlist_generation_runs_table.c.id == run_id
                    )
                )
                .mappings()
                .one()
            )

        return _run_record(row)

    def list_generation_runs(
        self, *, limit: int = 50
    ) -> list[PlaylistGenerationRunRecord]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(playlist_generation_runs_table)
                    .order_by(playlist_generation_runs_table.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )

        return [_run_record(row) for row in rows]

    def get_generation_run(self, run_id: int) -> PlaylistGenerationRunRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(playlist_generation_runs_table).where(
                        playlist_generation_runs_table.c.id == run_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        return _run_record(row) if row is not None else None

    def mark_generation_run_running(self, run_id: int) -> None:
        self._update_run(
            run_id,
            status=PLAYLIST_GENERATION_STATUS_RUNNING,
            error_detail=None,
            updated_at=datetime.now(UTC),
        )

    def mark_generation_run_failed(self, run_id: int, error_detail: str) -> None:
        self._update_run(
            run_id,
            status=PLAYLIST_GENERATION_STATUS_FAILED,
            error_detail=error_detail,
            completed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def replace_generated_playlists(
        self,
        *,
        playlists: list[dict[str, Any]],
        run_id: int,
        track_count: int,
    ) -> None:
        with self._engine.begin() as connection:
            existing_playlist_ids = [
                int(playlist_id)
                for playlist_id in connection.execute(
                    select(generated_playlists_table.c.id).where(
                        generated_playlists_table.c.run_id == run_id
                    )
                ).scalars()
            ]
            if existing_playlist_ids:
                connection.execute(
                    delete(generated_playlist_tracks_table).where(
                        generated_playlist_tracks_table.c.generated_playlist_id.in_(
                            existing_playlist_ids
                        )
                    )
                )
                connection.execute(
                    delete(generated_playlists_table).where(
                        generated_playlists_table.c.id.in_(existing_playlist_ids)
                    )
                )

            persisted_by_key: dict[str, int] = {}
            pending = list(playlists)
            while pending:
                progressed = False
                next_pending = []
                for playlist in pending:
                    parent_key = playlist.get("parent_key")
                    if parent_key is not None and parent_key not in persisted_by_key:
                        next_pending.append(playlist)
                        continue

                    result = connection.execute(
                        insert(generated_playlists_table).values(
                            run_id=run_id,
                            parent_playlist_id=(
                                persisted_by_key[parent_key]
                                if parent_key is not None
                                else None
                            ),
                            depth=playlist["depth"],
                            position=playlist["position"],
                            name=playlist["name"],
                            summary_json=playlist["summary"],
                            track_count=len(playlist["track_ids"]),
                        )
                    )
                    playlist_id = result.inserted_primary_key[0]
                    persisted_by_key[playlist["client_key"]] = playlist_id
                    connection.execute(
                        insert(generated_playlist_tracks_table),
                        [
                            {
                                "generated_playlist_id": playlist_id,
                                "local_track_id": local_track_id,
                                "position": position,
                            }
                            for position, local_track_id in enumerate(
                                playlist["track_ids"],
                                start=1,
                            )
                        ],
                    )
                    progressed = True

                if not progressed:
                    raise ValueError("Generated playlist tree contains missing parents")
                pending = next_pending

            connection.execute(
                update(playlist_generation_runs_table)
                .where(playlist_generation_runs_table.c.id == run_id)
                .values(
                    status=PLAYLIST_GENERATION_STATUS_COMPLETED,
                    playlist_count=len(playlists),
                    track_count=track_count,
                    error_detail=None,
                    completed_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

    def list_generated_playlists(
        self,
        *,
        run_id: int | None = None,
        limit: int | None = None,
    ) -> list[GeneratedPlaylistRecord]:
        query = select(generated_playlists_table)
        if run_id is not None:
            query = query.where(generated_playlists_table.c.run_id == run_id)
        query = query.order_by(
            generated_playlists_table.c.run_id.desc(),
            generated_playlists_table.c.depth.asc(),
            generated_playlists_table.c.position.asc(),
            generated_playlists_table.c.id.asc(),
        )
        if limit is not None:
            query = query.limit(limit)

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()

        return [_generated_playlist_record(row) for row in rows]

    def get_generated_playlist(
        self,
        generated_playlist_id: int,
    ) -> GeneratedPlaylistRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(generated_playlists_table).where(
                        generated_playlists_table.c.id == generated_playlist_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        return _generated_playlist_record(row) if row is not None else None

    def list_generated_playlist_tracks(
        self,
        generated_playlist_id: int,
    ) -> list[GeneratedPlaylistTrackRecord]:
        query = (
            select(
                generated_playlist_tracks_table.c.id,
                generated_playlist_tracks_table.c.local_track_id,
                generated_playlist_tracks_table.c.position,
                local_tracks_table.c.file_path,
                local_tracks_table.c.library_root_rel_path,
                beets_items_table.c.title,
                beets_items_table.c.artist,
                beets_items_table.c.album,
                beets_items_table.c.length,
            )
            .select_from(
                generated_playlist_tracks_table.join(
                    local_tracks_table,
                    local_tracks_table.c.id
                    == generated_playlist_tracks_table.c.local_track_id,
                ).outerjoin(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
            )
            .where(
                generated_playlist_tracks_table.c.generated_playlist_id
                == generated_playlist_id
            )
            .order_by(generated_playlist_tracks_table.c.position.asc())
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()

        return [
            GeneratedPlaylistTrackRecord(
                id=row["id"],
                local_track_id=row["local_track_id"],
                position=row["position"],
                title=row["title"] or _display_filename(row["library_root_rel_path"]),
                artist=row["artist"],
                album=row["album"],
                duration_ms=(
                    int(float(row["length"]) * 1000)
                    if row["length"] is not None
                    else None
                ),
                file_path=row["file_path"],
                library_root_rel_path=row["library_root_rel_path"],
            )
            for row in rows
        ]

    def _update_run(self, run_id: int, **values: Any) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                update(playlist_generation_runs_table)
                .where(playlist_generation_runs_table.c.id == run_id)
                .values(**values)
            )
        if result.rowcount == 0:
            raise PlaylistGenerationRunNotFoundError(str(run_id))


def _resolve_source_track_ids(
    connection: Connection,
    source_filter: dict[str, Any],
) -> set[int]:
    source_type = source_filter.get("source_type", SONIC_SOURCE_ALL_LOCAL)
    if source_type == SONIC_SOURCE_STREAMING_PLAYLISTS:
        track_ids = _local_track_ids_for_streaming_playlists(
            connection,
            [int(value) for value in source_filter.get("streaming_playlist_ids", [])],
        )
    else:
        track_ids = set(
            int(track_id)
            for track_id in connection.execute(
                select(local_tracks_table.c.id).order_by(local_tracks_table.c.id.asc())
            ).scalars()
        )

    for tag_filter in source_filter.get("tag_filters", []):
        track_ids &= _local_track_ids_for_tag_filter(connection, track_ids, tag_filter)

    return track_ids


def _local_track_ids_for_streaming_playlists(
    connection: Connection,
    playlist_ids: list[int],
) -> set[int]:
    if not playlist_ids:
        return set()

    from app.relationships.resolver import StreamingRelationshipResolver

    rows = (
        connection.execute(
            select(playlist_membership_table.c.streaming_track_id)
            .select_from(
                playlist_membership_table.join(
                    streaming_playlists_table,
                    streaming_playlists_table.c.id
                    == playlist_membership_table.c.playlist_id,
                )
            )
            .where(playlist_membership_table.c.playlist_id.in_(playlist_ids))
            .order_by(
                playlist_membership_table.c.playlist_id.asc(),
                playlist_membership_table.c.position.asc(),
            )
        )
        .mappings()
        .all()
    )
    resolver = StreamingRelationshipResolver(connection)
    local_track_ids = set()
    for row in rows:
        resolved_link = resolver.resolve(int(row["streaming_track_id"]))
        if resolved_link is not None:
            local_track_ids.add(resolved_link.local_track_id)
    return local_track_ids


def _local_track_ids_for_tag_filter(
    connection: Connection,
    local_track_ids: set[int],
    tag_filter: dict[str, Any],
) -> set[int]:
    if not local_track_ids:
        return set()

    scope = tag_filter.get("scope")
    key = str(tag_filter.get("key", "")).strip()
    value = str(tag_filter.get("value", "")).strip()
    match = tag_filter.get("match", SONIC_TAG_FILTER_MATCH_CONTAINS)
    if not key or not value:
        return local_track_ids

    if scope == SONIC_TAG_FILTER_ITEM_FIELD:
        if key not in beets_items_table.c:
            return set()
        value_column = cast(beets_items_table.c[key], String)
        query = (
            select(local_tracks_table.c.id)
            .select_from(
                local_tracks_table.join(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
            )
            .where(local_tracks_table.c.id.in_(local_track_ids))
        )
    elif scope == SONIC_TAG_FILTER_ITEM_ATTRIBUTE:
        value_column = beets_item_attributes_table.c.value
        query = (
            select(local_tracks_table.c.id)
            .select_from(
                local_tracks_table.join(
                    beets_item_attributes_table,
                    beets_item_attributes_table.c.entity_id
                    == local_tracks_table.c.beets_id,
                )
            )
            .where(
                local_tracks_table.c.id.in_(local_track_ids),
                beets_item_attributes_table.c.key == key,
            )
        )
    else:
        return local_track_ids

    if match == SONIC_TAG_FILTER_MATCH_CONTAINS:
        query = query.where(value_column.ilike(f"%{value}%"))
    else:
        query = query.where(func.lower(value_column) == value.lower())

    return {int(track_id) for track_id in connection.execute(query).scalars()}


def _feature_record(row: Any) -> SonicTrackFeatureRecord:
    return SonicTrackFeatureRecord(
        id=row["id"],
        local_track_id=row["local_track_id"],
        analyzer_key=row["analyzer_key"],
        analyzer_version=row["analyzer_version"],
        status=row["status"],
        descriptor_json=row["descriptor_json"],
        vector_json=row["vector_json"],
        failure_detail=row["failure_detail"],
        extracted_at=row["extracted_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_record(row: Any) -> PlaylistGenerationRunRecord:
    return PlaylistGenerationRunRecord(
        id=row["id"],
        status=row["status"],
        source_filter_json=dict(row["source_filter_json"] or {}),
        generation_config_json=dict(row["generation_config_json"] or {}),
        playlist_count=row["playlist_count"],
        track_count=row["track_count"],
        error_detail=row["error_detail"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _generated_playlist_record(row: Any) -> GeneratedPlaylistRecord:
    return GeneratedPlaylistRecord(
        id=row["id"],
        run_id=row["run_id"],
        parent_playlist_id=row["parent_playlist_id"],
        depth=row["depth"],
        position=row["position"],
        name=row["name"],
        summary_json=dict(row["summary_json"] or {}),
        track_count=row["track_count"],
        created_at=row["created_at"],
    )


def _display_filename(path: str) -> str:
    return PurePath(path).name
