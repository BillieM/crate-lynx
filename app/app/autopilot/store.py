from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from app.autopilot.models import (
    AUTOPILOT_ITEM_STATUS_FAILED,
    AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
    AUTOPILOT_ITEM_STATUSES,
    AUTOPILOT_RUN_STATUS_PLANNING,
    AUTOPILOT_RUN_STATUSES,
    AUTOPILOT_SETTINGS_ID,
    AUTOPILOT_TRIGGERS,
    DEFAULT_MAX_CONCURRENT_DOWNLOADS,
    DEFAULT_MAX_DOWNLOADS_PER_RUN,
    DEFAULT_MAX_SEARCHES_PER_RUN,
    DEFAULT_MAX_STORAGE_BYTES_PER_RUN,
    DEFAULT_QUIET_PERIOD_SECONDS,
    DEFAULT_RETRY_BASE_SECONDS,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_MAX_SECONDS,
    DEFAULT_SCHEDULE_MINUTES,
    AutopilotRunItemRecord,
    AutopilotRunRecord,
    AutopilotSettingsRecord,
    autopilot_run_items_table,
    autopilot_runs_table,
    autopilot_settings_table,
)
from app.core.db import create_database_engine

RUN_COUNT_FIELDS = frozenset(
    {
        "refreshed_playlists",
        "searched_tracks",
        "queued_downloads",
        "downloaded_tracks",
        "ingested_tracks",
        "analyzed_tracks",
        "regenerated_recipes",
        "refreshed_exports",
        "review_items",
        "failed_items",
    }
)


def bounded_retry_delay_seconds(
    *,
    attempt_count: int,
    base_seconds: int,
    max_seconds: int,
) -> int:
    """Return a capped exponential delay for a one-based failed attempt."""
    exponent = max(0, attempt_count - 1)
    return min(max_seconds, base_seconds * (2**exponent))


def _conflict_insert(target_table: Any, dialect_name: str) -> Any:
    if dialect_name == "postgresql":
        return postgresql_insert(target_table)
    if dialect_name == "sqlite":
        return sqlite_insert(target_table)
    raise ValueError(f"Unsupported database dialect: {dialect_name}")


class AutopilotStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    @property
    def engine(self) -> Engine:
        return self._engine

    def get_settings(self) -> AutopilotSettingsRecord:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            statement = _conflict_insert(
                autopilot_settings_table, connection.dialect.name
            ).values(
                id=AUTOPILOT_SETTINGS_ID,
                paused=False,
                schedule_minutes=DEFAULT_SCHEDULE_MINUTES,
                quiet_period_seconds=DEFAULT_QUIET_PERIOD_SECONDS,
                max_concurrent_downloads=DEFAULT_MAX_CONCURRENT_DOWNLOADS,
                max_downloads_per_run=DEFAULT_MAX_DOWNLOADS_PER_RUN,
                max_searches_per_run=DEFAULT_MAX_SEARCHES_PER_RUN,
                max_storage_bytes_per_run=DEFAULT_MAX_STORAGE_BYTES_PER_RUN,
                retry_max_attempts=DEFAULT_RETRY_MAX_ATTEMPTS,
                retry_base_seconds=DEFAULT_RETRY_BASE_SECONDS,
                retry_max_seconds=DEFAULT_RETRY_MAX_SECONDS,
                created_at=now,
                updated_at=now,
            )
            connection.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[autopilot_settings_table.c.id]
                )
            )
            row = (
                connection.execute(
                    select(autopilot_settings_table).where(
                        autopilot_settings_table.c.id == AUTOPILOT_SETTINGS_ID
                    )
                )
                .mappings()
                .one()
            )
        return _settings_record(row)

    def update_settings(self, **values: object) -> AutopilotSettingsRecord:
        allowed = {
            "paused",
            "schedule_minutes",
            "quiet_period_seconds",
            "max_concurrent_downloads",
            "max_downloads_per_run",
            "max_searches_per_run",
            "max_storage_bytes_per_run",
            "retry_max_attempts",
            "retry_base_seconds",
            "retry_max_seconds",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported autopilot setting(s): {sorted(unknown)}")

        current = self.get_settings()
        merged = {
            field: values.get(field, getattr(current, field)) for field in allowed
        }
        _validate_settings(merged)
        merged["updated_at"] = datetime.now(UTC)
        with self._engine.begin() as connection:
            connection.execute(
                update(autopilot_settings_table)
                .where(autopilot_settings_table.c.id == AUTOPILOT_SETTINGS_ID)
                .values(**merged)
            )
        return self.get_settings()

    def get_or_create_run(
        self,
        *,
        dry_run: bool,
        idempotency_key: str,
        trigger: str,
        started_at: datetime | None = None,
    ) -> tuple[AutopilotRunRecord, bool]:
        if trigger not in AUTOPILOT_TRIGGERS:
            raise ValueError(f"Unsupported autopilot trigger: {trigger}")
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("Autopilot idempotency key must not be empty")

        now = started_at or datetime.now(UTC)
        run_id = str(uuid.uuid4())
        with self._engine.begin() as connection:
            statement = _conflict_insert(
                autopilot_runs_table, connection.dialect.name
            ).values(
                id=run_id,
                idempotency_key=normalized_key,
                trigger=trigger,
                dry_run=dry_run,
                status=AUTOPILOT_RUN_STATUS_PLANNING,
                started_at=now,
                heartbeat_at=now,
                created_at=now,
                updated_at=now,
            )
            result = connection.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[autopilot_runs_table.c.idempotency_key]
                )
            )
            created = result.rowcount == 1
            row = (
                connection.execute(
                    select(autopilot_runs_table).where(
                        autopilot_runs_table.c.idempotency_key == normalized_key
                    )
                )
                .mappings()
                .one()
            )
        return _run_record(row), created

    def get_run(self, run_id: str) -> AutopilotRunRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(autopilot_runs_table).where(
                        autopilot_runs_table.c.id == run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _run_record(row) if row is not None else None

    def list_runs(self, *, limit: int = 20) -> list[AutopilotRunRecord]:
        bounded_limit = max(1, min(limit, 100))
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(autopilot_runs_table)
                    .order_by(
                        desc(autopilot_runs_table.c.started_at),
                        desc(autopilot_runs_table.c.id),
                    )
                    .limit(bounded_limit)
                )
                .mappings()
                .all()
            )
        return [_run_record(row) for row in rows]

    def list_run_items(
        self,
        run_id: str,
        *,
        statuses: set[str] | frozenset[str] | None = None,
    ) -> list[AutopilotRunItemRecord]:
        query = select(autopilot_run_items_table).where(
            autopilot_run_items_table.c.run_id == run_id
        )
        if statuses:
            unknown = set(statuses) - set(AUTOPILOT_ITEM_STATUSES)
            if unknown:
                raise ValueError(
                    f"Unsupported autopilot item status(es): {sorted(unknown)}"
                )
            query = query.where(autopilot_run_items_table.c.status.in_(statuses))
        query = query.order_by(
            autopilot_run_items_table.c.created_at.asc(),
            autopilot_run_items_table.c.id.asc(),
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [_run_item_record(row) for row in rows]

    def get_run_item(self, item_id: str) -> AutopilotRunItemRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(autopilot_run_items_table).where(
                        autopilot_run_items_table.c.id == item_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _run_item_record(row) if row is not None else None

    def last_completed_search_at(
        self,
        streaming_track_ids: set[int],
    ) -> dict[int, datetime]:
        """Return each track's latest durable attempted-search timestamp.

        Cap-skipped items have no attempts, so they remain ahead of tracks that
        consumed a search slot on an earlier run.
        """
        if not streaming_track_ids:
            return {}
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        autopilot_run_items_table.c.streaming_track_id,
                        func.max(autopilot_run_items_table.c.completed_at).label(
                            "last_completed_at"
                        ),
                    )
                    .where(
                        autopilot_run_items_table.c.action == "search_missing_track",
                        autopilot_run_items_table.c.streaming_track_id.in_(
                            streaming_track_ids
                        ),
                        autopilot_run_items_table.c.attempt_count > 0,
                        autopilot_run_items_table.c.completed_at.is_not(None),
                    )
                    .group_by(autopilot_run_items_table.c.streaming_track_id)
                )
                .mappings()
                .all()
            )
        return {
            int(row["streaming_track_id"]): row["last_completed_at"]
            for row in rows
            if row["streaming_track_id"] is not None
            and row["last_completed_at"] is not None
        }

    def get_or_create_run_item(
        self,
        *,
        action: str,
        idempotency_key: str,
        run_id: str,
        stage: str,
        **evidence: object,
    ) -> tuple[AutopilotRunItemRecord, bool]:
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("Autopilot item idempotency key must not be empty")
        allowed_evidence = {
            "playlist_id",
            "streaming_track_id",
            "acquisition_id",
            "recipe_id",
            "candidate_id",
            "identity_confidence",
            "version_confidence",
            "quality_score",
            "runner_up_margin",
            "expected_duration_ms",
            "candidate_duration_ms",
            "reason_code",
            "detail",
        }
        unknown = set(evidence) - allowed_evidence
        if unknown:
            raise ValueError(f"Unsupported autopilot item evidence: {sorted(unknown)}")
        now = datetime.now(UTC)
        item_id = str(uuid.uuid4())
        with self._engine.begin() as connection:
            statement = _conflict_insert(
                autopilot_run_items_table, connection.dialect.name
            ).values(
                id=item_id,
                run_id=run_id,
                idempotency_key=normalized_key,
                stage=stage,
                action=action,
                created_at=now,
                updated_at=now,
                **evidence,
            )
            result = connection.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[autopilot_run_items_table.c.idempotency_key]
                )
            )
            created = result.rowcount == 1
            row = (
                connection.execute(
                    select(autopilot_run_items_table).where(
                        autopilot_run_items_table.c.idempotency_key == normalized_key
                    )
                )
                .mappings()
                .one()
            )
        return _run_item_record(row), created

    def mark_item_running(self, item_id: str) -> AutopilotRunItemRecord:
        return self._update_item(
            item_id,
            status="running",
            attempt_count=autopilot_run_items_table.c.attempt_count + 1,
            next_attempt_at=None,
            completed_at=None,
        )

    def complete_item(
        self,
        item_id: str,
        *,
        status: str = "succeeded",
        reason_code: str | None = None,
        detail: str | None = None,
        **evidence: object,
    ) -> AutopilotRunItemRecord:
        if status not in {"succeeded", "skipped", "review", "failed"}:
            raise ValueError(f"Unsupported completion status: {status}")
        values = {
            "status": status,
            "reason_code": reason_code,
            "detail": _truncate(detail),
            "next_attempt_at": None,
            "completed_at": datetime.now(UTC),
            **evidence,
        }
        return self._update_item(item_id, **values)

    def fail_item_with_retry(
        self,
        item_id: str,
        *,
        detail: str,
        settings: AutopilotSettingsRecord,
        now: datetime | None = None,
    ) -> AutopilotRunItemRecord:
        item = self.get_run_item(item_id)
        if item is None:
            raise ValueError(f"Autopilot run item not found: {item_id}")
        if item.status != "running":
            item = self.mark_item_running(item_id)
        failure_time = now or datetime.now(UTC)
        if item.attempt_count >= settings.retry_max_attempts:
            return self.complete_item(
                item.id,
                status=AUTOPILOT_ITEM_STATUS_FAILED,
                reason_code="retry_exhausted",
                detail=detail,
            )
        delay = bounded_retry_delay_seconds(
            attempt_count=item.attempt_count,
            base_seconds=settings.retry_base_seconds,
            max_seconds=settings.retry_max_seconds,
        )
        return self._update_item(
            item.id,
            status=AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
            reason_code="retry_scheduled",
            detail=_truncate(detail),
            next_attempt_at=failure_time + timedelta(seconds=delay),
            completed_at=None,
        )

    def defer_item(
        self,
        item_id: str,
        *,
        next_attempt_at: datetime,
        reason_code: str,
        detail: str,
    ) -> AutopilotRunItemRecord:
        return self._update_item(
            item_id,
            status=AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
            reason_code=reason_code,
            detail=_truncate(detail),
            next_attempt_at=next_attempt_at,
            completed_at=None,
        )

    def upsert_recipe_debounce(
        self,
        *,
        run_id: str,
        recipe_id: int,
        next_attempt_at: datetime,
        detail: str,
    ) -> tuple[AutopilotRunItemRecord, bool]:
        """Create or extend the single pending regeneration for a recipe."""
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": 0x43524C000000 + recipe_id},
                )
            rows = (
                connection.execute(
                    select(autopilot_run_items_table)
                    .where(
                        autopilot_run_items_table.c.action == "regenerate_recipe",
                        autopilot_run_items_table.c.recipe_id == recipe_id,
                        autopilot_run_items_table.c.status
                        == AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
                    )
                    .order_by(
                        autopilot_run_items_table.c.created_at.asc(),
                        autopilot_run_items_table.c.id.asc(),
                    )
                    .with_for_update()
                )
                .mappings()
                .all()
            )
            if rows:
                owner = rows[0]
                existing_due_at = owner["next_attempt_at"]
                extended_due_at = (
                    next_attempt_at
                    if existing_due_at is None
                    or _as_utc(existing_due_at) < _as_utc(next_attempt_at)
                    else existing_due_at
                )
                values: dict[str, object] = {
                    "next_attempt_at": extended_due_at,
                    "updated_at": now,
                }
                if int(owner["attempt_count"]) == 0:
                    values.update(
                        reason_code="quiet_period",
                        detail=_truncate(detail),
                    )
                connection.execute(
                    update(autopilot_run_items_table)
                    .where(autopilot_run_items_table.c.id == owner["id"])
                    .values(**values)
                )
                duplicate_ids = [row["id"] for row in rows[1:]]
                if duplicate_ids:
                    connection.execute(
                        update(autopilot_run_items_table)
                        .where(autopilot_run_items_table.c.id.in_(duplicate_ids))
                        .values(
                            status="skipped",
                            reason_code="recipe_debounce_coalesced",
                            detail=(
                                f"Coalesced into pending recipe item {owner['id']}"
                            ),
                            next_attempt_at=None,
                            completed_at=now,
                            updated_at=now,
                        )
                    )
                row = (
                    connection.execute(
                        select(autopilot_run_items_table).where(
                            autopilot_run_items_table.c.id == owner["id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                return _run_item_record(row), False

            item_id = str(uuid.uuid4())
            connection.execute(
                insert(autopilot_run_items_table).values(
                    id=item_id,
                    run_id=run_id,
                    idempotency_key=f"recipe-debounce:{recipe_id}:{item_id}",
                    stage="regenerate",
                    action="regenerate_recipe",
                    status=AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
                    recipe_id=recipe_id,
                    attempt_count=0,
                    next_attempt_at=next_attempt_at,
                    reason_code="quiet_period",
                    detail=_truncate(detail),
                    created_at=now,
                    updated_at=now,
                )
            )
            row = (
                connection.execute(
                    select(autopilot_run_items_table).where(
                        autopilot_run_items_table.c.id == item_id
                    )
                )
                .mappings()
                .one()
            )
        return _run_item_record(row), True

    def due_retry_items(
        self, *, now: datetime | None = None
    ) -> list[AutopilotRunItemRecord]:
        retry_at = now or datetime.now(UTC)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(autopilot_run_items_table)
                    .where(
                        autopilot_run_items_table.c.status
                        == AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
                        autopilot_run_items_table.c.next_attempt_at <= retry_at,
                    )
                    .order_by(
                        autopilot_run_items_table.c.next_attempt_at.asc(),
                        autopilot_run_items_table.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )
        return [_run_item_record(row) for row in rows]

    def pending_retry_item(
        self,
        *,
        action: str,
        playlist_id: int | None = None,
        streaming_track_id: int | None = None,
        exclude_item_id: str | None = None,
    ) -> AutopilotRunItemRecord | None:
        """Return the newest pending retry for one stable operational target."""
        query = select(autopilot_run_items_table).where(
            autopilot_run_items_table.c.action == action,
            autopilot_run_items_table.c.status == AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
        )
        if playlist_id is None:
            query = query.where(autopilot_run_items_table.c.playlist_id.is_(None))
        else:
            query = query.where(autopilot_run_items_table.c.playlist_id == playlist_id)
        if streaming_track_id is None:
            query = query.where(
                autopilot_run_items_table.c.streaming_track_id.is_(None)
            )
        else:
            query = query.where(
                autopilot_run_items_table.c.streaming_track_id == streaming_track_id
            )
        if exclude_item_id is not None:
            query = query.where(autopilot_run_items_table.c.id != exclude_item_id)
        query = query.order_by(
            desc(autopilot_run_items_table.c.created_at),
            desc(autopilot_run_items_table.c.id),
        ).limit(1)
        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        return _run_item_record(row) if row is not None else None

    def heartbeat(self, run_id: str) -> AutopilotRunRecord:
        return self.update_run(run_id, heartbeat_at=datetime.now(UTC))

    def increment_run_counts(
        self, run_id: str, **increments: int
    ) -> AutopilotRunRecord:
        unknown = set(increments) - RUN_COUNT_FIELDS
        if unknown:
            raise ValueError(f"Unsupported autopilot count(s): {sorted(unknown)}")
        values: dict[str, object] = {}
        for field, increment in increments.items():
            if increment < 0:
                raise ValueError("Autopilot count increments must be nonnegative")
            values[field] = getattr(autopilot_runs_table.c, field) + increment
        return self.update_run(run_id, **values)

    def update_run(self, run_id: str, **values: object) -> AutopilotRunRecord:
        allowed = {
            "status",
            "heartbeat_at",
            "finished_at",
            "error_detail",
            *RUN_COUNT_FIELDS,
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported autopilot run fields: {sorted(unknown)}")
        if "status" in values and values["status"] not in AUTOPILOT_RUN_STATUSES:
            raise ValueError(f"Unsupported autopilot run status: {values['status']}")
        if "error_detail" in values:
            values["error_detail"] = _truncate(values["error_detail"])
        values["updated_at"] = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(autopilot_runs_table)
                .where(autopilot_runs_table.c.id == run_id)
                .values(**values)
            )
            if result.rowcount == 0:
                raise ValueError(f"Autopilot run not found: {run_id}")
            row = (
                connection.execute(
                    select(autopilot_runs_table).where(
                        autopilot_runs_table.c.id == run_id
                    )
                )
                .mappings()
                .one()
            )
        return _run_record(row)

    def _update_item(self, item_id: str, **values: object) -> AutopilotRunItemRecord:
        allowed = {
            "status",
            "attempt_count",
            "next_attempt_at",
            "identity_confidence",
            "version_confidence",
            "quality_score",
            "runner_up_margin",
            "expected_duration_ms",
            "candidate_duration_ms",
            "reason_code",
            "detail",
            "acquisition_id",
            "candidate_id",
            "completed_at",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported autopilot item fields: {sorted(unknown)}")
        if "status" in values and values["status"] not in AUTOPILOT_ITEM_STATUSES:
            raise ValueError(f"Unsupported autopilot item status: {values['status']}")
        values["updated_at"] = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(autopilot_run_items_table)
                .where(autopilot_run_items_table.c.id == item_id)
                .values(**values)
            )
            if result.rowcount == 0:
                raise ValueError(f"Autopilot run item not found: {item_id}")
            row = (
                connection.execute(
                    select(autopilot_run_items_table).where(
                        autopilot_run_items_table.c.id == item_id
                    )
                )
                .mappings()
                .one()
            )
        return _run_item_record(row)


def _validate_settings(values: dict[str, object]) -> None:
    positive_fields = {
        "schedule_minutes",
        "max_concurrent_downloads",
        "retry_max_attempts",
        "retry_base_seconds",
        "retry_max_seconds",
    }
    nonnegative_fields = {
        "quiet_period_seconds",
        "max_downloads_per_run",
        "max_searches_per_run",
        "max_storage_bytes_per_run",
    }
    for field in positive_fields:
        value = values[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    for field in nonnegative_fields:
        value = values[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field} must be a nonnegative integer")
    if int(values["retry_max_seconds"]) < int(values["retry_base_seconds"]):
        raise ValueError("retry_max_seconds must be at least retry_base_seconds")
    if not isinstance(values["paused"], bool):
        raise TypeError("paused must be a boolean")


def _settings_record(row: Any) -> AutopilotSettingsRecord:
    return AutopilotSettingsRecord(
        id=int(row["id"]),
        paused=bool(row["paused"]),
        schedule_minutes=int(row["schedule_minutes"]),
        quiet_period_seconds=int(row["quiet_period_seconds"]),
        max_concurrent_downloads=int(row["max_concurrent_downloads"]),
        max_downloads_per_run=int(row["max_downloads_per_run"]),
        max_searches_per_run=int(row["max_searches_per_run"]),
        max_storage_bytes_per_run=int(row["max_storage_bytes_per_run"]),
        retry_max_attempts=int(row["retry_max_attempts"]),
        retry_base_seconds=int(row["retry_base_seconds"]),
        retry_max_seconds=int(row["retry_max_seconds"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_record(row: Any) -> AutopilotRunRecord:
    return AutopilotRunRecord(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        trigger=row["trigger"],
        dry_run=bool(row["dry_run"]),
        status=row["status"],
        started_at=row["started_at"],
        heartbeat_at=row["heartbeat_at"],
        finished_at=row["finished_at"],
        error_detail=row["error_detail"],
        refreshed_playlists=int(row["refreshed_playlists"]),
        searched_tracks=int(row["searched_tracks"]),
        queued_downloads=int(row["queued_downloads"]),
        downloaded_tracks=int(row["downloaded_tracks"]),
        ingested_tracks=int(row["ingested_tracks"]),
        analyzed_tracks=int(row["analyzed_tracks"]),
        regenerated_recipes=int(row["regenerated_recipes"]),
        refreshed_exports=int(row["refreshed_exports"]),
        review_items=int(row["review_items"]),
        failed_items=int(row["failed_items"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _run_item_record(row: Any) -> AutopilotRunItemRecord:
    return AutopilotRunItemRecord(
        id=row["id"],
        run_id=row["run_id"],
        idempotency_key=row["idempotency_key"],
        stage=row["stage"],
        action=row["action"],
        status=row["status"],
        playlist_id=row["playlist_id"],
        streaming_track_id=row["streaming_track_id"],
        acquisition_id=row["acquisition_id"],
        recipe_id=row["recipe_id"],
        candidate_id=row["candidate_id"],
        attempt_count=int(row["attempt_count"]),
        next_attempt_at=row["next_attempt_at"],
        identity_confidence=row["identity_confidence"],
        version_confidence=row["version_confidence"],
        quality_score=row["quality_score"],
        runner_up_margin=row["runner_up_margin"],
        expected_duration_ms=row["expected_duration_ms"],
        candidate_duration_ms=row["candidate_duration_ms"],
        reason_code=row["reason_code"],
        detail=row["detail"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def _truncate(value: object, limit: int = 4000) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
