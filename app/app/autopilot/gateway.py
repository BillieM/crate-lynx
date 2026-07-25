from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.autopilot.gates import ImportVerificationDecision, verify_imported_audio
from app.links.impact import (
    affected_sync_or_automation_playlist_ids_for_streaming_tracks,
)
from app.relationships.resolver import StreamingRelationshipResolver
from app.sonic.models import sonic_track_features_table
from app.soulseek.client import SlskdClient
from app.soulseek.config import load_slskd_config
from app.soulseek.jobs import (
    enqueue_soulseek_candidate_now,
    refresh_soulseek_acquisition,
    search_missing_track,
)
from app.soulseek.models import (
    SOULSEEK_STATUS_COMPLETED,
    SOULSEEK_STATUS_DOWNLOADING,
    SOULSEEK_STATUS_FAILED,
    SOULSEEK_STATUS_INGESTED,
    SOULSEEK_STATUS_LINK_FAILED,
    SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_VERIFICATION_PENDING,
    SoulseekAcquisitionRecord,
    SoulseekCandidateRecord,
    StreamingTrackForSoulseek,
)
from app.soulseek.store import SoulseekStore
from app.streaming.models import (
    PLAYLIST_AUTOMATION_LEVEL_OFF,
    StreamingPlaylistSummary,
    playlist_membership_table,
    streaming_tracks_table,
)
from app.streaming.store import StreamingAccountStore


@dataclass(frozen=True, slots=True)
class PlaylistRefreshResult:
    playlist_id: int
    changed: bool
    membership_count: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    acquisition: SoulseekAcquisitionRecord
    candidates: list[SoulseekCandidateRecord]
    download_suppressed_reason: str | None = None
    performed_search: bool = True


@dataclass(frozen=True, slots=True)
class VerificationResult:
    acquisition: SoulseekAcquisitionRecord
    decision: ImportVerificationDecision
    affected_playlist_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AnalysisState:
    local_track_id: int | None
    status: str | None


def _noop_checkpoint() -> None:
    pass


class AutopilotWorkflowGateway(Protocol):
    def selected_playlists(self) -> list[StreamingPlaylistSummary]: ...

    def refresh_playlist(self, playlist_id: int) -> PlaylistRefreshResult: ...

    def unresolved_tracks(
        self, playlist_id: int
    ) -> list[StreamingTrackForSoulseek]: ...

    def search_track(
        self,
        *,
        automation_run_id: str,
        streaming_track_id: int,
        unattended: bool,
    ) -> SearchResult: ...

    def active_unattended_downloads(self) -> int: ...

    def queue_candidate(self, candidate_id: str) -> SoulseekAcquisitionRecord: ...

    def refresh_active_transfers(self) -> list[SoulseekAcquisitionRecord]: ...

    def verify_pending_imports(self) -> list[VerificationResult]: ...

    def analysis_state(self, acquisition_id: str) -> AnalysisState: ...

    def affected_playlist_ids(self, streaming_track_id: int) -> tuple[int, ...]: ...


@dataclass(slots=True)
class ExistingServicesGateway:
    engine: Engine
    lease_checkpoint: Callable[[], None] = _noop_checkpoint

    def selected_playlists(self) -> list[StreamingPlaylistSummary]:
        return [
            playlist
            for playlist in StreamingAccountStore(engine=self.engine).list_playlists()
            if playlist.automation_level != PLAYLIST_AUTOMATION_LEVEL_OFF
        ]

    def refresh_playlist(self, playlist_id: int) -> PlaylistRefreshResult:
        before = self._membership_ids(playlist_id)
        self.lease_checkpoint()
        StreamingAccountStore(engine=self.engine).sync_youtube_music_playlist(
            playlist_id=playlist_id
        )
        self.lease_checkpoint()
        after = self._membership_ids(playlist_id)
        return PlaylistRefreshResult(
            playlist_id=playlist_id,
            changed=before != after,
            membership_count=len(after),
        )

    def unresolved_tracks(self, playlist_id: int) -> list[StreamingTrackForSoulseek]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        streaming_tracks_table.c.id,
                        streaming_tracks_table.c.title,
                        streaming_tracks_table.c.artist,
                        streaming_tracks_table.c.album,
                        streaming_tracks_table.c.duration_ms,
                    )
                    .select_from(
                        playlist_membership_table.join(
                            streaming_tracks_table,
                            streaming_tracks_table.c.id
                            == playlist_membership_table.c.streaming_track_id,
                        )
                    )
                    .where(playlist_membership_table.c.playlist_id == playlist_id)
                    .order_by(
                        playlist_membership_table.c.position.asc(),
                        streaming_tracks_table.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )
            resolver = StreamingRelationshipResolver(connection)
            return [
                StreamingTrackForSoulseek(
                    id=int(row["id"]),
                    title=row["title"],
                    artist=row["artist"],
                    album=row["album"],
                    duration_ms=row["duration_ms"],
                )
                for row in rows
                if resolver.resolve(int(row["id"])) is None
            ]

    def search_track(
        self,
        *,
        automation_run_id: str,
        streaming_track_id: int,
        unattended: bool,
    ) -> SearchResult:
        store = SoulseekStore(engine=self.engine)
        if unattended:
            self.lease_checkpoint()
            acquisition = store.create_autopilot_search_acquisition(
                automation_run_id=automation_run_id,
                streaming_track_id=streaming_track_id,
            )
            self.lease_checkpoint()
            if acquisition.status in {
                SOULSEEK_STATUS_QUEUED,
                SOULSEEK_STATUS_DOWNLOADING,
                SOULSEEK_STATUS_COMPLETED,
                SOULSEEK_STATUS_INGESTED,
                SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
            } or (
                acquisition.status
                in {SOULSEEK_STATUS_LINK_FAILED, SOULSEEK_STATUS_FAILED}
                and (
                    acquisition.local_track_id is not None
                    or acquisition.completed_source_path is not None
                )
            ):
                review_required = acquisition.status in {
                    SOULSEEK_STATUS_LINK_FAILED,
                    SOULSEEK_STATUS_FAILED,
                }
                return SearchResult(
                    acquisition=acquisition,
                    candidates=store.list_candidates(acquisition.id),
                    download_suppressed_reason=(
                        "unattended_acquisition_review_required"
                        if review_required
                        else "unattended_acquisition_in_flight"
                    ),
                    performed_search=False,
                )
        else:
            latest = store.latest_summaries_for_tracks([streaming_track_id]).get(
                streaming_track_id
            )
            if latest is not None and latest.candidate_count > 0:
                existing = store.get_acquisition(latest.id)
                if existing is not None:
                    return SearchResult(
                        acquisition=existing,
                        candidates=store.list_candidates(existing.id),
                        performed_search=False,
                    )
            self.lease_checkpoint()
            acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
            self.lease_checkpoint()

        performed_search = False
        if acquisition.candidate_count == 0:
            self.lease_checkpoint()
            search_missing_track(acquisition.id)
            self.lease_checkpoint()
            performed_search = True
            acquisition = store.get_acquisition(acquisition.id)
            if acquisition is None:
                raise RuntimeError("Soulseek acquisition disappeared after search")
        return SearchResult(
            acquisition=acquisition,
            candidates=store.list_candidates(acquisition.id),
            performed_search=performed_search,
        )

    def active_unattended_downloads(self) -> int:
        return len(
            SoulseekStore(engine=self.engine).list_unattended_acquisitions(
                statuses={SOULSEEK_STATUS_QUEUED, SOULSEEK_STATUS_DOWNLOADING}
            )
        )

    def queue_candidate(self, candidate_id: str) -> SoulseekAcquisitionRecord:
        self.lease_checkpoint()
        acquisition = enqueue_soulseek_candidate_now(
            candidate_id,
            client=SlskdClient(load_slskd_config()),
            store=SoulseekStore(engine=self.engine),
        )
        self.lease_checkpoint()
        return acquisition

    def refresh_active_transfers(self) -> list[SoulseekAcquisitionRecord]:
        store = SoulseekStore(engine=self.engine)
        active = store.list_unattended_acquisitions(
            statuses={SOULSEEK_STATUS_QUEUED, SOULSEEK_STATUS_DOWNLOADING}
        )
        refreshed: list[SoulseekAcquisitionRecord] = []
        for acquisition in active:
            self.lease_checkpoint()
            refresh_soulseek_acquisition(acquisition.id)
            self.lease_checkpoint()
            updated = store.get_acquisition(acquisition.id)
            if updated is not None:
                refreshed.append(updated)
        return refreshed

    def verify_pending_imports(self) -> list[VerificationResult]:
        store = SoulseekStore(engine=self.engine)
        pending = store.list_unattended_acquisitions(
            statuses={SOULSEEK_STATUS_INGESTED},
            verification_status=SOULSEEK_VERIFICATION_PENDING,
        )
        results: list[VerificationResult] = []
        library_root = Path(os.environ.get("LIBRARY_ROOT", "/nas/media/music"))
        for acquisition in pending:
            if acquisition.selected_candidate_id is None:
                decision = ImportVerificationDecision(
                    accepted=False,
                    reason_code="candidate_missing",
                    detail="Ingested unattended acquisition has no selected candidate",
                )
                self.lease_checkpoint()
                store.mark_unattended_verification_review(
                    acquisition.id, detail=decision.detail
                )
                self.lease_checkpoint()
                updated = store.get_acquisition(acquisition.id) or acquisition
                results.append(
                    VerificationResult(
                        acquisition=updated,
                        decision=decision,
                        affected_playlist_ids=(),
                    )
                )
                continue
            candidate = store.get_candidate(acquisition.selected_candidate_id)
            if candidate is None:
                decision = ImportVerificationDecision(
                    accepted=False,
                    reason_code="candidate_missing",
                    detail="Selected unattended candidate no longer exists",
                )
                self.lease_checkpoint()
                store.mark_unattended_verification_review(
                    acquisition.id, detail=decision.detail
                )
                self.lease_checkpoint()
                updated = store.get_acquisition(acquisition.id) or acquisition
                results.append(
                    VerificationResult(
                        acquisition=updated,
                        decision=decision,
                        affected_playlist_ids=(),
                    )
                )
                continue
            decision = verify_imported_audio(
                acquisition=acquisition,
                candidate=candidate,
                engine=self.engine,
                library_root=library_root,
            )
            if decision.accepted:
                self.lease_checkpoint()
                linked = store.mark_unattended_verified_and_auto_link(
                    acquisition.id,
                    detail=decision.detail,
                )
                self.lease_checkpoint()
                results.append(
                    VerificationResult(
                        acquisition=linked.acquisition,
                        decision=decision,
                        affected_playlist_ids=linked.affected_playlist_ids,
                    )
                )
            else:
                self.lease_checkpoint()
                store.mark_unattended_verification_review(
                    acquisition.id,
                    detail=decision.detail,
                    failed=decision.reason_code
                    in {"corrupt_or_truncated", "unreadable_audio"},
                )
                self.lease_checkpoint()
                updated = store.get_acquisition(acquisition.id) or acquisition
                results.append(
                    VerificationResult(
                        acquisition=updated,
                        decision=decision,
                        affected_playlist_ids=(),
                    )
                )
        return results

    def analysis_state(self, acquisition_id: str) -> AnalysisState:
        acquisition = SoulseekStore(engine=self.engine).get_acquisition(acquisition_id)
        if acquisition is None or acquisition.local_track_id is None:
            return AnalysisState(local_track_id=None, status=None)
        with self.engine.connect() as connection:
            status = connection.execute(
                select(sonic_track_features_table.c.status).where(
                    sonic_track_features_table.c.local_track_id
                    == acquisition.local_track_id
                )
            ).scalar_one_or_none()
        return AnalysisState(
            local_track_id=acquisition.local_track_id,
            status=str(status) if status is not None else None,
        )

    def affected_playlist_ids(self, streaming_track_id: int) -> tuple[int, ...]:
        with self.engine.connect() as connection:
            return affected_sync_or_automation_playlist_ids_for_streaming_tracks(
                connection,
                (streaming_track_id,),
            )

    def _membership_ids(self, playlist_id: int) -> tuple[int, ...]:
        with self.engine.connect() as connection:
            return tuple(
                int(value)
                for value in connection.execute(
                    select(playlist_membership_table.c.streaming_track_id)
                    .where(playlist_membership_table.c.playlist_id == playlist_id)
                    .order_by(playlist_membership_table.c.position.asc())
                ).scalars()
            )
