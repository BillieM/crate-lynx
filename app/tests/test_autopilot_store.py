from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.autopilot.models import metadata
from app.autopilot.store import AutopilotStore, bounded_retry_delay_seconds
from sqlalchemy import create_engine


def _store(tmp_path) -> AutopilotStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'autopilot-store.db'}")
    metadata.create_all(engine)
    return AutopilotStore(engine=engine)


def test_settings_are_seeded_safe_and_updated_independently(tmp_path) -> None:
    store = _store(tmp_path)

    settings = store.get_settings()

    assert settings.paused is False
    assert settings.max_downloads_per_run == 10
    assert settings.max_searches_per_run == 25
    assert settings.max_concurrent_downloads == 2
    assert settings.max_storage_bytes_per_run == 10 * 1024 * 1024 * 1024

    updated = store.update_settings(
        paused=True,
        max_downloads_per_run=0,
        max_searches_per_run=0,
        quiet_period_seconds=30,
    )

    assert updated.paused is True
    assert updated.max_downloads_per_run == 0
    assert updated.max_searches_per_run == 0
    assert updated.quiet_period_seconds == 30
    assert updated.schedule_minutes == settings.schedule_minutes


def test_settings_reject_invalid_retry_window(tmp_path) -> None:
    store = _store(tmp_path)

    with pytest.raises(
        ValueError, match="retry_max_seconds must be at least retry_base_seconds"
    ):
        store.update_settings(retry_base_seconds=120, retry_max_seconds=60)


def test_run_and_item_idempotency_and_bounded_retry(tmp_path) -> None:
    store = _store(tmp_path)
    run, created = store.get_or_create_run(
        dry_run=True,
        idempotency_key="scheduled:60:123",
        trigger="scheduled",
    )
    replay, replay_created = store.get_or_create_run(
        dry_run=True,
        idempotency_key="scheduled:60:123",
        trigger="scheduled",
    )

    assert created is True
    assert replay_created is False
    assert replay.id == run.id

    item, item_created = store.get_or_create_run_item(
        action="search_missing_track",
        idempotency_key=f"{run.id}:search:track:10",
        run_id=run.id,
        stage="search",
        streaming_track_id=10,
    )
    replay_item, replay_item_created = store.get_or_create_run_item(
        action="search_missing_track",
        idempotency_key=f"{run.id}:search:track:10",
        run_id=run.id,
        stage="search",
        streaming_track_id=10,
    )

    assert item_created is True
    assert replay_item_created is False
    assert replay_item.id == item.id

    retry_at = datetime.now(UTC)
    retry = store.fail_item_with_retry(
        item.id,
        detail="temporary connectivity failure",
        settings=store.update_settings(
            retry_base_seconds=10,
            retry_max_seconds=25,
            retry_max_attempts=3,
        ),
        now=retry_at,
    )

    assert retry.status == "retry_wait"
    assert retry.attempt_count == 1
    assert retry.next_attempt_at is not None
    assert retry.next_attempt_at.replace(tzinfo=UTC) == retry_at + timedelta(seconds=10)
    assert store.due_retry_items(now=retry_at) == []
    assert [value.id for value in store.due_retry_items(now=retry.next_attempt_at)] == [
        item.id
    ]


def test_last_search_timestamp_excludes_cap_skips(tmp_path) -> None:
    store = _store(tmp_path)
    run, _ = store.get_or_create_run(
        dry_run=False,
        idempotency_key="scheduled:60:search-history",
        trigger="scheduled",
    )
    attempted, _ = store.get_or_create_run_item(
        action="search_missing_track",
        idempotency_key=f"{run.id}:search:track:10",
        run_id=run.id,
        stage="search",
        streaming_track_id=10,
    )
    store.mark_item_running(attempted.id)
    store.complete_item(attempted.id)
    capped, _ = store.get_or_create_run_item(
        action="search_missing_track",
        idempotency_key=f"{run.id}:search:track:20",
        run_id=run.id,
        stage="search",
        streaming_track_id=20,
    )
    store.complete_item(
        capped.id,
        status="skipped",
        reason_code="search_count_cap",
    )

    history = store.last_completed_search_at({10, 20, 30})
    assert set(history) == {10}
    assert history[10] is not None


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 10), (2, 20), (3, 25), (10, 25)],
)
def test_retry_delay_is_exponential_and_capped(attempt: int, expected: int) -> None:
    assert (
        bounded_retry_delay_seconds(
            attempt_count=attempt,
            base_seconds=10,
            max_seconds=25,
        )
        == expected
    )
