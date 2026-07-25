from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any

from sqlalchemy import (
    String,
    and_,
    case,
    cast,
    delete,
    func,
    insert,
    inspect as sqlalchemy_inspect,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.autopilot.models import (
    AUTOPILOT_ITEM_STATUS_FAILED,
    AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
    AUTOPILOT_ITEM_STATUS_REVIEW,
    AUTOPILOT_RUN_STATUS_PARTIAL,
    AUTOPILOT_RUN_STATUS_SUCCEEDED,
    autopilot_run_items_table,
    autopilot_runs_table,
)
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
    PLAYLIST_GENERATION_TRIGGER_MANUAL,
    SONIC_ANALYZER_CURRENT_VERSION,
    SONIC_ANALYZER_DESCRIPTOR_LEGACY_VERSION,
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
    PlaylistGenerationRecipeRecord,
    PlaylistGenerationRunRecord,
    SonicFeatureSummaryRecord,
    SonicTrackFeatureRecord,
    generated_playlist_tracks_table,
    generated_playlists_table,
    playlist_generation_recipes_table,
    playlist_generation_runs_table,
    sonic_track_features_table,
)
from app.streaming.models import playlist_membership_table, streaming_playlists_table


class PlaylistGenerationRunNotFoundError(ValueError):
    pass


class PlaylistGenerationRunActiveError(ValueError):
    pass


class GeneratedPlaylistNotFoundError(ValueError):
    pass


class PlaylistGenerationRecipeNotFoundError(ValueError):
    pass


class PlaylistGenerationRecipeNameConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SonicReadyTrack:
    local_track_id: int
    descriptors: dict[str, Any]
    vector: list[float]
    album: str | None = None
    artist: str | None = None
    tag_values: tuple[str, ...] = ()
    title: str | None = None
    analyzer_version: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimedSonicFeatureAttempt:
    local_track_id: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class SonicGenerationPreviewRecord:
    analyzer_key: str
    analyzer_version: str
    can_generate: bool
    failed_feature_count: int
    feature_profile: str
    current_feature_count: int
    legacy_descriptor_feature_count: int
    missing_feature_count: int
    pending_feature_count: int
    ready_track_count: int
    skipped_track_count: int
    source_track_count: int


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
        def status_case(status: str) -> object:
            return case(
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
            existing = (
                connection.execute(
                    select(sonic_track_features_table).where(
                        sonic_track_features_table.c.local_track_id == local_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
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
                        attempt_count=1,
                        updated_at=now,
                    )
                )
                feature_id = result.inserted_primary_key[0]
            else:
                feature_id = existing["id"]
                preserves_legacy_evidence = _is_legacy_upgrade(
                    existing,
                    analyzer_key=analyzer_key,
                    analyzer_version=analyzer_version,
                )
                values: dict[str, Any] = {
                    "status": SONIC_FEATURE_STATUS_PENDING,
                    "failure_detail": None,
                    "attempt_count": sonic_track_features_table.c.attempt_count + 1,
                    "updated_at": now,
                }
                if preserves_legacy_evidence:
                    values["failure_detail"] = _feature_upgrade_pending_marker(
                        analyzer_key=analyzer_key,
                        analyzer_version=analyzer_version,
                    )
                else:
                    values.update(
                        analyzer_key=analyzer_key,
                        analyzer_version=analyzer_version,
                        descriptor_json=None,
                        vector_json=None,
                        extracted_at=None,
                    )
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
            if existing_id is None:
                result = connection.execute(
                    insert(sonic_track_features_table).values(
                        local_track_id=local_track_id,
                        analyzer_key=analyzer_key,
                        analyzer_version=analyzer_version,
                        status=SONIC_FEATURE_STATUS_READY,
                        descriptor_json=descriptors,
                        vector_json=vector,
                        failure_detail=None,
                        extracted_at=now,
                        attempt_count=1,
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
                        status=SONIC_FEATURE_STATUS_READY,
                        descriptor_json=descriptors,
                        vector_json=vector,
                        failure_detail=None,
                        extracted_at=now,
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

    def persist_feature_success_if_current(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        attempt_count: int,
        descriptors: dict[str, Any],
        local_track_id: int,
        vector: list[float],
    ) -> bool:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(sonic_track_features_table)
                .where(
                    sonic_track_features_table.c.local_track_id == local_track_id,
                    sonic_track_features_table.c.status == SONIC_FEATURE_STATUS_PENDING,
                    sonic_track_features_table.c.attempt_count == attempt_count,
                )
                .values(
                    analyzer_key=analyzer_key,
                    analyzer_version=analyzer_version,
                    status=SONIC_FEATURE_STATUS_READY,
                    descriptor_json=descriptors,
                    vector_json=vector,
                    failure_detail=None,
                    extracted_at=now,
                    updated_at=now,
                )
            )
        return result.rowcount == 1

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
                        attempt_count=1,
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

    def persist_feature_failure_if_current(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        attempt_count: int,
        failure_detail: str,
        local_track_id: int,
    ) -> bool:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(sonic_track_features_table).where(
                        sonic_track_features_table.c.local_track_id == local_track_id,
                        sonic_track_features_table.c.status
                        == SONIC_FEATURE_STATUS_PENDING,
                        sonic_track_features_table.c.attempt_count == attempt_count,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                return False
            values = _feature_failure_values(
                existing,
                analyzer_key=analyzer_key,
                analyzer_version=analyzer_version,
                failure_detail=failure_detail,
                now=now,
            )
            connection.execute(
                update(sonic_track_features_table)
                .where(sonic_track_features_table.c.id == existing["id"])
                .values(**values)
            )
        return True

    def mark_feature_failed_if_pending(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        failure_detail: str,
        local_track_id: int,
        attempt_count: int | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(
                        sonic_track_features_table.c.id,
                        sonic_track_features_table.c.analyzer_key,
                        sonic_track_features_table.c.analyzer_version,
                        sonic_track_features_table.c.status,
                        sonic_track_features_table.c.descriptor_json,
                        sonic_track_features_table.c.vector_json,
                        sonic_track_features_table.c.failure_detail,
                        sonic_track_features_table.c.attempt_count,
                    ).where(
                        sonic_track_features_table.c.local_track_id == local_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                values = {
                    "analyzer_key": analyzer_key,
                    "analyzer_version": analyzer_version,
                    "status": SONIC_FEATURE_STATUS_FAILED,
                    "failure_detail": failure_detail,
                    "updated_at": now,
                }
                connection.execute(
                    insert(sonic_track_features_table).values(
                        local_track_id=local_track_id,
                        descriptor_json=None,
                        vector_json=None,
                        extracted_at=None,
                        attempt_count=1,
                        **values,
                    )
                )
                return True

            if existing["status"] != SONIC_FEATURE_STATUS_PENDING:
                return False
            if attempt_count is not None and existing["attempt_count"] != attempt_count:
                return False

            values = _feature_failure_values(
                existing,
                analyzer_key=analyzer_key,
                analyzer_version=analyzer_version,
                failure_detail=failure_detail,
                now=now,
            )
            connection.execute(
                update(sonic_track_features_table)
                .where(sonic_track_features_table.c.id == existing["id"])
                .values(**values)
            )
            return True

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

    def claim_missing_feature_attempts(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        limit: int = 100,
        max_attempts: int,
        pending_stale_before: datetime | None = None,
    ) -> list[ClaimedSonicFeatureAttempt]:
        now = datetime.now(UTC)
        retryable_feature = sonic_track_features_table.c.attempt_count < max_attempts
        outdated_feature = or_(
            sonic_track_features_table.c.analyzer_key != analyzer_key,
            sonic_track_features_table.c.analyzer_version != analyzer_version,
        )
        upgrade_failure_prefix = _feature_upgrade_failure_prefix(
            analyzer_key=analyzer_key,
            analyzer_version=analyzer_version,
        )
        previous_upgrade_failed = (
            sonic_track_features_table.c.failure_detail.startswith(
                upgrade_failure_prefix
            )
        )
        first_upgrade_attempt = and_(
            outdated_feature,
            sonic_track_features_table.c.status != SONIC_FEATURE_STATUS_PENDING,
            or_(
                sonic_track_features_table.c.failure_detail.is_(None),
                ~previous_upgrade_failed,
            ),
        )
        retry_upgrade_after = [
            outdated_feature,
            sonic_track_features_table.c.status == SONIC_FEATURE_STATUS_READY,
            previous_upgrade_failed,
            retryable_feature,
        ]
        if pending_stale_before is not None:
            retry_upgrade_after.append(
                sonic_track_features_table.c.updated_at < pending_stale_before
            )
        retryable_statuses = [
            first_upgrade_attempt,
            and_(*retry_upgrade_after),
            and_(
                ~outdated_feature,
                sonic_track_features_table.c.status == SONIC_FEATURE_STATUS_FAILED,
                retryable_feature,
            ),
        ]
        if pending_stale_before is not None:
            retryable_statuses.append(
                and_(
                    sonic_track_features_table.c.status == SONIC_FEATURE_STATUS_PENDING,
                    sonic_track_features_table.c.updated_at < pending_stale_before,
                    retryable_feature,
                )
            )
        query = (
            select(
                local_tracks_table.c.id.label("local_track_id"),
                sonic_track_features_table.c.id.label("feature_id"),
                sonic_track_features_table.c.analyzer_key,
                sonic_track_features_table.c.analyzer_version,
                sonic_track_features_table.c.attempt_count,
                sonic_track_features_table.c.descriptor_json,
                sonic_track_features_table.c.vector_json,
                sonic_track_features_table.c.status,
                sonic_track_features_table.c.failure_detail,
                outdated_feature.label("is_outdated"),
            )
            .select_from(
                local_tracks_table.outerjoin(
                    sonic_track_features_table,
                    sonic_track_features_table.c.local_track_id
                    == local_tracks_table.c.id,
                )
            )
            .where(
                or_(
                    sonic_track_features_table.c.id.is_(None),
                    *retryable_statuses,
                )
            )
            .order_by(local_tracks_table.c.id.asc())
            .limit(limit)
            .with_for_update(of=local_tracks_table, skip_locked=True)
        )
        claimed_attempts: list[ClaimedSonicFeatureAttempt] = []
        with self._engine.begin() as connection:
            rows = connection.execute(query).mappings().all()
            for row in rows:
                local_track_id = int(row["local_track_id"])
                feature_id = row["feature_id"]
                values: dict[str, Any] = {
                    "status": SONIC_FEATURE_STATUS_PENDING,
                    "failure_detail": None,
                    "updated_at": now,
                }
                preserves_legacy_evidence = bool(
                    feature_id is not None
                    and _is_legacy_upgrade(
                        row,
                        analyzer_key=analyzer_key,
                        analyzer_version=analyzer_version,
                    )
                )
                is_upgrade_retry = bool(
                    preserves_legacy_evidence
                    and (
                        row["status"] == SONIC_FEATURE_STATUS_PENDING
                        or (
                            isinstance(row["failure_detail"], str)
                            and row["failure_detail"].startswith(upgrade_failure_prefix)
                        )
                    )
                )
                attempt_count = 1
                if feature_id is not None and (
                    not row["is_outdated"] or is_upgrade_retry
                ):
                    attempt_count = int(row["attempt_count"]) + 1
                values["attempt_count"] = attempt_count
                if feature_id is None:
                    connection.execute(
                        insert(sonic_track_features_table).values(
                            local_track_id=local_track_id,
                            analyzer_key=analyzer_key,
                            analyzer_version=analyzer_version,
                            descriptor_json=None,
                            vector_json=None,
                            extracted_at=None,
                            **values,
                        )
                    )
                else:
                    if preserves_legacy_evidence:
                        values["failure_detail"] = _feature_upgrade_pending_marker(
                            analyzer_key=analyzer_key,
                            analyzer_version=analyzer_version,
                        )
                    else:
                        values.update(
                            analyzer_key=analyzer_key,
                            analyzer_version=analyzer_version,
                            descriptor_json=None,
                            vector_json=None,
                            extracted_at=None,
                        )
                    connection.execute(
                        update(sonic_track_features_table)
                        .where(sonic_track_features_table.c.id == feature_id)
                        .values(**values)
                    )
                claimed_attempts.append(
                    ClaimedSonicFeatureAttempt(
                        local_track_id=local_track_id,
                        attempt_count=attempt_count,
                    )
                )

        return claimed_attempts

    def claim_missing_feature_track_ids(
        self,
        *,
        analyzer_key: str,
        analyzer_version: str,
        limit: int = 100,
        max_attempts: int,
        pending_stale_before: datetime | None = None,
    ) -> list[int]:
        return [
            attempt.local_track_id
            for attempt in self.claim_missing_feature_attempts(
                analyzer_key=analyzer_key,
                analyzer_version=analyzer_version,
                limit=limit,
                max_attempts=max_attempts,
                pending_stale_before=pending_stale_before,
            )
        ]

    def ready_tracks_for_source(
        self,
        source_filter: dict[str, Any],
        *,
        analyzer_key: str | None = None,
        analyzer_version: str | None = None,
    ) -> list[SonicReadyTrack]:
        with self._engine.connect() as connection:
            local_track_ids = _resolve_source_track_ids(connection, source_filter)
            if not local_track_ids:
                return []

            rows = (
                connection.execute(
                    select(
                        sonic_track_features_table.c.local_track_id,
                        sonic_track_features_table.c.analyzer_key,
                        sonic_track_features_table.c.analyzer_version,
                        sonic_track_features_table.c.status,
                        sonic_track_features_table.c.descriptor_json,
                        sonic_track_features_table.c.vector_json,
                        sonic_track_features_table.c.failure_detail,
                    )
                    .where(
                        sonic_track_features_table.c.local_track_id.in_(
                            sorted(local_track_ids)
                        ),
                        or_(
                            sonic_track_features_table.c.status
                            == SONIC_FEATURE_STATUS_READY,
                            and_(
                                sonic_track_features_table.c.status
                                == SONIC_FEATURE_STATUS_PENDING,
                                sonic_track_features_table.c.analyzer_version
                                == SONIC_ANALYZER_DESCRIPTOR_LEGACY_VERSION,
                            ),
                        ),
                        sonic_track_features_table.c.vector_json.is_not(None),
                    )
                    .order_by(sonic_track_features_table.c.local_track_id.asc())
                )
                .mappings()
                .all()
            )
            metadata_by_id = _track_metadata_for_local_tracks(
                connection,
                {int(row["local_track_id"]) for row in rows},
            )

        return [
            SonicReadyTrack(
                local_track_id=int(row["local_track_id"]),
                descriptors=dict(row["descriptor_json"] or {}),
                vector=[float(value) for value in row["vector_json"]],
                album=metadata_by_id.get(int(row["local_track_id"]), {}).get("album"),
                artist=metadata_by_id.get(int(row["local_track_id"]), {}).get("artist"),
                tag_values=tuple(
                    metadata_by_id.get(int(row["local_track_id"]), {}).get(
                        "tag_values",
                        (),
                    )
                ),
                title=metadata_by_id.get(int(row["local_track_id"]), {}).get("title"),
                analyzer_version=str(row["analyzer_version"]),
            )
            for row in rows
            if isinstance(row["vector_json"], list)
            and _feature_is_compatible(
                row,
                analyzer_key=analyzer_key,
                analyzer_version=analyzer_version,
            )
            and (
                row["status"] == SONIC_FEATURE_STATUS_READY
                or _is_active_legacy_upgrade(
                    row,
                    analyzer_key=analyzer_key or str(row["analyzer_key"]),
                    analyzer_version=analyzer_version or str(row["analyzer_version"]),
                )
            )
        ]

    def generation_preview(
        self,
        source_filter: dict[str, Any],
        *,
        analyzer_key: str,
        analyzer_version: str,
        feature_profile: str,
    ) -> SonicGenerationPreviewRecord:
        with self._engine.connect() as connection:
            local_track_ids = _resolve_source_track_ids(connection, source_filter)
            source_track_count = len(local_track_ids)
            if not local_track_ids:
                return SonicGenerationPreviewRecord(
                    analyzer_key=analyzer_key,
                    analyzer_version=analyzer_version,
                    can_generate=False,
                    failed_feature_count=0,
                    feature_profile=feature_profile,
                    current_feature_count=0,
                    legacy_descriptor_feature_count=0,
                    missing_feature_count=0,
                    pending_feature_count=0,
                    ready_track_count=0,
                    skipped_track_count=0,
                    source_track_count=0,
                )

            rows = (
                connection.execute(
                    select(
                        sonic_track_features_table.c.local_track_id,
                        sonic_track_features_table.c.analyzer_key,
                        sonic_track_features_table.c.analyzer_version,
                        sonic_track_features_table.c.status,
                        sonic_track_features_table.c.descriptor_json,
                        sonic_track_features_table.c.vector_json,
                        sonic_track_features_table.c.failure_detail,
                    )
                    .where(
                        sonic_track_features_table.c.local_track_id.in_(
                            sorted(local_track_ids)
                        )
                    )
                    .order_by(sonic_track_features_table.c.local_track_id.asc())
                )
                .mappings()
                .all()
            )

        rows_by_track_id = {int(row["local_track_id"]): row for row in rows}
        ready_track_count = 0
        current_feature_count = 0
        legacy_descriptor_feature_count = 0
        pending_feature_count = 0
        failed_feature_count = 0
        for local_track_id in local_track_ids:
            row = rows_by_track_id.get(local_track_id)
            if row is None:
                continue
            status = row["status"]
            usable_legacy_upgrade = (
                status == SONIC_FEATURE_STATUS_PENDING
                and isinstance(row["vector_json"], list)
                and _is_active_legacy_upgrade(
                    row,
                    analyzer_key=analyzer_key,
                    analyzer_version=analyzer_version,
                )
            )
            if (status == SONIC_FEATURE_STATUS_READY or usable_legacy_upgrade) and (
                _feature_is_compatible(
                    row,
                    analyzer_key=analyzer_key,
                    analyzer_version=analyzer_version,
                )
                and isinstance(row["vector_json"], list)
            ):
                ready_track_count += 1
                if str(row["analyzer_version"]) == analyzer_version:
                    current_feature_count += 1
                elif (
                    str(row["analyzer_version"])
                    == SONIC_ANALYZER_DESCRIPTOR_LEGACY_VERSION
                ):
                    legacy_descriptor_feature_count += 1
            if status == SONIC_FEATURE_STATUS_PENDING:
                pending_feature_count += 1
            elif status == SONIC_FEATURE_STATUS_FAILED:
                failed_feature_count += 1

        missing_feature_count = source_track_count - len(rows_by_track_id)
        skipped_track_count = source_track_count - ready_track_count
        return SonicGenerationPreviewRecord(
            analyzer_key=analyzer_key,
            analyzer_version=analyzer_version,
            can_generate=ready_track_count > 0,
            failed_feature_count=failed_feature_count,
            feature_profile=feature_profile,
            current_feature_count=current_feature_count,
            legacy_descriptor_feature_count=legacy_descriptor_feature_count,
            missing_feature_count=missing_feature_count,
            pending_feature_count=pending_feature_count,
            ready_track_count=ready_track_count,
            skipped_track_count=skipped_track_count,
            source_track_count=source_track_count,
        )

    def create_generation_run(
        self,
        *,
        analyzer_evidence: dict[str, Any] | None = None,
        generation_config: dict[str, Any],
        readiness_summary: dict[str, Any] | None = None,
        recipe_id: int | None = None,
        run_name: str = "Generated crates",
        source_filter: dict[str, Any],
        trigger: str = PLAYLIST_GENERATION_TRIGGER_MANUAL,
    ) -> PlaylistGenerationRunRecord:
        with self._engine.begin() as connection:
            result = connection.execute(
                insert(playlist_generation_runs_table).values(
                    status=PLAYLIST_GENERATION_STATUS_PENDING,
                    source_filter_json=source_filter,
                    generation_config_json=generation_config,
                    recipe_id=recipe_id,
                    run_name=run_name,
                    trigger=trigger,
                    readiness_summary_json=readiness_summary,
                    analyzer_evidence_json=analyzer_evidence,
                    playlist_count=0,
                    track_count=0,
                )
            )
            run_id = result.inserted_primary_key[0]

        run = self.get_generation_run(run_id)
        if run is None:
            raise PlaylistGenerationRunNotFoundError(str(run_id))
        return run

    def create_generation_recipe(
        self,
        *,
        enabled: bool,
        export_config: dict[str, Any] | None,
        generation_config: dict[str, Any],
        name: str,
        regenerate_on_change: bool,
        source_filter: dict[str, Any],
    ) -> PlaylistGenerationRecipeRecord:
        from app.autopilot.exports import validate_recipe_export_config

        validated_export_config = validate_recipe_export_config(
            engine=self._engine,
            raw=export_config,
        )
        now = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                result = connection.execute(
                    insert(playlist_generation_recipes_table).values(
                        name=name,
                        source_filter_json=source_filter,
                        generation_config_json=generation_config,
                        enabled=enabled,
                        regenerate_on_change=regenerate_on_change,
                        export_config_json=validated_export_config,
                        updated_at=now,
                    )
                )
                recipe_id = int(result.inserted_primary_key[0])
        except IntegrityError as exc:
            raise PlaylistGenerationRecipeNameConflictError(name) from exc
        recipe = self.get_generation_recipe(recipe_id)
        if recipe is None:
            raise PlaylistGenerationRecipeNotFoundError(str(recipe_id))
        return recipe

    def list_generation_recipes(
        self,
        *,
        enabled_only: bool = False,
    ) -> list[PlaylistGenerationRecipeRecord]:
        query = select(playlist_generation_recipes_table)
        if enabled_only:
            query = query.where(playlist_generation_recipes_table.c.enabled.is_(True))
        query = query.order_by(
            playlist_generation_recipes_table.c.name.asc(),
            playlist_generation_recipes_table.c.id.asc(),
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [_recipe_record(row) for row in rows]

    def get_generation_recipe(
        self,
        recipe_id: int,
    ) -> PlaylistGenerationRecipeRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(playlist_generation_recipes_table).where(
                        playlist_generation_recipes_table.c.id == recipe_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _recipe_record(row) if row is not None else None

    def update_generation_recipe(
        self,
        recipe_id: int,
        *,
        enabled: bool,
        export_config: dict[str, Any] | None,
        generation_config: dict[str, Any],
        name: str,
        regenerate_on_change: bool,
        source_filter: dict[str, Any],
    ) -> PlaylistGenerationRecipeRecord:
        from app.autopilot.exports import validate_recipe_export_config

        validated_export_config = validate_recipe_export_config(
            engine=self._engine,
            raw=export_config,
        )
        try:
            with self._engine.begin() as connection:
                result = connection.execute(
                    update(playlist_generation_recipes_table)
                    .where(playlist_generation_recipes_table.c.id == recipe_id)
                    .values(
                        name=name,
                        source_filter_json=source_filter,
                        generation_config_json=generation_config,
                        enabled=enabled,
                        regenerate_on_change=regenerate_on_change,
                        export_config_json=validated_export_config,
                        updated_at=datetime.now(UTC),
                    )
                )
        except IntegrityError as exc:
            raise PlaylistGenerationRecipeNameConflictError(name) from exc
        if result.rowcount == 0:
            raise PlaylistGenerationRecipeNotFoundError(str(recipe_id))
        recipe = self.get_generation_recipe(recipe_id)
        if recipe is None:
            raise PlaylistGenerationRecipeNotFoundError(str(recipe_id))
        return recipe

    def delete_generation_recipe(self, recipe_id: int) -> None:
        with self._engine.begin() as connection:
            recipe_exists = connection.execute(
                select(playlist_generation_recipes_table.c.id).where(
                    playlist_generation_recipes_table.c.id == recipe_id
                )
            ).scalar_one_or_none()
            if recipe_exists is None:
                raise PlaylistGenerationRecipeNotFoundError(str(recipe_id))

            now = datetime.now(UTC)
            inspector = sqlalchemy_inspect(connection)
            if inspector.has_table(
                autopilot_run_items_table.name
            ) and inspector.has_table(autopilot_runs_table.name):
                pending_rows = (
                    connection.execute(
                        select(
                            autopilot_run_items_table.c.id,
                            autopilot_run_items_table.c.run_id,
                        ).where(
                            autopilot_run_items_table.c.action == "regenerate_recipe",
                            autopilot_run_items_table.c.recipe_id == recipe_id,
                            autopilot_run_items_table.c.status
                            == AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
                        )
                    )
                    .mappings()
                    .all()
                )
                if pending_rows:
                    pending_ids = [row["id"] for row in pending_rows]
                    connection.execute(
                        update(autopilot_run_items_table)
                        .where(autopilot_run_items_table.c.id.in_(pending_ids))
                        .values(
                            status="skipped",
                            recipe_id=None,
                            next_attempt_at=None,
                            reason_code="recipe_deleted",
                            detail=(
                                "Cancelled pending regeneration because its saved "
                                "recipe was deleted"
                            ),
                            completed_at=now,
                            updated_at=now,
                        )
                    )
                    _finish_autopilot_runs_in_transaction(
                        connection,
                        {str(row["run_id"]) for row in pending_rows},
                        now=now,
                    )

            connection.execute(
                update(playlist_generation_runs_table)
                .where(playlist_generation_runs_table.c.recipe_id == recipe_id)
                .values(recipe_id=None)
            )
            result = connection.execute(
                delete(playlist_generation_recipes_table).where(
                    playlist_generation_recipes_table.c.id == recipe_id
                )
            )
            if result.rowcount == 0:
                raise PlaylistGenerationRecipeNotFoundError(str(recipe_id))

    def mark_generation_recipe_regenerated(
        self,
        recipe_id: int,
        *,
        run_id: int,
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(playlist_generation_recipes_table)
                .where(playlist_generation_recipes_table.c.id == recipe_id)
                .values(
                    last_run_id=run_id,
                    last_regenerated_at=now,
                    updated_at=now,
                )
            )
        if result.rowcount == 0:
            raise PlaylistGenerationRecipeNotFoundError(str(recipe_id))

    def list_generation_runs(
        self, *, limit: int = 50
    ) -> list[PlaylistGenerationRunRecord]:
        numbered_runs = _numbered_generation_runs_query()
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(numbered_runs)
                    .order_by(
                        numbered_runs.c.created_at.desc(),
                        numbered_runs.c.id.desc(),
                    )
                    .limit(limit)
                )
                .mappings()
                .all()
            )

        return [_run_record(row) for row in rows]

    def get_generation_run(self, run_id: int) -> PlaylistGenerationRunRecord | None:
        numbered_runs = _numbered_generation_runs_query()
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(numbered_runs).where(numbered_runs.c.id == run_id)
                )
                .mappings()
                .one_or_none()
            )

        return _run_record(row) if row is not None else None

    def delete_generation_run(self, run_id: int) -> None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        playlist_generation_runs_table.c.id,
                        playlist_generation_runs_table.c.status,
                    ).where(playlist_generation_runs_table.c.id == run_id)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PlaylistGenerationRunNotFoundError(str(run_id))

            if row["status"] in (
                PLAYLIST_GENERATION_STATUS_PENDING,
                PLAYLIST_GENERATION_STATUS_RUNNING,
            ):
                raise PlaylistGenerationRunActiveError(str(run_id))

            generated_playlist_ids = select(generated_playlists_table.c.id).where(
                generated_playlists_table.c.run_id == run_id
            )
            connection.execute(
                delete(generated_playlist_tracks_table).where(
                    generated_playlist_tracks_table.c.generated_playlist_id.in_(
                        generated_playlist_ids
                    )
                )
            )
            connection.execute(
                delete(generated_playlists_table).where(
                    generated_playlists_table.c.run_id == run_id
                )
            )
            connection.execute(
                update(playlist_generation_recipes_table)
                .where(playlist_generation_recipes_table.c.last_run_id == run_id)
                .values(last_run_id=None, updated_at=datetime.now(UTC))
            )
            result = connection.execute(
                delete(playlist_generation_runs_table).where(
                    playlist_generation_runs_table.c.id == run_id
                )
            )
            if result.rowcount == 0:
                raise PlaylistGenerationRunNotFoundError(str(run_id))

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

    def update_generation_run_evidence(
        self,
        run_id: int,
        *,
        analyzer_evidence: dict[str, Any],
        readiness_summary: dict[str, Any],
    ) -> None:
        self._update_run(
            run_id,
            analyzer_evidence_json=analyzer_evidence,
            readiness_summary_json=readiness_summary,
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


def _finish_autopilot_runs_in_transaction(
    connection: Connection,
    run_ids: set[str],
    *,
    now: datetime,
) -> None:
    for run_id in run_ids:
        statuses = (
            connection.execute(
                select(autopilot_run_items_table.c.status).where(
                    autopilot_run_items_table.c.run_id == run_id
                )
            )
            .scalars()
            .all()
        )
        failed = sum(status == AUTOPILOT_ITEM_STATUS_FAILED for status in statuses)
        review = sum(status == AUTOPILOT_ITEM_STATUS_REVIEW for status in statuses)
        waiting = sum(status == AUTOPILOT_ITEM_STATUS_RETRY_WAIT for status in statuses)
        connection.execute(
            update(autopilot_runs_table)
            .where(autopilot_runs_table.c.id == run_id)
            .values(
                status=(
                    AUTOPILOT_RUN_STATUS_PARTIAL
                    if failed or review or waiting
                    else AUTOPILOT_RUN_STATUS_SUCCEEDED
                ),
                failed_items=failed,
                review_items=review,
                finished_at=now,
                updated_at=now,
            )
        )


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
        track_ids = {
            int(track_id)
            for track_id in connection.execute(
                select(local_tracks_table.c.id).order_by(local_tracks_table.c.id.asc())
            ).scalars()
        }

    for tag_filter in source_filter.get("tag_filters", []):
        track_ids &= _local_track_ids_for_tag_filter(connection, track_ids, tag_filter)

    return track_ids


def _feature_is_compatible(
    row: Any,
    *,
    analyzer_key: str | None,
    analyzer_version: str | None,
) -> bool:
    if analyzer_key is not None and row["analyzer_key"] != analyzer_key:
        return False
    return not (
        analyzer_version is not None
        and row["analyzer_version"] != analyzer_version
        and not (
            analyzer_version == SONIC_ANALYZER_CURRENT_VERSION
            and row["analyzer_version"] == SONIC_ANALYZER_DESCRIPTOR_LEGACY_VERSION
        )
    )


def _is_legacy_upgrade(
    row: Any,
    *,
    analyzer_key: str,
    analyzer_version: str,
) -> bool:
    return bool(
        analyzer_version == SONIC_ANALYZER_CURRENT_VERSION
        and row["analyzer_key"] == analyzer_key
        and row["analyzer_version"] == SONIC_ANALYZER_DESCRIPTOR_LEGACY_VERSION
        and row["status"] in (SONIC_FEATURE_STATUS_READY, SONIC_FEATURE_STATUS_PENDING)
        and isinstance(row["descriptor_json"], dict)
        and isinstance(row["vector_json"], list)
    )


def _feature_upgrade_failure_prefix(
    *,
    analyzer_key: str,
    analyzer_version: str,
) -> str:
    return f"Upgrade to {analyzer_key}@{analyzer_version} failed:"


def _feature_upgrade_pending_marker(
    *,
    analyzer_key: str,
    analyzer_version: str,
) -> str:
    return f"Upgrade to {analyzer_key}@{analyzer_version} pending"


def _is_active_legacy_upgrade(
    row: Any,
    *,
    analyzer_key: str,
    analyzer_version: str,
) -> bool:
    return bool(
        _is_legacy_upgrade(
            row,
            analyzer_key=analyzer_key,
            analyzer_version=analyzer_version,
        )
        and row["failure_detail"]
        == _feature_upgrade_pending_marker(
            analyzer_key=analyzer_key,
            analyzer_version=analyzer_version,
        )
    )


def _feature_failure_values(
    existing: Any,
    *,
    analyzer_key: str,
    analyzer_version: str,
    failure_detail: str,
    now: datetime,
) -> dict[str, Any]:
    if _is_active_legacy_upgrade(
        existing,
        analyzer_key=analyzer_key,
        analyzer_version=analyzer_version,
    ):
        prefix = _feature_upgrade_failure_prefix(
            analyzer_key=analyzer_key,
            analyzer_version=analyzer_version,
        )
        return {
            "status": SONIC_FEATURE_STATUS_READY,
            "failure_detail": f"{prefix} {failure_detail}",
            "updated_at": now,
        }
    return {
        "analyzer_key": analyzer_key,
        "analyzer_version": analyzer_version,
        "status": SONIC_FEATURE_STATUS_FAILED,
        "failure_detail": failure_detail,
        "updated_at": now,
    }


def _track_metadata_for_local_tracks(
    connection: Connection,
    local_track_ids: set[int],
) -> dict[int, dict[str, Any]]:
    if not local_track_ids:
        return {}

    rows = (
        connection.execute(
            select(
                local_tracks_table.c.id,
                local_tracks_table.c.beets_id,
                beets_items_table.c.title,
                beets_items_table.c.artist,
                beets_items_table.c.album,
            )
            .select_from(
                local_tracks_table.outerjoin(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
            )
            .where(local_tracks_table.c.id.in_(sorted(local_track_ids)))
        )
        .mappings()
        .all()
    )
    metadata_by_id = {
        int(row["id"]): {
            "album": row["album"],
            "artist": row["artist"],
            "beets_id": row["beets_id"],
            "tag_values": (),
            "title": row["title"],
        }
        for row in rows
    }

    beets_ids_by_track_id = {
        int(row["id"]): int(row["beets_id"])
        for row in rows
        if row["beets_id"] is not None
    }
    if not beets_ids_by_track_id:
        return metadata_by_id

    tag_rows = (
        connection.execute(
            select(
                local_tracks_table.c.id.label("local_track_id"),
                beets_item_attributes_table.c.value,
            )
            .select_from(
                local_tracks_table.join(
                    beets_item_attributes_table,
                    beets_item_attributes_table.c.entity_id
                    == local_tracks_table.c.beets_id,
                )
            )
            .where(
                local_tracks_table.c.id.in_(sorted(beets_ids_by_track_id.keys())),
                func.lower(beets_item_attributes_table.c.key).in_(
                    ("genre", "genres", "style", "styles")
                ),
                beets_item_attributes_table.c.value.is_not(None),
            )
            .order_by(local_tracks_table.c.id.asc(), beets_item_attributes_table.c.key)
        )
        .mappings()
        .all()
    )
    tag_values_by_track_id: dict[int, list[str]] = defaultdict(list)
    for row in tag_rows:
        tag_values_by_track_id[int(row["local_track_id"])].append(str(row["value"]))

    for local_track_id, tag_values in tag_values_by_track_id.items():
        metadata_by_id.setdefault(local_track_id, {})["tag_values"] = tuple(tag_values)

    return metadata_by_id


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
        attempt_count=int(row["attempt_count"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _numbered_generation_runs_query():
    generation_number = func.row_number().over(
        order_by=(
            playlist_generation_runs_table.c.created_at.asc(),
            playlist_generation_runs_table.c.id.asc(),
        )
    )
    return select(
        playlist_generation_runs_table.c.id,
        playlist_generation_runs_table.c.status,
        playlist_generation_runs_table.c.source_filter_json,
        playlist_generation_runs_table.c.generation_config_json,
        playlist_generation_runs_table.c.recipe_id,
        playlist_generation_runs_table.c.run_name,
        playlist_generation_runs_table.c.trigger,
        playlist_generation_runs_table.c.readiness_summary_json,
        playlist_generation_runs_table.c.analyzer_evidence_json,
        playlist_generation_runs_table.c.playlist_count,
        playlist_generation_runs_table.c.track_count,
        playlist_generation_runs_table.c.error_detail,
        playlist_generation_runs_table.c.completed_at,
        playlist_generation_runs_table.c.created_at,
        playlist_generation_runs_table.c.updated_at,
        generation_number.label("generation_number"),
    ).subquery()


def _run_record(row: Any) -> PlaylistGenerationRunRecord:
    return PlaylistGenerationRunRecord(
        id=row["id"],
        generation_number=int(row["generation_number"]),
        status=row["status"],
        source_filter_json=dict(row["source_filter_json"] or {}),
        generation_config_json=dict(row["generation_config_json"] or {}),
        recipe_id=row["recipe_id"],
        run_name=row["run_name"],
        trigger=row["trigger"],
        readiness_summary_json=(
            dict(row["readiness_summary_json"])
            if isinstance(row["readiness_summary_json"], dict)
            else None
        ),
        analyzer_evidence_json=(
            dict(row["analyzer_evidence_json"])
            if isinstance(row["analyzer_evidence_json"], dict)
            else None
        ),
        playlist_count=row["playlist_count"],
        track_count=row["track_count"],
        error_detail=row["error_detail"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _recipe_record(row: Any) -> PlaylistGenerationRecipeRecord:
    return PlaylistGenerationRecipeRecord(
        id=int(row["id"]),
        name=str(row["name"]),
        source_filter_json=dict(row["source_filter_json"] or {}),
        generation_config_json=dict(row["generation_config_json"] or {}),
        enabled=bool(row["enabled"]),
        regenerate_on_change=bool(row["regenerate_on_change"]),
        export_config_json=(
            dict(row["export_config_json"])
            if isinstance(row["export_config_json"], dict)
            else None
        ),
        last_run_id=(
            int(row["last_run_id"]) if row["last_run_id"] is not None else None
        ),
        last_regenerated_at=row["last_regenerated_at"],
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
