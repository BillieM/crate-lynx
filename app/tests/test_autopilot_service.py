from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from app.autopilot.gates import ImportVerificationDecision
from app.autopilot.gateway import (
    AnalysisState,
    PlaylistRefreshResult,
    SearchResult,
    VerificationResult,
)
from app.autopilot.models import metadata
from app.autopilot.lock import LockOwnershipLostError
from app.autopilot.recipes import RecipeRegenerationResult
from app.autopilot.service import AutopilotCoordinator
from app.autopilot.store import AutopilotStore
from app.soulseek.models import (
    SOULSEEK_STATUS_CANDIDATES_FOUND,
    SOULSEEK_STATUS_QUEUED,
    SoulseekAcquisitionRecord,
    SoulseekCandidateRecord,
    StreamingTrackForSoulseek,
)
from app.streaming.models import StreamingPlaylistSummary
from sqlalchemy import create_engine


def _playlist(playlist_id: int, automation_level: str) -> StreamingPlaylistSummary:
    return StreamingPlaylistSummary(
        id=playlist_id,
        account_id=1,
        provider_playlist_id=f"PL{playlist_id}",
        title=f"Playlist {playlist_id}",
        sync_mode="off",
        automation_level=automation_level,
        provider_track_count=1,
        imported_track_count=1,
        metadata_synced_at=None,
        tracks_synced_at=None,
        last_sync_error=None,
        last_sync_error_at=None,
    )


def _acquisition(track_id: int, run_id: str) -> SoulseekAcquisitionRecord:
    now = datetime.now(UTC)
    return SoulseekAcquisitionRecord(
        id=f"acquisition-{track_id}",
        streaming_track_id=track_id,
        status=SOULSEEK_STATUS_CANDIDATES_FOUND,
        search_text="Artist Track",
        fallback_search_text=None,
        slskd_search_id="search-1",
        slskd_fallback_search_id=None,
        candidate_count=1,
        selected_candidate_id=None,
        slskd_batch_id=None,
        destination=None,
        completed_source_path=None,
        slskd_completed_event_id=None,
        local_track_id=None,
        final_link_id=None,
        proposal_id=None,
        job_id=None,
        enqueue_job_id=None,
        refresh_job_id=None,
        error_detail=None,
        link_error_detail=None,
        automation_run_id=run_id,
        unattended=True,
        verification_status=None,
        verification_detail=None,
        verified_at=None,
        searched_at=now,
        queued_at=None,
        completed_at=None,
        ingested_at=None,
        proposal_available_at=None,
        linked_at=None,
        failed_at=None,
        created_at=now,
        updated_at=now,
    )


def _candidate(track_id: int) -> SoulseekCandidateRecord:
    return SoulseekCandidateRecord(
        id=f"candidate-{track_id}",
        acquisition_id=f"acquisition-{track_id}",
        slskd_search_id="search-1",
        username="peer",
        filename="Artist/Track.flac",
        size=8_000_000,
        extension=".flac",
        duration_seconds=240,
        bit_rate=None,
        bit_depth=16,
        sample_rate=44_100,
        is_variable_bit_rate=None,
        has_free_upload_slot=True,
        queue_length=0,
        upload_speed=1_000_000,
        score=0.95,
        identity_confidence=0.96,
        version_confidence=1.0,
        quality_score=0.9,
        created_at=datetime.now(UTC),
    )


@dataclass
class FakeGateway:
    playlists: list[StreamingPlaylistSummary]
    queue_calls: list[str] = field(default_factory=list)
    refresh_calls: list[int] = field(default_factory=list)
    search_calls: list[tuple[int, bool]] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
    analysis_states: dict[str, AnalysisState] = field(default_factory=dict)
    affected_playlists_by_track: dict[int, tuple[int, ...]] = field(
        default_factory=dict
    )

    def selected_playlists(self):
        return self.playlists

    def refresh_playlist(self, playlist_id: int):
        self.refresh_calls.append(playlist_id)
        return PlaylistRefreshResult(
            playlist_id=playlist_id,
            changed=True,
            membership_count=1,
        )

    def unresolved_tracks(self, playlist_id: int):
        return [
            StreamingTrackForSoulseek(
                id=playlist_id,
                title="Track",
                artist="Artist",
                album=None,
                duration_ms=240_000,
            )
        ]

    def search_track(
        self,
        *,
        automation_run_id: str,
        streaming_track_id: int,
        unattended: bool,
    ):
        self.search_calls.append((streaming_track_id, unattended))
        return SearchResult(
            acquisition=_acquisition(streaming_track_id, automation_run_id),
            candidates=[_candidate(streaming_track_id)],
        )

    def active_unattended_downloads(self):
        return 0

    def queue_candidate(self, candidate_id: str):
        self.queue_calls.append(candidate_id)
        return _acquisition(int(candidate_id.rsplit("-", 1)[1]), "run")

    def refresh_active_transfers(self):
        return []

    def verify_pending_imports(self):
        return self.verification_results

    def analysis_state(self, acquisition_id: str):
        return self.analysis_states.get(
            acquisition_id,
            AnalysisState(local_track_id=None, status=None),
        )

    def affected_playlist_ids(self, streaming_track_id: int):
        return self.affected_playlists_by_track.get(streaming_track_id, ())


@dataclass
class FakeRecipes:
    regenerate_calls: list[int] = field(default_factory=list)

    def affected_recipe_ids(self, affected_playlist_ids: set[int]):
        return [99] if affected_playlist_ids else []

    def regenerate(self, recipe_id: int):
        self.regenerate_calls.append(recipe_id)
        return RecipeRegenerationResult(
            recipe_id=recipe_id,
            generation_run_id=100,
            export_result=None,
        )


def _coordinator(tmp_path, gateway: FakeGateway, recipes: FakeRecipes):
    engine = create_engine(f"sqlite:///{tmp_path / 'autopilot-service.db'}")
    metadata.create_all(engine)
    store = AutopilotStore(engine=engine)
    return AutopilotCoordinator(store, gateway, recipes), store


def test_dry_run_suppresses_download_link_regeneration_and_export(tmp_path) -> None:
    gateway = FakeGateway([_playlist(1, "full")])
    recipes = FakeRecipes()
    coordinator, store = _coordinator(tmp_path, gateway, recipes)

    run = coordinator.run(
        dry_run=True,
        idempotency_key="manual:dry-run",
        trigger="manual",
    )

    assert run.status == "succeeded"
    assert run.refreshed_playlists == 1
    assert run.searched_tracks == 1
    assert run.queued_downloads == 0
    assert gateway.queue_calls == []
    assert recipes.regenerate_calls == []
    reasons = {item.reason_code for item in store.list_run_items(run.id)}
    assert "dry_run_download_suppressed" in reasons
    assert "dry_run_regeneration_suppressed" in reasons


def test_assist_never_downloads_while_full_is_explicit_opt_in(tmp_path) -> None:
    gateway = FakeGateway(
        [
            _playlist(1, "assist"),
            _playlist(2, "full"),
        ]
    )
    recipes = FakeRecipes()
    coordinator, store = _coordinator(tmp_path, gateway, recipes)

    run = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:1",
        trigger="scheduled",
    )

    assert gateway.search_calls == [(1, False), (2, True)]
    assert gateway.queue_calls == ["candidate-2"]
    assert run.queued_downloads == 1
    assert run.review_items == 1
    assist = next(
        item
        for item in store.list_run_items(run.id)
        if item.action == "assist_search_result"
    )
    assert assist.status == "review"
    assert assist.reason_code == "assist_only"


def test_global_pause_prevents_all_automatic_work(tmp_path) -> None:
    gateway = FakeGateway([_playlist(1, "full")])
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(paused=True)

    run = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:2",
        trigger="scheduled",
    )

    assert run.status == "paused"
    assert gateway.refresh_calls == []
    assert gateway.search_calls == []
    assert gateway.queue_calls == []


def test_inflight_unattended_acquisition_is_skipped_across_runs(tmp_path) -> None:
    class InFlightGateway(FakeGateway):
        def search_track(
            self,
            *,
            automation_run_id: str,
            streaming_track_id: int,
            unattended: bool,
        ):
            self.search_calls.append((streaming_track_id, unattended))
            acquisition = replace(
                _acquisition(streaming_track_id, "original-run"),
                status=SOULSEEK_STATUS_QUEUED,
            )
            return SearchResult(
                acquisition=acquisition,
                candidates=[_candidate(streaming_track_id)],
                download_suppressed_reason="unattended_acquisition_in_flight",
            )

    gateway = InFlightGateway([_playlist(1, "full")])
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())

    first = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:duplicate-1",
        trigger="scheduled",
    )
    second = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:duplicate-2",
        trigger="scheduled",
    )

    assert gateway.queue_calls == []
    assert first.queued_downloads == second.queued_downloads == 0
    assert {
        item.reason_code
        for run in (first, second)
        for item in store.list_run_items(run.id)
    } >= {"unattended_acquisition_in_flight"}


def test_operational_retry_backoff_and_attempt_count_cross_runs(tmp_path) -> None:
    class FlakyRefreshGateway(FakeGateway):
        failures_remaining = 1

        def refresh_playlist(self, playlist_id: int):
            self.refresh_calls.append(playlist_id)
            if self.failures_remaining:
                self.failures_remaining -= 1
                raise OSError("temporary provider outage")
            return PlaylistRefreshResult(
                playlist_id=playlist_id,
                changed=False,
                membership_count=1,
            )

    gateway = FlakyRefreshGateway([_playlist(1, "sync_only")])
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(
        retry_base_seconds=60,
        retry_max_seconds=60,
        retry_max_attempts=3,
    )

    first = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:retry-1",
        trigger="scheduled",
    )
    retry = next(
        item
        for item in store.list_run_items(first.id)
        if item.action == "refresh_playlist"
    )
    assert retry.status == "retry_wait"
    assert retry.attempt_count == 1

    second = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:retry-2",
        trigger="scheduled",
    )
    assert gateway.refresh_calls == [1]
    assert any(
        item.reason_code == "retry_backoff_active"
        for item in store.list_run_items(second.id)
    )

    store.defer_item(
        retry.id,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        reason_code="retry_scheduled",
        detail="test clock advanced beyond backoff",
    )
    third = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:retry-3",
        trigger="scheduled",
    )

    assert gateway.refresh_calls == [1, 1]
    resumed = store.get_run_item(retry.id)
    assert resumed is not None
    assert resumed.status == "succeeded"
    assert resumed.attempt_count == 2
    assert any(
        item.reason_code == "retry_carried_forward"
        for item in store.list_run_items(third.id)
    )


def test_pause_stops_between_playlists_and_records_evidence(tmp_path) -> None:
    class PauseAfterRefreshGateway(FakeGateway):
        pause_callback = None

        def refresh_playlist(self, playlist_id: int):
            result = super().refresh_playlist(playlist_id)
            if self.pause_callback is not None:
                self.pause_callback()
            return result

    gateway = PauseAfterRefreshGateway(
        [_playlist(1, "sync_only"), _playlist(2, "sync_only")]
    )
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    gateway.pause_callback = lambda: store.update_settings(paused=True)

    run = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:pause-mid-run",
        trigger="scheduled",
    )

    assert run.status == "paused"
    assert gateway.refresh_calls == [1]
    pause_item = next(
        item for item in store.list_run_items(run.id) if item.action == "global_pause"
    )
    assert pause_item.status == "skipped"
    assert pause_item.reason_code == "global_pause"
    assert "playlist:2" in (pause_item.detail or "")


def test_verified_import_counts_ready_sonic_analysis(tmp_path) -> None:
    acquisition = replace(
        _acquisition(1, "run"),
        status="linked",
        local_track_id=51,
    )
    gateway = FakeGateway(
        [],
        verification_results=[
            VerificationResult(
                acquisition=acquisition,
                decision=ImportVerificationDecision(
                    accepted=True,
                    reason_code="verified",
                    detail="Readable audio and duration verified",
                ),
                affected_playlist_ids=(),
            )
        ],
        analysis_states={
            acquisition.id: AnalysisState(local_track_id=51, status="ready")
        },
    )
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())

    run = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-ready",
        trigger="scheduled",
    )

    assert run.ingested_tracks == 1
    assert run.analyzed_tracks == 1
    analysis_item = next(
        item
        for item in store.list_run_items(run.id)
        if item.action == "observe_track_analysis"
    )
    assert analysis_item.status == "succeeded"
    assert "Local track 51" in (analysis_item.detail or "")


def test_pending_analysis_is_observed_by_later_scheduled_run(tmp_path) -> None:
    acquisition = replace(
        _acquisition(1, "run"),
        status="linked",
        local_track_id=52,
    )
    gateway = FakeGateway(
        [],
        verification_results=[
            VerificationResult(
                acquisition=acquisition,
                decision=ImportVerificationDecision(
                    accepted=True,
                    reason_code="verified",
                    detail="Readable audio and duration verified",
                ),
                affected_playlist_ids=(),
            )
        ],
        analysis_states={
            acquisition.id: AnalysisState(local_track_id=52, status="pending")
        },
    )
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(
        retry_base_seconds=60,
        retry_max_seconds=60,
        retry_max_attempts=3,
    )

    first = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-pending",
        trigger="scheduled",
    )
    analysis_item = next(
        item
        for item in store.list_run_items(first.id)
        if item.action == "observe_track_analysis"
    )
    assert analysis_item.status == "retry_wait"
    assert first.analyzed_tracks == 0

    store.defer_item(
        analysis_item.id,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        reason_code="retry_scheduled",
        detail="test clock advanced beyond backoff",
    )
    gateway.verification_results = []
    gateway.analysis_states[acquisition.id] = AnalysisState(
        local_track_id=52,
        status="ready",
    )
    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-observed",
        trigger="scheduled",
    )

    updated_first = store.get_run(first.id)
    updated_item = store.get_run_item(analysis_item.id)
    assert updated_first is not None
    assert updated_first.analyzed_tracks == 1
    assert updated_item is not None
    assert updated_item.status == "succeeded"
    assert updated_item.attempt_count == 2


def test_recipe_regeneration_waits_for_analysis_and_reschedules_when_ready(
    tmp_path,
) -> None:
    class ExportingRecipes(FakeRecipes):
        def regenerate(self, recipe_id: int):
            result = super().regenerate(recipe_id)
            return replace(result, export_result=object())

    acquisition = replace(
        _acquisition(1, "run"),
        status="linked",
        local_track_id=53,
    )
    gateway = FakeGateway(
        [],
        verification_results=[
            VerificationResult(
                acquisition=acquisition,
                decision=ImportVerificationDecision(
                    accepted=True,
                    reason_code="verified",
                    detail="Readable audio and duration verified",
                ),
                affected_playlist_ids=(7,),
            )
        ],
        analysis_states={
            acquisition.id: AnalysisState(local_track_id=53, status="pending")
        },
        affected_playlists_by_track={1: (7,)},
    )
    recipes = ExportingRecipes()
    coordinator, store = _coordinator(tmp_path, gateway, recipes)
    store.update_settings(
        quiet_period_seconds=0,
        retry_base_seconds=1,
        retry_max_seconds=1,
        retry_max_attempts=4,
    )

    first = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-before-recipe-1",
        trigger="scheduled",
    )
    analysis_item = next(
        item
        for item in store.list_run_items(first.id)
        if item.action == "observe_track_analysis"
    )
    assert analysis_item.status == "retry_wait"
    assert not any(
        item.action == "regenerate_recipe" for item in store.list_run_items(first.id)
    )

    gateway.verification_results = []
    store.defer_item(
        analysis_item.id,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        reason_code="retry_scheduled",
        detail="analysis remains pending after the original quiet period",
    )
    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-before-recipe-2",
        trigger="scheduled",
    )
    assert recipes.regenerate_calls == []
    assert not any(
        item.action == "regenerate_recipe"
        for run in store.list_runs(limit=10)
        for item in store.list_run_items(run.id)
    )

    store.defer_item(
        analysis_item.id,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        reason_code="retry_scheduled",
        detail="analysis is now ready",
    )
    gateway.analysis_states[acquisition.id] = AnalysisState(
        local_track_id=53,
        status="ready",
    )
    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-before-recipe-3",
        trigger="scheduled",
    )

    recipe_items = [
        item
        for run in store.list_runs(limit=10)
        for item in store.list_run_items(run.id)
        if item.action == "regenerate_recipe"
    ]
    assert len(recipe_items) == 1
    assert recipe_items[0].status == "retry_wait"
    assert recipes.regenerate_calls == []

    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:analysis-before-recipe-4",
        trigger="scheduled",
    )

    updated_first = store.get_run(first.id)
    assert updated_first is not None
    assert updated_first.analyzed_tracks == 1
    assert updated_first.regenerated_recipes == 1
    assert updated_first.refreshed_exports == 1
    assert recipes.regenerate_calls == [99]
    assert store.get_run_item(recipe_items[0].id).status == "succeeded"


def test_search_cap_is_deterministic_and_resumes_remaining_tracks(tmp_path) -> None:
    class ResolvingAssistGateway(FakeGateway):
        searched: set[int] = set()

        def unresolved_tracks(self, playlist_id: int):
            if playlist_id in self.searched:
                return []
            return super().unresolved_tracks(playlist_id)

        def search_track(self, **kwargs):
            result = super().search_track(**kwargs)
            self.searched.add(kwargs["streaming_track_id"])
            return result

    gateway = ResolvingAssistGateway(
        [_playlist(3, "assist"), _playlist(1, "assist"), _playlist(2, "assist")]
    )
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(max_searches_per_run=2)

    first = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:search-cap-1",
        trigger="scheduled",
    )
    assert gateway.search_calls == [(1, False), (2, False)]
    capped = [
        item
        for item in store.list_run_items(first.id)
        if item.reason_code == "search_count_cap"
    ]
    assert len(capped) == 1
    assert capped[0].action == "defer_search_backlog"
    assert capped[0].streaming_track_id is None
    assert "Deferred 1 unresolved tracks" in (capped[0].detail or "")

    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:search-cap-2",
        trigger="scheduled",
    )
    assert gateway.search_calls == [(1, False), (2, False), (3, False)]


def test_search_cap_resumes_unattempted_tracks_that_remain_unresolved(tmp_path) -> None:
    gateway = FakeGateway(
        [
            _playlist(4, "assist"),
            _playlist(2, "assist"),
            _playlist(1, "assist"),
            _playlist(3, "assist"),
        ]
    )
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(max_searches_per_run=2)

    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:search-cap-unresolved-1",
        trigger="scheduled",
    )
    assert gateway.search_calls == [(1, False), (2, False)]

    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:search-cap-unresolved-2",
        trigger="scheduled",
    )

    assert gateway.search_calls == [
        (1, False),
        (2, False),
        (3, False),
        (4, False),
    ]


def test_search_rotation_stays_fair_and_cached_lookups_do_not_use_live_cap(
    tmp_path,
) -> None:
    class RotatingAssistGateway(FakeGateway):
        track_one_calls = 0
        live_search_calls: list[int] = []

        def search_track(self, **kwargs):
            result = super().search_track(**kwargs)
            track_id = kwargs["streaming_track_id"]
            if track_id == 1:
                self.track_one_calls += 1
            performed_search = not (track_id == 1 and self.track_one_calls == 2)
            if performed_search:
                self.live_search_calls.append(track_id)
            return replace(result, performed_search=performed_search)

    gateway = RotatingAssistGateway(
        [
            _playlist(4, "assist"),
            _playlist(2, "assist"),
            _playlist(1, "assist"),
            _playlist(3, "assist"),
        ]
    )
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(max_searches_per_run=1)

    runs = [
        coordinator.run(
            dry_run=False,
            idempotency_key=f"scheduled:60:search-rotation-{index}",
            trigger="scheduled",
        )
        for index in range(1, 6)
    ]

    assert gateway.search_calls == [
        (1, False),
        (2, False),
        (3, False),
        (4, False),
        (1, False),
        (2, False),
    ]
    assert gateway.live_search_calls == [1, 2, 3, 4, 2]
    assert [run.searched_tracks for run in runs] == [1, 1, 1, 1, 1]


def test_search_backlog_evidence_is_bounded_by_the_cap(tmp_path) -> None:
    class LargePlaylistGateway(FakeGateway):
        def unresolved_tracks(self, playlist_id: int):
            return [
                StreamingTrackForSoulseek(
                    id=track_id,
                    title=f"Track {track_id}",
                    artist="Artist",
                    album=None,
                    duration_ms=240_000,
                )
                for track_id in range(1, 101)
            ]

    gateway = LargePlaylistGateway([_playlist(1, "assist")])
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(max_searches_per_run=2)

    run = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:bounded-search-backlog",
        trigger="scheduled",
    )
    items = store.list_run_items(run.id)

    assert len([item for item in items if item.action == "search_missing_track"]) == 2
    backlog_items = [item for item in items if item.action == "defer_search_backlog"]
    assert len(backlog_items) == 1
    assert "Deferred 98 unresolved tracks" in (backlog_items[0].detail or "")


def test_zero_search_cap_disables_acquisition_searches(tmp_path) -> None:
    gateway = FakeGateway([_playlist(1, "full")])
    coordinator, store = _coordinator(tmp_path, gateway, FakeRecipes())
    store.update_settings(max_searches_per_run=0)

    run = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:search-cap-zero",
        trigger="scheduled",
    )

    assert gateway.search_calls == []
    items = store.list_run_items(run.id)
    assert not any(item.action == "search_missing_track" for item in items)
    backlog_items = [item for item in items if item.action == "defer_search_backlog"]
    assert len(backlog_items) == 1
    assert backlog_items[0].reason_code == "search_count_cap"


def test_recipe_bursts_extend_one_pending_debounce_and_regenerate_once(
    tmp_path,
) -> None:
    gateway = FakeGateway([_playlist(1, "sync_only")])
    recipes = FakeRecipes()
    coordinator, store = _coordinator(tmp_path, gateway, recipes)
    store.update_settings(quiet_period_seconds=60)

    first = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:burst-1",
        trigger="scheduled",
    )
    first_item = next(
        item
        for item in store.list_run_items(first.id)
        if item.action == "regenerate_recipe"
    )
    first_due_at = first_item.next_attempt_at

    second = coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:burst-2",
        trigger="scheduled",
    )
    pending = [
        item
        for run in store.list_runs(limit=10)
        for item in store.list_run_items(run.id)
        if item.action == "regenerate_recipe" and item.status == "retry_wait"
    ]
    assert len(pending) == 1
    assert pending[0].id == first_item.id
    assert first_due_at is not None
    assert pending[0].next_attempt_at is not None
    assert pending[0].next_attempt_at >= first_due_at
    assert all(
        item.action != "regenerate_recipe" for item in store.list_run_items(second.id)
    )

    store.defer_item(
        first_item.id,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        reason_code="quiet_period",
        detail="test clock advanced beyond quiet period",
    )
    gateway.playlists = []
    coordinator.run(
        dry_run=False,
        idempotency_key="scheduled:60:burst-drain",
        trigger="scheduled",
    )

    assert recipes.regenerate_calls == [99]
    assert store.get_run_item(first_item.id).status == "succeeded"


def test_lease_theft_stops_before_next_external_mutation(tmp_path) -> None:
    ownership = {"held": True}

    class StealingGateway(FakeGateway):
        def refresh_playlist(self, playlist_id: int):
            result = super().refresh_playlist(playlist_id)
            ownership["held"] = False
            return result

    def assert_owned() -> None:
        if not ownership["held"]:
            raise LockOwnershipLostError("test lease stolen")

    gateway = StealingGateway([_playlist(1, "sync_only"), _playlist(2, "sync_only")])
    engine = create_engine(f"sqlite:///{tmp_path / 'autopilot-lease.db'}")
    metadata.create_all(engine)
    store = AutopilotStore(engine=engine)
    coordinator = AutopilotCoordinator(
        store,
        gateway,
        FakeRecipes(),
        lease_checkpoint=assert_owned,
    )

    run = coordinator.run(
        dry_run=True,
        idempotency_key="manual:lease-theft",
        trigger="manual",
    )

    assert run.status == "failed"
    assert gateway.refresh_calls == [1]
    assert gateway.search_calls == []
    refresh_item = next(
        item
        for item in store.list_run_items(run.id)
        if item.action == "refresh_playlist"
    )
    assert refresh_item.status == "retry_wait"
