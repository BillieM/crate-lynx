from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.autopilot.gates import CandidateGateDecision, evaluate_unattended_candidates
from app.autopilot.gateway import AutopilotWorkflowGateway
from app.autopilot.lock import LockOwnershipLostError
from app.autopilot.models import (
    AUTOPILOT_ITEM_STATUS_FAILED,
    AUTOPILOT_ITEM_STATUS_RETRY_WAIT,
    AUTOPILOT_ITEM_STATUS_REVIEW,
    AUTOPILOT_RUN_STATUS_FAILED,
    AUTOPILOT_RUN_STATUS_PARTIAL,
    AUTOPILOT_RUN_STATUS_PAUSED,
    AUTOPILOT_RUN_STATUS_RUNNING,
    AUTOPILOT_RUN_STATUS_SKIPPED,
    AUTOPILOT_RUN_STATUS_SUCCEEDED,
    AutopilotRunItemRecord,
    AutopilotRunRecord,
)
from app.autopilot.recipes import RecipeRegenerationAdapter
from app.autopilot.store import AutopilotStore
from app.sonic.models import (
    SONIC_FEATURE_STATUS_FAILED,
    SONIC_FEATURE_STATUS_READY,
)
from app.streaming.models import (
    PLAYLIST_AUTOMATION_LEVEL_ASSIST,
    PLAYLIST_AUTOMATION_LEVEL_FULL,
)

logger = logging.getLogger(__name__)

_AUTOMATION_PRIORITY = {
    "off": 0,
    "sync_only": 1,
    "assist": 2,
    "full": 3,
}
_TERMINAL_ITEM_STATUSES = {"succeeded", "skipped", "review", "failed"}
_SEARCH_LOOKUP_BATCH_MULTIPLIER = 2


class _AutopilotPaused(RuntimeError):
    pass


def _noop_checkpoint() -> None:
    pass


@dataclass(slots=True)
class AutopilotCoordinator:
    store: AutopilotStore
    gateway: AutopilotWorkflowGateway
    recipe_adapter: RecipeRegenerationAdapter
    lease_checkpoint: Callable[[], None] = _noop_checkpoint

    def run(
        self,
        *,
        dry_run: bool,
        idempotency_key: str,
        trigger: str,
    ) -> AutopilotRunRecord:
        run, created = self.store.get_or_create_run(
            dry_run=dry_run,
            idempotency_key=idempotency_key,
            trigger=trigger,
        )
        if not created and run.status in {
            AUTOPILOT_RUN_STATUS_SUCCEEDED,
            AUTOPILOT_RUN_STATUS_PARTIAL,
            AUTOPILOT_RUN_STATUS_PAUSED,
            AUTOPILOT_RUN_STATUS_SKIPPED,
        }:
            return run

        settings = self.store.get_settings()
        if settings.paused:
            return self.store.update_run(
                run.id,
                status=AUTOPILOT_RUN_STATUS_PAUSED,
                finished_at=datetime.now(UTC),
                error_detail=None,
            )

        self.store.update_run(
            run.id,
            status=AUTOPILOT_RUN_STATUS_RUNNING,
            heartbeat_at=datetime.now(UTC),
            finished_at=None,
            error_detail=None,
        )
        try:
            if not dry_run:
                self._pause_checkpoint(run.id, "before_deferred_work")
                self._process_due_recipe_work(
                    settings=settings,
                    current_run_id=run.id,
                )
                self._process_due_analysis_work(
                    settings=settings,
                    current_run_id=run.id,
                )
                self._pause_checkpoint(run.id, "before_transfer_refresh")
                self._refresh_transfers(run.id, settings=settings)

            affected_playlist_ids: set[int] = set()
            track_context: dict[int, tuple[object, int]] = {}
            for playlist in self.gateway.selected_playlists():
                self._pause_checkpoint(run.id, f"playlist:{playlist.id}")
                refresh_item = self._item(
                    run_id=run.id,
                    stage="refresh",
                    action="refresh_playlist",
                    suffix=f"playlist:{playlist.id}",
                    playlist_id=playlist.id,
                )
                if refresh_item.status in _TERMINAL_ITEM_STATUSES:
                    continue
                refresh_work_item = self._retry_work_item(refresh_item)
                if refresh_work_item is None:
                    continue
                self.store.mark_item_running(refresh_work_item.id)
                try:
                    refresh = self._external_mutation(
                        lambda: self.gateway.refresh_playlist(playlist.id)
                    )
                except LockOwnershipLostError as exc:
                    self.store.fail_item_with_retry(
                        refresh_work_item.id,
                        detail=str(exc),
                        settings=settings,
                    )
                    self._settle_retry_origin(refresh_work_item, refresh_item)
                    raise
                except Exception as exc:  # noqa: BLE001 - isolate one playlist
                    self.store.fail_item_with_retry(
                        refresh_work_item.id,
                        detail=str(exc),
                        settings=settings,
                    )
                    self._settle_retry_origin(refresh_work_item, refresh_item)
                    continue
                self.store.complete_item(refresh_work_item.id)
                self._settle_retry_origin(refresh_work_item, refresh_item)
                self.store.increment_run_counts(run.id, refreshed_playlists=1)
                if refresh.changed:
                    affected_playlist_ids.add(playlist.id)
                if playlist.automation_level not in {
                    PLAYLIST_AUTOMATION_LEVEL_ASSIST,
                    PLAYLIST_AUTOMATION_LEVEL_FULL,
                }:
                    continue
                for track in self.gateway.unresolved_tracks(playlist.id):
                    existing = track_context.get(track.id)
                    if (
                        existing is None
                        or _AUTOMATION_PRIORITY[playlist.automation_level]
                        > _AUTOMATION_PRIORITY[existing[0].automation_level]
                    ):
                        track_context[track.id] = (playlist, track)

            queued_downloads = 0
            queued_bytes = 0
            live_searches = 0
            available_concurrency = max(
                0,
                settings.max_concurrent_downloads
                - self.gateway.active_unattended_downloads(),
            )
            last_search_at = self.store.last_completed_search_at(set(track_context))
            ordered_track_ids = sorted(
                track_context,
                key=lambda track_id: (
                    track_id in last_search_at,
                    (
                        _as_utc(last_search_at[track_id])
                        if track_id in last_search_at
                        else datetime.min.replace(tzinfo=UTC)
                    ),
                    track_id,
                ),
            )
            lookup_limit = (
                settings.max_searches_per_run * _SEARCH_LOOKUP_BATCH_MULTIPLIER
            )
            search_batch = ordered_track_ids[:lookup_limit]
            processed_track_count = 0
            for streaming_track_id in search_batch:
                if live_searches >= settings.max_searches_per_run:
                    break
                processed_track_count += 1
                playlist, track = track_context[streaming_track_id]
                self._pause_checkpoint(run.id, f"track:{track.id}")
                full = playlist.automation_level == PLAYLIST_AUTOMATION_LEVEL_FULL
                search_item = self._item(
                    run_id=run.id,
                    stage="search",
                    action="search_missing_track",
                    suffix=f"track:{track.id}",
                    playlist_id=playlist.id,
                    streaming_track_id=track.id,
                )
                if search_item.status in _TERMINAL_ITEM_STATUSES:
                    continue
                search_work_item = self._retry_work_item(search_item)
                if search_work_item is None:
                    continue
                self.store.mark_item_running(search_work_item.id)
                # Count exceptions conservatively as live-search work. A
                # successful cached/no-op result releases the slot below.
                live_searches += 1
                try:
                    search = self._external_mutation(
                        lambda: self.gateway.search_track(
                            automation_run_id=run.id,
                            streaming_track_id=track.id,
                            unattended=full,
                        )
                    )
                except LockOwnershipLostError as exc:
                    self.store.fail_item_with_retry(
                        search_work_item.id,
                        detail=str(exc),
                        settings=settings,
                    )
                    self._settle_retry_origin(search_work_item, search_item)
                    raise
                except Exception as exc:  # noqa: BLE001 - isolate one track
                    self.store.fail_item_with_retry(
                        search_work_item.id,
                        detail=str(exc),
                        settings=settings,
                    )
                    self._settle_retry_origin(search_work_item, search_item)
                    continue
                if not search.performed_search:
                    live_searches -= 1
                if search.download_suppressed_reason is not None:
                    suppression_detail = (
                        "An imported unattended acquisition requires review; "
                        "autopilot will not download it again"
                        if search.download_suppressed_reason
                        == "unattended_acquisition_review_required"
                        else (
                            "An unattended acquisition is already queued, "
                            "downloading, imported, or awaiting verification"
                        )
                    )
                    self.store.complete_item(
                        search_work_item.id,
                        status="skipped",
                        reason_code=search.download_suppressed_reason,
                        detail=suppression_detail,
                        acquisition_id=search.acquisition.id,
                    )
                    self._settle_retry_origin(search_work_item, search_item)
                    continue
                self.store.complete_item(
                    search_work_item.id,
                    acquisition_id=search.acquisition.id,
                )
                self._settle_retry_origin(search_work_item, search_item)
                if search.performed_search:
                    self.store.increment_run_counts(run.id, searched_tracks=1)
                if not full:
                    self._record_assist_review(
                        run_id=run.id,
                        playlist_id=playlist.id,
                        streaming_track_id=track.id,
                        acquisition_id=search.acquisition.id,
                    )
                    continue

                decision = evaluate_unattended_candidates(
                    candidates=search.candidates,
                    expected_duration_ms=track.duration_ms,
                )
                gate_item = self._gate_item(
                    run_id=run.id,
                    playlist_id=playlist.id,
                    streaming_track_id=track.id,
                    acquisition_id=search.acquisition.id,
                    decision=decision,
                )
                if not decision.accepted:
                    self.store.complete_item(
                        gate_item.id,
                        status="review",
                        reason_code=decision.reason_code,
                        detail=decision.detail,
                    )
                    self.store.increment_run_counts(run.id, review_items=1)
                    continue
                if decision.candidate is None:
                    raise RuntimeError("Accepted unattended gate has no candidate")
                if dry_run:
                    self.store.complete_item(
                        gate_item.id,
                        status="skipped",
                        reason_code="dry_run_download_suppressed",
                        detail=(
                            "All unattended gates passed; dry-run suppressed download"
                        ),
                    )
                    continue
                candidate = decision.candidate
                cap_reason = _download_cap_reason(
                    available_concurrency=available_concurrency,
                    candidate_size=candidate.size,
                    max_downloads=settings.max_downloads_per_run,
                    max_storage_bytes=settings.max_storage_bytes_per_run,
                    queued_bytes=queued_bytes,
                    queued_downloads=queued_downloads,
                )
                if cap_reason is not None:
                    self.store.complete_item(
                        gate_item.id,
                        status="skipped",
                        reason_code=cap_reason,
                        detail="Bounded unattended download cap reached",
                    )
                    continue
                self._pause_checkpoint(run.id, f"queue:{track.id}")
                gate_work_item = self._retry_work_item(gate_item)
                if gate_work_item is None:
                    continue
                self.store.mark_item_running(gate_work_item.id)
                try:
                    acquisition = self._external_mutation(
                        lambda: self.gateway.queue_candidate(candidate.id)
                    )
                except LockOwnershipLostError as exc:
                    self.store.fail_item_with_retry(
                        gate_work_item.id,
                        detail=str(exc),
                        settings=settings,
                    )
                    self._settle_retry_origin(gate_work_item, gate_item)
                    raise
                except Exception as exc:  # noqa: BLE001 - bounded item retry
                    self.store.fail_item_with_retry(
                        gate_work_item.id,
                        detail=str(exc),
                        settings=settings,
                    )
                    self._settle_retry_origin(gate_work_item, gate_item)
                    continue
                self.store.complete_item(
                    gate_work_item.id,
                    acquisition_id=acquisition.id,
                    candidate_id=candidate.id,
                )
                self._settle_retry_origin(gate_work_item, gate_item)
                queued_downloads += 1
                queued_bytes += candidate.size
                available_concurrency -= 1
                self.store.increment_run_counts(run.id, queued_downloads=1)

            deferred_track_count = len(ordered_track_ids) - processed_track_count
            if deferred_track_count > 0:
                backlog_item = self._item(
                    run_id=run.id,
                    stage="search",
                    action="defer_search_backlog",
                    suffix="search-cap",
                )
                self.store.complete_item(
                    backlog_item.id,
                    status="skipped",
                    reason_code="search_count_cap",
                    detail=(
                        f"Deferred {deferred_track_count} unresolved tracks after "
                        f"{live_searches} live searches and "
                        f"{processed_track_count} bounded lookups; oldest attempts "
                        "resume first on the next run"
                    ),
                )

            if not dry_run:
                affected_playlist_ids.update(
                    self._verify_imports(run.id, settings=settings)
                )
                self._schedule_recipe_work(
                    run_id=run.id,
                    affected_playlist_ids=affected_playlist_ids,
                    quiet_period_seconds=settings.quiet_period_seconds,
                )
            elif affected_playlist_ids:
                self._record_dry_run_recipe_plan(run.id, affected_playlist_ids)

            return self._finish_run(run.id)
        except _AutopilotPaused:
            paused_run = self.store.get_run(run.id)
            if paused_run is None:
                raise RuntimeError(f"Autopilot run disappeared: {run.id}")
            return paused_run
        except Exception as exc:
            logger.exception("Autopilot coordinator failed run_id=%s", run.id)
            return self.store.update_run(
                run.id,
                status=AUTOPILOT_RUN_STATUS_FAILED,
                failed_items=1,
                finished_at=datetime.now(UTC),
                error_detail=str(exc),
            )

    def _refresh_transfers(self, run_id: str, *, settings) -> None:
        item = self._item(
            run_id=run_id,
            stage="transfer",
            action="refresh_active_transfers",
            suffix="active",
        )
        if item.status in _TERMINAL_ITEM_STATUSES:
            return
        work_item = self._retry_work_item(item)
        if work_item is None:
            return
        self.store.mark_item_running(work_item.id)
        try:
            refreshed = self._external_mutation(self.gateway.refresh_active_transfers)
        except LockOwnershipLostError as exc:
            self.store.fail_item_with_retry(
                work_item.id,
                detail=str(exc),
                settings=settings,
            )
            self._settle_retry_origin(work_item, item)
            raise
        except Exception as exc:  # noqa: BLE001 - bounded item retry
            self.store.fail_item_with_retry(
                work_item.id,
                detail=str(exc),
                settings=settings,
            )
            self._settle_retry_origin(work_item, item)
            return
        completed = sum(
            acquisition.status in {"completed", "ingested", "linked"}
            for acquisition in refreshed
        )
        self.store.complete_item(
            work_item.id,
            detail=f"Refreshed {len(refreshed)} unattended transfers",
        )
        self._settle_retry_origin(work_item, item)
        if completed:
            self.store.increment_run_counts(run_id, downloaded_tracks=completed)

    def _verify_imports(self, run_id: str, *, settings) -> set[int]:
        item = self._item(
            run_id=run_id,
            stage="verify",
            action="verify_pending_imports",
            suffix="pending",
        )
        if item.status in _TERMINAL_ITEM_STATUSES:
            return set()
        work_item = self._retry_work_item(item)
        if work_item is None:
            return set()
        self.store.mark_item_running(work_item.id)
        try:
            results = self._external_mutation(self.gateway.verify_pending_imports)
        except LockOwnershipLostError as exc:
            self.store.fail_item_with_retry(
                work_item.id,
                detail=str(exc),
                settings=settings,
            )
            self._settle_retry_origin(work_item, item)
            raise
        except Exception as exc:  # noqa: BLE001 - bounded item retry
            self.store.fail_item_with_retry(
                work_item.id,
                detail=str(exc),
                settings=settings,
            )
            self._settle_retry_origin(work_item, item)
            return set()
        review_count = sum(not result.decision.accepted for result in results)
        linked_count = sum(result.acquisition.status == "linked" for result in results)
        self.store.complete_item(
            work_item.id,
            detail=(
                f"Verified {len(results)} imports; linked {linked_count}; "
                f"review {review_count}"
            ),
        )
        self._settle_retry_origin(work_item, item)
        for result in results:
            result_item = self._item(
                run_id=run_id,
                stage="verify",
                action="post_import_verification",
                suffix=f"acquisition:{result.acquisition.id}",
                streaming_track_id=result.acquisition.streaming_track_id,
                acquisition_id=result.acquisition.id,
            )
            self.store.complete_item(
                result_item.id,
                status="succeeded" if result.decision.accepted else "review",
                reason_code=(
                    None if result.decision.accepted else result.decision.reason_code
                ),
                detail=result.decision.detail,
            )
            if result.decision.accepted:
                self._observe_analysis(
                    run_id=run_id,
                    acquisition_id=result.acquisition.id,
                    streaming_track_id=result.acquisition.streaming_track_id,
                    settings=settings,
                )
        if results:
            self.store.increment_run_counts(run_id, ingested_tracks=len(results))
        # Link impact is regenerated only after sonic analysis reaches ready.
        # This avoids consuming the quiet-period debounce with an ineligible
        # pending track.
        return set()

    def _schedule_recipe_work(
        self,
        *,
        run_id: str,
        affected_playlist_ids: set[int],
        quiet_period_seconds: int,
    ) -> None:
        due_at = datetime.now(UTC) + timedelta(seconds=quiet_period_seconds)
        for recipe_id in self.recipe_adapter.affected_recipe_ids(affected_playlist_ids):
            self.store.upsert_recipe_debounce(
                run_id=run_id,
                recipe_id=recipe_id,
                next_attempt_at=due_at,
                detail=(
                    f"Recipe regeneration debounced for {quiet_period_seconds} seconds"
                ),
            )

    def _process_due_recipe_work(self, *, settings, current_run_id: str) -> None:
        for item in self.store.due_retry_items():
            if item.action != "regenerate_recipe":
                continue
            if item.recipe_id is None:
                self.store.complete_item(
                    item.id,
                    status="skipped",
                    reason_code="recipe_deleted",
                    detail="Skipped pending regeneration because its recipe was deleted",
                )
                self._finish_run(item.run_id)
                continue
            self._pause_checkpoint(current_run_id, f"recipe:{item.recipe_id}")
            self.store.mark_item_running(item.id)
            try:
                result = self._external_mutation(
                    lambda: self.recipe_adapter.regenerate(item.recipe_id)
                )
            except LockOwnershipLostError as exc:
                self.store.fail_item_with_retry(
                    item.id,
                    detail=str(exc),
                    settings=settings,
                )
                self._finish_run(item.run_id)
                raise
            except Exception as exc:  # noqa: BLE001 - bounded item retry
                self.store.fail_item_with_retry(
                    item.id,
                    detail=str(exc),
                    settings=settings,
                )
                continue
            self.store.complete_item(
                item.id,
                detail=f"Generated snapshot {result.generation_run_id}",
            )
            increments = {"regenerated_recipes": 1}
            if result.export_result is not None:
                increments["refreshed_exports"] = 1
            self.store.increment_run_counts(item.run_id, **increments)
            self._finish_run(item.run_id)

    def _process_due_analysis_work(self, *, settings, current_run_id: str) -> None:
        for item in self.store.due_retry_items():
            if item.action != "observe_track_analysis" or item.acquisition_id is None:
                continue
            self._pause_checkpoint(
                current_run_id,
                f"analysis:{item.acquisition_id}",
            )
            self._observe_analysis_item(item, settings=settings)
            self._finish_run(item.run_id)

    def _observe_analysis(
        self,
        *,
        run_id: str,
        acquisition_id: str,
        streaming_track_id: int,
        settings,
    ) -> None:
        item = self._item(
            run_id=run_id,
            stage="analyze",
            action="observe_track_analysis",
            suffix=f"acquisition:{acquisition_id}",
            acquisition_id=acquisition_id,
            streaming_track_id=streaming_track_id,
        )
        if item.status in _TERMINAL_ITEM_STATUSES:
            return
        self._observe_analysis_item(item, settings=settings)

    def _observe_analysis_item(
        self,
        item: AutopilotRunItemRecord,
        *,
        settings,
    ) -> None:
        if item.acquisition_id is None:
            raise RuntimeError("Analysis observer item has no acquisition")
        self.store.mark_item_running(item.id)
        try:
            state = self.gateway.analysis_state(item.acquisition_id)
        except Exception as exc:  # noqa: BLE001 - bounded observer retry
            self.store.fail_item_with_retry(
                item.id,
                detail=str(exc),
                settings=settings,
            )
            return
        if state.status == SONIC_FEATURE_STATUS_READY:
            self.store.complete_item(
                item.id,
                detail=(f"Local track {state.local_track_id} has ready sonic features"),
            )
            self.store.increment_run_counts(item.run_id, analyzed_tracks=1)
            if item.streaming_track_id is not None:
                affected_playlist_ids = set(
                    self.gateway.affected_playlist_ids(item.streaming_track_id)
                )
                if affected_playlist_ids:
                    self._schedule_recipe_work(
                        run_id=item.run_id,
                        affected_playlist_ids=affected_playlist_ids,
                        quiet_period_seconds=settings.quiet_period_seconds,
                    )
            return
        if state.status == SONIC_FEATURE_STATUS_FAILED:
            self.store.complete_item(
                item.id,
                status="review",
                reason_code="analysis_failed",
                detail=(f"Local track {state.local_track_id} sonic analysis failed"),
            )
            return
        pending_status = state.status or "missing"
        self.store.fail_item_with_retry(
            item.id,
            detail=(
                f"Local track {state.local_track_id} sonic analysis is "
                f"{pending_status}; checking again after backoff"
            ),
            settings=settings,
        )

    def _retry_work_item(
        self,
        current_item: AutopilotRunItemRecord,
    ) -> AutopilotRunItemRecord | None:
        pending = self.store.pending_retry_item(
            action=current_item.action,
            playlist_id=current_item.playlist_id,
            streaming_track_id=current_item.streaming_track_id,
            exclude_item_id=current_item.id,
        )
        if pending is None:
            return current_item
        now = datetime.now(UTC)
        next_attempt_at = pending.next_attempt_at
        if next_attempt_at is not None and _as_utc(next_attempt_at) > now:
            self.store.complete_item(
                current_item.id,
                status="skipped",
                reason_code="retry_backoff_active",
                detail=(
                    f"Prior {pending.action} attempt {pending.attempt_count} is "
                    f"backing off until {_as_utc(next_attempt_at).isoformat()}"
                ),
            )
            return None
        self.store.complete_item(
            current_item.id,
            status="skipped",
            reason_code="retry_carried_forward",
            detail=(
                f"Resumed prior item {pending.id} at attempt "
                f"{pending.attempt_count + 1}"
            ),
        )
        return pending

    def _settle_retry_origin(
        self,
        work_item: AutopilotRunItemRecord,
        current_item: AutopilotRunItemRecord,
    ) -> None:
        if work_item.run_id != current_item.run_id:
            self._finish_run(work_item.run_id)

    def _pause_checkpoint(self, run_id: str, point: str) -> None:
        if not self.store.get_settings().paused:
            return
        item = self._item(
            run_id=run_id,
            stage="control",
            action="global_pause",
            suffix=point,
        )
        self.store.complete_item(
            item.id,
            status="skipped",
            reason_code="global_pause",
            detail=f"Global pause stopped autopilot at {point}",
        )
        self.store.update_run(
            run_id,
            status=AUTOPILOT_RUN_STATUS_PAUSED,
            finished_at=datetime.now(UTC),
            error_detail=None,
        )
        raise _AutopilotPaused

    def _external_mutation(self, operation):
        self.lease_checkpoint()
        result = operation()
        self.lease_checkpoint()
        return result

    def _record_assist_review(
        self,
        *,
        run_id: str,
        playlist_id: int,
        streaming_track_id: int,
        acquisition_id: str,
    ) -> None:
        item = self._item(
            run_id=run_id,
            stage="review",
            action="assist_search_result",
            suffix=f"track:{streaming_track_id}",
            playlist_id=playlist_id,
            streaming_track_id=streaming_track_id,
            acquisition_id=acquisition_id,
        )
        self.store.complete_item(
            item.id,
            status="review",
            reason_code="assist_only",
            detail="Assist/search never queues a download without manual approval",
        )
        self.store.increment_run_counts(run_id, review_items=1)

    def _gate_item(
        self,
        *,
        run_id: str,
        playlist_id: int,
        streaming_track_id: int,
        acquisition_id: str,
        decision: CandidateGateDecision,
    ) -> AutopilotRunItemRecord:
        return self._item(
            run_id=run_id,
            stage="acquire",
            action="gate_and_queue_download",
            suffix=f"track:{streaming_track_id}",
            playlist_id=playlist_id,
            streaming_track_id=streaming_track_id,
            acquisition_id=acquisition_id,
            candidate_id=(
                decision.candidate.id if decision.candidate is not None else None
            ),
            identity_confidence=decision.identity_confidence,
            version_confidence=decision.version_confidence,
            quality_score=decision.quality_score,
            runner_up_margin=decision.runner_up_margin,
            expected_duration_ms=decision.expected_duration_ms,
            candidate_duration_ms=decision.candidate_duration_ms,
        )

    def _record_dry_run_recipe_plan(
        self, run_id: str, affected_playlist_ids: set[int]
    ) -> None:
        for recipe_id in self.recipe_adapter.affected_recipe_ids(affected_playlist_ids):
            item = self._item(
                run_id=run_id,
                stage="regenerate",
                action="regenerate_recipe",
                suffix=f"recipe:{recipe_id}",
                recipe_id=recipe_id,
            )
            self.store.complete_item(
                item.id,
                status="skipped",
                reason_code="dry_run_regeneration_suppressed",
                detail="Dry-run suppressed recipe regeneration and configured export",
            )

    def _item(
        self,
        *,
        run_id: str,
        stage: str,
        action: str,
        suffix: str,
        **evidence: object,
    ) -> AutopilotRunItemRecord:
        item, _ = self.store.get_or_create_run_item(
            action=action,
            idempotency_key=f"{run_id}:{stage}:{action}:{suffix}",
            run_id=run_id,
            stage=stage,
            **evidence,
        )
        return item

    def _finish_run(self, run_id: str) -> AutopilotRunRecord:
        items = self.store.list_run_items(run_id)
        failed = sum(item.status == AUTOPILOT_ITEM_STATUS_FAILED for item in items)
        review = sum(item.status == AUTOPILOT_ITEM_STATUS_REVIEW for item in items)
        waiting = sum(item.status == AUTOPILOT_ITEM_STATUS_RETRY_WAIT for item in items)
        status = (
            AUTOPILOT_RUN_STATUS_PARTIAL
            if failed or review or waiting
            else AUTOPILOT_RUN_STATUS_SUCCEEDED
        )
        return self.store.update_run(
            run_id,
            status=status,
            failed_items=failed,
            review_items=review,
            finished_at=datetime.now(UTC),
        )


def _download_cap_reason(
    *,
    available_concurrency: int,
    candidate_size: int,
    max_downloads: int,
    max_storage_bytes: int,
    queued_bytes: int,
    queued_downloads: int,
) -> str | None:
    if available_concurrency <= 0:
        return "concurrency_cap"
    if queued_downloads >= max_downloads:
        return "download_count_cap"
    if candidate_size > max_storage_bytes - queued_bytes:
        return "storage_cap"
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
