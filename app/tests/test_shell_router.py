from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event, insert

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.ingestion.failures import (
    failed_ingestion_attempts_table,
    metadata as failed_ingestion_attempts_metadata,
)
from app.links.store import metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.matching.pipeline import metadata as suggested_links_metadata
from app.relationships.models import metadata as relationships_metadata
from app.relationships.store import StreamingRelationshipSuggestionStore
from app.shell.router import create_router
from app.sonic.models import metadata as sonic_metadata
from app.soulseek.models import (
    SOULSEEK_STATUS_FAILED,
    SOULSEEK_STATUS_LINKED,
    metadata as soulseek_metadata,
    soulseek_acquisitions_table,
)
from app.streaming.models import PLAYLIST_SYNC_MODE_FULL, metadata as streaming_metadata
from tests.factories import TestDataFactory


def test_shell_summary_returns_lightweight_nav_counts(tmp_path: Path) -> None:
    engine = _create_engine(tmp_path / "shell-summary.db")
    factory = TestDataFactory(engine)
    account_id = factory.streaming_account()
    playlist_id = factory.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Late Night Drive",
    )
    linked_streaming_track_id = factory.streaming_track(
        provider_track_id="ytm-linked",
        title="Linked Track",
    )
    proposed_streaming_track_id = factory.streaming_track(
        provider_track_id="ytm-proposed",
        title="Proposed Track",
    )
    failed_soulseek_track_id = factory.streaming_track(
        provider_track_id="ytm-failed",
        title="Failed Search",
    )
    linked_soulseek_track_id = factory.streaming_track(
        provider_track_id="ytm-soulseek-linked",
        title="Linked Search",
    )
    linked_local_track_id = factory.local_track(file_path="Artist/Linked.mp3")
    proposed_local_track_id = factory.local_track(file_path="Artist/Proposed.mp3")
    factory.playlist_membership(
        playlist_id=playlist_id,
        position=1,
        streaming_track_id=linked_streaming_track_id,
    )
    factory.playlist_membership(
        playlist_id=playlist_id,
        position=2,
        streaming_track_id=proposed_streaming_track_id,
    )
    factory.playlist_membership(
        playlist_id=playlist_id,
        position=3,
        streaming_track_id=failed_soulseek_track_id,
    )
    factory.playlist_membership(
        playlist_id=playlist_id,
        position=4,
        streaming_track_id=linked_soulseek_track_id,
    )
    factory.final_link(
        local_track_id=linked_local_track_id,
        streaming_track_id=linked_streaming_track_id,
    )
    factory.suggested_link(
        local_track_id=proposed_local_track_id,
        score=0.91,
        streaming_track_id=proposed_streaming_track_id,
    )
    factory.streaming_relationship_suggestion(
        first_track_id=linked_streaming_track_id,
        second_track_id=proposed_streaming_track_id,
    )
    run_id = factory.playlist_generation_run(playlist_count=2, track_count=24)
    _insert_soulseek_acquisition(
        engine,
        "failed-acq",
        failed_soulseek_track_id,
        SOULSEEK_STATUS_FAILED,
    )
    _insert_soulseek_acquisition(
        engine,
        "linked-acq",
        linked_soulseek_track_id,
        SOULSEEK_STATUS_LINKED,
    )
    _insert_failed_ingestion_attempt(engine, "incoming/unidentified.mp3")
    _insert_failed_ingestion_attempt(
        engine,
        "incoming/ignored.flac",
        ignored_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    _insert_failed_ingestion_attempt(engine, "incoming/not-audio.txt")

    response = _route(create_router(), "GET", "/shell/summary").endpoint(engine=engine)

    assert response.counts.library_track_total == 2
    assert response.counts.link_proposal_count == 1
    assert response.counts.relationship_suggestion_count == 1
    assert response.counts.soulseek_unlinked_count == 2
    assert response.counts.unidentified_active_count == 1
    assert [
        (playlist.id, playlist.title, playlist.imported_track_count)
        for playlist in response.playlists
    ] == [(playlist_id, "Late Night Drive", 4)]
    assert [
        (run.id, run.generation_number, run.playlist_count)
        for run in response.generated_runs
    ] == [(run_id, 1, 2)]


def test_relationship_summary_count_is_set_based(tmp_path: Path) -> None:
    engine = _create_engine(tmp_path / "relationship-summary-query-count.db")
    factory = TestDataFactory(engine)
    for index in range(100):
        first_track_id = factory.streaming_track(
            provider_track_id=f"summary-first-{index}",
            isrc=None,
        )
        second_track_id = factory.streaming_track(
            provider_track_id=f"summary-second-{index}",
            isrc=None,
        )
        factory.streaming_relationship_suggestion(
            first_track_id=first_track_id,
            second_track_id=second_track_id,
        )

    statement_count = 0

    def count_statement(*_args) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        assert (
            StreamingRelationshipSuggestionStore(engine=engine).count_pending() == 100
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_count <= 3


def _create_engine(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    for metadata in (
        beets_metadata,
        streaming_metadata,
        local_tracks_metadata,
        links_metadata,
        suggested_links_metadata,
        relationships_metadata,
        sonic_metadata,
        soulseek_metadata,
        failed_ingestion_attempts_metadata,
    ):
        metadata.create_all(engine)
    return engine


def _route(router, method: str, path: str):
    return next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def _insert_soulseek_acquisition(
    engine, acquisition_id: str, streaming_track_id: int, status: str
) -> None:
    timestamp = datetime(2026, 5, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(soulseek_acquisitions_table).values(
                id=acquisition_id,
                streaming_track_id=streaming_track_id,
                status=status,
                candidate_count=0,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )


def _insert_failed_ingestion_attempt(
    engine, source_path: str, ignored_at: datetime | None = None
) -> None:
    timestamp = datetime(2026, 5, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(failed_ingestion_attempts_table).values(
                source_path=source_path,
                filename=Path(source_path).name,
                fingerprint=None,
                failure_reason="metadata unavailable",
                first_failed_at=timestamp,
                failed_at=timestamp,
                attempt_count=1,
                ignored_at=ignored_at,
            )
        )
