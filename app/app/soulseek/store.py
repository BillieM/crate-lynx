from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
import re
import uuid

from sqlalchemy import delete, desc, func, insert, select, update
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.links.store import final_links_table
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_PENDING,
    suggested_links_table,
)
from app.m3u.jobs import affected_full_sync_playlist_ids_for_streaming_tracks
from app.relationships.resolver import StreamingRelationshipResolver
from app.soulseek.models import (
    MissingTrackSoulseekSummary,
    SoulseekAutoLinkResult,
    SOULSEEK_STATUS_CANDIDATES_FOUND,
    SOULSEEK_STATUS_COMPLETED,
    SOULSEEK_STATUS_DOWNLOADING,
    SOULSEEK_STATUS_FAILED,
    SOULSEEK_STATUS_INGESTED,
    SOULSEEK_STATUS_LINK_FAILED,
    SOULSEEK_STATUS_LINKED,
    SOULSEEK_STATUS_NO_CANDIDATES,
    SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_STATUS_SEARCHING,
    SoulseekAcquisitionRecord,
    SoulseekCandidateRecord,
    SoulseekQueueItemRecord,
    StreamingTrackForSoulseek,
    soulseek_acquisitions_table,
    soulseek_candidates_table,
)
from app.soulseek.ranking import RankedSoulseekCandidate
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


class SoulseekAcquisitionNotFoundError(ValueError):
    pass


class SoulseekCandidateNotFoundError(ValueError):
    pass


class SoulseekCandidateConflictError(ValueError):
    pass


class SoulseekAutoLinkConflictError(ValueError):
    pass


_DESTINATION_MARKER_RE = re.compile(
    r"^(?P<streaming_track_id>\d+)-"
    r"(?P<acquisition_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_ACTIVE_SEARCH_STATUSES = {
    SOULSEEK_STATUS_SEARCHING,
    SOULSEEK_STATUS_CANDIDATES_FOUND,
    SOULSEEK_STATUS_NO_CANDIDATES,
    SOULSEEK_STATUS_FAILED,
    SOULSEEK_STATUS_LINK_FAILED,
}
_QUEUE_REVIEW_STATUSES = {SOULSEEK_STATUS_CANDIDATES_FOUND}
_QUEUE_DOWNLOADING_STATUSES = {
    SOULSEEK_STATUS_SEARCHING,
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_STATUS_DOWNLOADING,
    SOULSEEK_STATUS_COMPLETED,
    SOULSEEK_STATUS_INGESTED,
    SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
}
_QUEUE_FAILED_STATUSES = {SOULSEEK_STATUS_FAILED, SOULSEEK_STATUS_LINK_FAILED}
_SOURCE_PATH_MATCH_STATUSES = {
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_STATUS_DOWNLOADING,
    SOULSEEK_STATUS_COMPLETED,
}


class SoulseekStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def get_streaming_track(
        self,
        streaming_track_id: int,
    ) -> StreamingTrackForSoulseek | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        streaming_tracks_table.c.id,
                        streaming_tracks_table.c.title,
                        streaming_tracks_table.c.artist,
                        streaming_tracks_table.c.album,
                        streaming_tracks_table.c.duration_ms,
                    ).where(streaming_tracks_table.c.id == streaming_track_id)
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None
        return StreamingTrackForSoulseek(
            id=row["id"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            duration_ms=row["duration_ms"],
        )

    def create_or_reset_search_acquisition(
        self,
        streaming_track_id: int,
    ) -> SoulseekAcquisitionRecord:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            latest = (
                connection.execute(
                    select(soulseek_acquisitions_table)
                    .where(
                        soulseek_acquisitions_table.c.streaming_track_id
                        == streaming_track_id
                    )
                    .order_by(
                        desc(soulseek_acquisitions_table.c.created_at),
                        desc(soulseek_acquisitions_table.c.id),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if latest is not None and latest["status"] in _ACTIVE_SEARCH_STATUSES:
                acquisition_id = latest["id"]
                connection.execute(
                    delete(soulseek_candidates_table).where(
                        soulseek_candidates_table.c.acquisition_id == acquisition_id
                    )
                )
                connection.execute(
                    update(soulseek_acquisitions_table)
                    .where(soulseek_acquisitions_table.c.id == acquisition_id)
                    .values(
                        status=SOULSEEK_STATUS_SEARCHING,
                        search_text=None,
                        fallback_search_text=None,
                        slskd_search_id=None,
                        slskd_fallback_search_id=None,
                        candidate_count=0,
                        selected_candidate_id=None,
                        slskd_batch_id=None,
                        destination=None,
                        completed_source_path=None,
                        slskd_completed_event_id=None,
                        local_track_id=None,
                        final_link_id=None,
                        enqueue_job_id=None,
                        refresh_job_id=None,
                        error_detail=None,
                        link_error_detail=None,
                        searched_at=None,
                        queued_at=None,
                        completed_at=None,
                        ingested_at=None,
                        proposal_available_at=None,
                        linked_at=None,
                        failed_at=None,
                        updated_at=now,
                    )
                )
            else:
                acquisition_id = str(uuid.uuid4())
                connection.execute(
                    insert(soulseek_acquisitions_table).values(
                        id=acquisition_id,
                        streaming_track_id=streaming_track_id,
                        status=SOULSEEK_STATUS_SEARCHING,
                        candidate_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                )

            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(row)

    def set_search_job_id(self, acquisition_id: str, job_id: str | None) -> None:
        self._update_acquisition(acquisition_id, job_id=job_id)

    def set_enqueue_job_id(self, acquisition_id: str, job_id: str | None) -> None:
        self._update_acquisition(acquisition_id, enqueue_job_id=job_id)

    def set_refresh_job_id(self, acquisition_id: str, job_id: str | None) -> None:
        self._update_acquisition(acquisition_id, refresh_job_id=job_id)

    def get_acquisition(self, acquisition_id: str) -> SoulseekAcquisitionRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _acquisition_record(row) if row is not None else None

    def get_candidate(self, candidate_id: str) -> SoulseekCandidateRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(soulseek_candidates_table).where(
                        soulseek_candidates_table.c.id == candidate_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _candidate_record(row) if row is not None else None

    def list_candidates(self, acquisition_id: str) -> list[SoulseekCandidateRecord]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(soulseek_candidates_table)
                    .where(soulseek_candidates_table.c.acquisition_id == acquisition_id)
                    .order_by(
                        soulseek_candidates_table.c.score.desc(),
                        soulseek_candidates_table.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )
        return [_candidate_record(row) for row in rows]

    def list_queue_items(
        self,
        *,
        filter_key: str = "all",
        candidate_limit: int = 5,
    ) -> list[SoulseekQueueItemRecord]:
        with self._engine.connect() as connection:
            latest_acquisitions = _latest_acquisitions(connection)
            track_ids = set(latest_acquisitions)
            if filter_key in {"all", "needs_search"}:
                track_ids.update(
                    _missing_unsearched_tracks(
                        connection,
                        excluded_streaming_track_ids=latest_acquisitions.keys(),
                    )
                )

            tracks = _streaming_tracks(connection, track_ids)
            playlist_usage = _playlist_usage(connection, track_ids)
            candidate_map = _candidate_map(
                connection,
                [acquisition.id for acquisition in latest_acquisitions.values()],
                limit=candidate_limit,
            )
            selected_candidates = _selected_candidate_map(
                connection,
                latest_acquisitions.values(),
            )

        items: list[SoulseekQueueItemRecord] = []
        for track_id, track in tracks.items():
            acquisition = latest_acquisitions.get(track_id)
            if not _queue_filter_matches(filter_key, acquisition):
                continue
            playlist_ids, playlist_titles = playlist_usage.get(track_id, ([], []))
            items.append(
                SoulseekQueueItemRecord(
                    streaming_track=track,
                    playlist_count=len(playlist_ids),
                    playlist_ids=playlist_ids,
                    playlist_titles=playlist_titles,
                    acquisition=acquisition,
                    candidates=(
                        candidate_map.get(acquisition.id, [])
                        if acquisition is not None
                        else []
                    ),
                    selected_candidate=(
                        selected_candidates.get(acquisition.selected_candidate_id)
                        if acquisition is not None
                        and acquisition.selected_candidate_id is not None
                        else None
                    ),
                )
            )

        return sorted(items, key=_queue_sort_key)

    def get_queue_item_for_acquisition(
        self,
        acquisition_id: str,
    ) -> SoulseekQueueItemRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            acquisition = _acquisition_record(row)
            track = _streaming_tracks(
                connection,
                [acquisition.streaming_track_id],
            ).get(acquisition.streaming_track_id)
            if track is None:
                return None
            playlist_ids, playlist_titles = _playlist_usage(
                connection,
                [acquisition.streaming_track_id],
            ).get(acquisition.streaming_track_id, ([], []))
            candidates = _candidate_map(
                connection,
                [acquisition_id],
                limit=1000,
            ).get(acquisition_id, [])
            selected_candidate = (
                _selected_candidate_map(connection, [acquisition]).get(
                    acquisition.selected_candidate_id
                )
                if acquisition.selected_candidate_id is not None
                else None
            )
        return SoulseekQueueItemRecord(
            streaming_track=track,
            playlist_count=len(playlist_ids),
            playlist_ids=playlist_ids,
            playlist_titles=playlist_titles,
            acquisition=acquisition,
            candidates=candidates,
            selected_candidate=selected_candidate,
        )

    def persist_search_results(
        self,
        *,
        acquisition_id: str,
        candidates: list[RankedSoulseekCandidate],
        fallback_search_id: str | None,
        fallback_search_text: str | None,
        search_id: str,
        search_text: str,
    ) -> SoulseekAcquisitionRecord:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            connection.execute(
                delete(soulseek_candidates_table).where(
                    soulseek_candidates_table.c.acquisition_id == acquisition_id
                )
            )
            if candidates:
                connection.execute(
                    insert(soulseek_candidates_table),
                    [
                        {
                            "id": str(uuid.uuid4()),
                            "acquisition_id": acquisition_id,
                            "slskd_search_id": candidate.slskd_search_id,
                            "username": candidate.username,
                            "filename": candidate.filename,
                            "size": candidate.size,
                            "extension": candidate.extension,
                            "duration_seconds": candidate.duration_seconds,
                            "bit_rate": candidate.bit_rate,
                            "bit_depth": candidate.bit_depth,
                            "sample_rate": candidate.sample_rate,
                            "is_variable_bit_rate": candidate.is_variable_bit_rate,
                            "has_free_upload_slot": candidate.has_free_upload_slot,
                            "queue_length": candidate.queue_length,
                            "upload_speed": candidate.upload_speed,
                            "score": candidate.score,
                            "created_at": now,
                        }
                        for candidate in candidates
                    ],
                )
            status = (
                SOULSEEK_STATUS_CANDIDATES_FOUND
                if candidates
                else SOULSEEK_STATUS_NO_CANDIDATES
            )
            connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == acquisition_id)
                .values(
                    status=status,
                    search_text=search_text,
                    fallback_search_text=fallback_search_text,
                    slskd_search_id=search_id,
                    slskd_fallback_search_id=fallback_search_id,
                    candidate_count=len(candidates),
                    error_detail=None,
                    searched_at=now,
                    failed_at=None,
                    updated_at=now,
                )
            )
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(row)

    def mark_failed(self, acquisition_id: str, error_detail: str) -> None:
        now = datetime.now(UTC)
        self._update_acquisition(
            acquisition_id,
            status=SOULSEEK_STATUS_FAILED,
            error_detail=error_detail[:4000],
            failed_at=now,
        )

    def mark_download_approval_queued(
        self,
        *,
        acquisition_id: str,
        candidate_id: str,
        job_id: str,
    ) -> SoulseekAcquisitionRecord:
        now = datetime.now(UTC)
        return self._update_acquisition(
            acquisition_id,
            selected_candidate_id=candidate_id,
            slskd_batch_id=None,
            destination=None,
            completed_source_path=None,
            slskd_completed_event_id=None,
            enqueue_job_id=job_id,
            status=SOULSEEK_STATUS_QUEUED,
            error_detail=None,
            link_error_detail=None,
            queued_at=now,
            completed_at=None,
            ingested_at=None,
            proposal_available_at=None,
            linked_at=None,
            failed_at=None,
        )

    def mark_enqueued(
        self,
        *,
        acquisition_id: str,
        batch_id: str,
        candidate_id: str,
        destination: str | None,
        error_detail: str | None = None,
    ) -> SoulseekAcquisitionRecord:
        now = datetime.now(UTC)
        return self._update_acquisition(
            acquisition_id,
            selected_candidate_id=candidate_id,
            slskd_batch_id=batch_id,
            destination=destination,
            completed_source_path=None,
            slskd_completed_event_id=None,
            status=SOULSEEK_STATUS_QUEUED,
            error_detail=error_detail,
            link_error_detail=None,
            queued_at=now,
            failed_at=None,
        )

    def mark_transfer_status(
        self,
        acquisition_id: str,
        *,
        error_detail: str | None,
        status: str,
    ) -> SoulseekAcquisitionRecord:
        now = datetime.now(UTC)
        values: dict[str, object] = {
            "status": status,
            "error_detail": error_detail,
        }
        if status == SOULSEEK_STATUS_COMPLETED:
            values["completed_at"] = now
        if status == SOULSEEK_STATUS_FAILED:
            values["failed_at"] = now
        return self._update_acquisition(acquisition_id, **values)

    def mark_download_completed_from_webhook(
        self,
        *,
        event_id: str,
        source_path: str,
        transfer_id: str,
    ) -> SoulseekAcquisitionRecord | None:
        now = datetime.now(UTC)
        transfer_reference = _stored_transfer_reference(transfer_id)
        normalized_source_path = _normalize_source_path_for_match(source_path)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table)
                    .where(
                        soulseek_acquisitions_table.c.slskd_batch_id
                        == transfer_reference
                    )
                    .order_by(
                        desc(soulseek_acquisitions_table.c.updated_at),
                        desc(soulseek_acquisitions_table.c.created_at),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            values: dict[str, object | None] = {
                "completed_source_path": normalized_source_path,
                "slskd_completed_event_id": event_id,
                "error_detail": None,
                "updated_at": now,
            }
            if row["completed_at"] is None:
                values["completed_at"] = now
            if row["status"] in {
                SOULSEEK_STATUS_SEARCHING,
                SOULSEEK_STATUS_QUEUED,
                SOULSEEK_STATUS_DOWNLOADING,
                SOULSEEK_STATUS_FAILED,
            }:
                values["status"] = SOULSEEK_STATUS_COMPLETED
                values["failed_at"] = None

            connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == row["id"])
                .values(**values)
            )
            updated_row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == row["id"]
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(updated_row)

    def mark_ingested_from_source_path(
        self,
        *,
        local_track_id: int,
        source_path: str,
    ) -> SoulseekAcquisitionRecord | None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            parsed = _acquisition_reference_from_source_path(connection, source_path)
            if parsed is None:
                return None

            streaming_track_id, acquisition_id = parsed
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id,
                        soulseek_acquisitions_table.c.streaming_track_id
                        == streaming_track_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == acquisition_id)
                .values(
                    status=SOULSEEK_STATUS_INGESTED,
                    local_track_id=local_track_id,
                    ingested_at=now,
                    updated_at=now,
                )
            )
            updated_row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(updated_row)

    def mark_ingested_and_auto_link_from_source_path(
        self,
        *,
        local_track_id: int,
        source_path: str,
    ) -> SoulseekAutoLinkResult | None:
        now = datetime.now(UTC)
        affected_playlist_ids: tuple[int, ...] = ()
        with self._engine.begin() as connection:
            parsed = _acquisition_reference_from_source_path(connection, source_path)
            if parsed is None:
                return None

            streaming_track_id, acquisition_id = parsed
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id,
                        soulseek_acquisitions_table.c.streaming_track_id
                        == streaming_track_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None

            connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == acquisition_id)
                .values(
                    status=SOULSEEK_STATUS_INGESTED,
                    local_track_id=local_track_id,
                    ingested_at=now,
                    updated_at=now,
                )
            )

            try:
                final_link_id, affected_playlist_ids = _create_soulseek_final_link(
                    connection,
                    local_track_id=local_track_id,
                    streaming_track_id=streaming_track_id,
                )
            except SoulseekAutoLinkConflictError as exc:
                connection.execute(
                    update(soulseek_acquisitions_table)
                    .where(soulseek_acquisitions_table.c.id == acquisition_id)
                    .values(
                        status=SOULSEEK_STATUS_LINK_FAILED,
                        error_detail=str(exc),
                        link_error_detail=str(exc),
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(soulseek_acquisitions_table)
                    .where(soulseek_acquisitions_table.c.id == acquisition_id)
                    .values(
                        status=SOULSEEK_STATUS_LINKED,
                        final_link_id=final_link_id,
                        linked_at=now,
                        error_detail=None,
                        link_error_detail=None,
                        updated_at=now,
                    )
                )

            updated_row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return SoulseekAutoLinkResult(
            acquisition=_acquisition_record(updated_row),
            affected_playlist_ids=affected_playlist_ids,
        )

    def mark_failed_from_source_path(
        self,
        *,
        error_detail: str,
        source_path: str,
    ) -> SoulseekAcquisitionRecord | None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            parsed = _acquisition_reference_from_source_path(connection, source_path)
            if parsed is None:
                return None

            streaming_track_id, acquisition_id = parsed
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id,
                        soulseek_acquisitions_table.c.streaming_track_id
                        == streaming_track_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == acquisition_id)
                .values(
                    status=SOULSEEK_STATUS_FAILED,
                    error_detail=f"Ingestion failed: {error_detail}"[:4000],
                    failed_at=now,
                    updated_at=now,
                )
            )
            updated_row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(updated_row)

    def mark_proposal_available_if_present(
        self,
        acquisition_id: str,
    ) -> SoulseekAcquisitionRecord | None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            local_track_id = row["local_track_id"]
            if local_track_id is None:
                return _acquisition_record(row)

            proposal_id = _pending_proposal_id(
                connection,
                local_track_id=local_track_id,
                streaming_track_id=row["streaming_track_id"],
            )
            if proposal_id is None:
                return _acquisition_record(row)

            connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == acquisition_id)
                .values(
                    status=SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
                    proposal_available_at=now,
                    updated_at=now,
                )
            )
            updated_row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(updated_row)

    def backfill_auto_links_from_pending_suggestions(
        self,
        *,
        min_score: float = 0.9,
    ) -> list[SoulseekAutoLinkResult]:
        now = datetime.now(UTC)
        results: list[SoulseekAutoLinkResult] = []
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(
                        soulseek_acquisitions_table.c.id,
                        soulseek_acquisitions_table.c.streaming_track_id,
                    )
                    .where(
                        soulseek_acquisitions_table.c.local_track_id.is_(None),
                        soulseek_acquisitions_table.c.final_link_id.is_(None),
                        soulseek_acquisitions_table.c.selected_candidate_id.is_not(
                            None
                        ),
                        soulseek_acquisitions_table.c.status.in_(
                            {
                                SOULSEEK_STATUS_COMPLETED,
                                SOULSEEK_STATUS_INGESTED,
                                SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
                            }
                        ),
                    )
                    .order_by(
                        desc(soulseek_acquisitions_table.c.updated_at),
                        desc(soulseek_acquisitions_table.c.created_at),
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                suggestions = (
                    connection.execute(
                        select(
                            suggested_links_table.c.local_track_id,
                            suggested_links_table.c.score,
                        )
                        .where(
                            suggested_links_table.c.streaming_track_id
                            == row["streaming_track_id"],
                            suggested_links_table.c.status
                            == SUGGESTED_LINK_STATUS_PENDING,
                            suggested_links_table.c.score >= min_score,
                        )
                        .order_by(
                            suggested_links_table.c.score.desc(),
                            suggested_links_table.c.id.asc(),
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(suggestions) != 1:
                    if len(suggestions) > 1:
                        connection.execute(
                            update(soulseek_acquisitions_table)
                            .where(soulseek_acquisitions_table.c.id == row["id"])
                            .values(
                                status=SOULSEEK_STATUS_LINK_FAILED,
                                link_error_detail=(
                                    "Multiple high-confidence local-track suggestions "
                                    "matched this Soulseek acquisition"
                                ),
                                updated_at=now,
                            )
                        )
                    continue

                local_track_id = int(suggestions[0]["local_track_id"])
                try:
                    final_link_id, affected_playlist_ids = _create_soulseek_final_link(
                        connection,
                        local_track_id=local_track_id,
                        streaming_track_id=int(row["streaming_track_id"]),
                    )
                except SoulseekAutoLinkConflictError as exc:
                    connection.execute(
                        update(soulseek_acquisitions_table)
                        .where(soulseek_acquisitions_table.c.id == row["id"])
                        .values(
                            status=SOULSEEK_STATUS_LINK_FAILED,
                            local_track_id=local_track_id,
                            error_detail=str(exc),
                            link_error_detail=str(exc),
                            updated_at=now,
                        )
                    )
                    continue

                connection.execute(
                    update(soulseek_acquisitions_table)
                    .where(soulseek_acquisitions_table.c.id == row["id"])
                    .values(
                        status=SOULSEEK_STATUS_LINKED,
                        local_track_id=local_track_id,
                        final_link_id=final_link_id,
                        linked_at=now,
                        error_detail=None,
                        link_error_detail=None,
                        updated_at=now,
                    )
                )
                updated_row = (
                    connection.execute(
                        select(soulseek_acquisitions_table).where(
                            soulseek_acquisitions_table.c.id == row["id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                results.append(
                    SoulseekAutoLinkResult(
                        acquisition=_acquisition_record(updated_row),
                        affected_playlist_ids=affected_playlist_ids,
                    )
                )

        return results

    def backfill_completed_acquisitions_from_existing_final_links(
        self,
    ) -> list[SoulseekAutoLinkResult]:
        now = datetime.now(UTC)
        results: list[SoulseekAutoLinkResult] = []
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(
                        soulseek_acquisitions_table.c.id,
                        soulseek_acquisitions_table.c.streaming_track_id,
                    )
                    .where(
                        soulseek_acquisitions_table.c.local_track_id.is_(None),
                        soulseek_acquisitions_table.c.final_link_id.is_(None),
                        soulseek_acquisitions_table.c.selected_candidate_id.is_not(
                            None
                        ),
                        soulseek_acquisitions_table.c.status.in_(
                            {
                                SOULSEEK_STATUS_COMPLETED,
                                SOULSEEK_STATUS_INGESTED,
                                SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
                            }
                        ),
                    )
                    .order_by(
                        desc(soulseek_acquisitions_table.c.updated_at),
                        desc(soulseek_acquisitions_table.c.created_at),
                    )
                )
                .mappings()
                .all()
            )
            resolver = StreamingRelationshipResolver(connection)
            for row in rows:
                target_group_ids = resolver.equivalent_group_track_ids(
                    int(row["streaming_track_id"])
                )
                final_links = (
                    connection.execute(
                        select(
                            final_links_table.c.id,
                            final_links_table.c.local_track_id,
                            final_links_table.c.streaming_track_id,
                        )
                        .where(
                            final_links_table.c.streaming_track_id.in_(target_group_ids)
                        )
                        .order_by(final_links_table.c.id.asc())
                    )
                    .mappings()
                    .all()
                )
                if len(final_links) != 1:
                    if len(final_links) > 1:
                        connection.execute(
                            update(soulseek_acquisitions_table)
                            .where(soulseek_acquisitions_table.c.id == row["id"])
                            .values(
                                status=SOULSEEK_STATUS_LINK_FAILED,
                                link_error_detail=(
                                    "Multiple existing final links matched this "
                                    "Soulseek acquisition"
                                ),
                                updated_at=now,
                            )
                        )
                    continue

                final_link = final_links[0]
                affected_playlist_ids = (
                    affected_full_sync_playlist_ids_for_streaming_tracks(
                        connection,
                        target_group_ids,
                    )
                )
                connection.execute(
                    update(soulseek_acquisitions_table)
                    .where(soulseek_acquisitions_table.c.id == row["id"])
                    .values(
                        status=SOULSEEK_STATUS_LINKED,
                        local_track_id=int(final_link["local_track_id"]),
                        final_link_id=int(final_link["id"]),
                        linked_at=now,
                        error_detail=None,
                        link_error_detail=None,
                        updated_at=now,
                    )
                )
                updated_row = (
                    connection.execute(
                        select(soulseek_acquisitions_table).where(
                            soulseek_acquisitions_table.c.id == row["id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                results.append(
                    SoulseekAutoLinkResult(
                        acquisition=_acquisition_record(updated_row),
                        affected_playlist_ids=affected_playlist_ids,
                    )
                )

        return results

    def latest_summaries_for_tracks(
        self,
        streaming_track_ids: Iterable[int],
    ) -> dict[int, MissingTrackSoulseekSummary]:
        target_ids = set(streaming_track_ids)
        if not target_ids:
            return {}

        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(soulseek_acquisitions_table)
                    .where(
                        soulseek_acquisitions_table.c.streaming_track_id.in_(target_ids)
                    )
                    .order_by(
                        soulseek_acquisitions_table.c.streaming_track_id.asc(),
                        desc(soulseek_acquisitions_table.c.created_at),
                        desc(soulseek_acquisitions_table.c.id),
                    )
                )
                .mappings()
                .all()
            )
            summaries: dict[int, MissingTrackSoulseekSummary] = {}
            for row in rows:
                track_id = int(row["streaming_track_id"])
                if track_id in summaries:
                    continue
                status = row["status"]
                if row["local_track_id"] is not None:
                    proposal_id = _pending_proposal_id(
                        connection,
                        local_track_id=row["local_track_id"],
                        streaming_track_id=track_id,
                    )
                    if proposal_id is not None:
                        status = SOULSEEK_STATUS_PROPOSAL_AVAILABLE
                summaries[track_id] = MissingTrackSoulseekSummary(
                    id=row["id"],
                    status=status,
                    candidate_count=int(row["candidate_count"]),
                    selected_candidate_id=row["selected_candidate_id"],
                    slskd_batch_id=row["slskd_batch_id"],
                    completed_source_path=row["completed_source_path"],
                    slskd_completed_event_id=row["slskd_completed_event_id"],
                    job_id=row["job_id"],
                    enqueue_job_id=row["enqueue_job_id"],
                    refresh_job_id=row["refresh_job_id"],
                    local_track_id=row["local_track_id"],
                    final_link_id=row["final_link_id"],
                    error_detail=row["error_detail"],
                    link_error_detail=row["link_error_detail"],
                )

        return summaries

    def _update_acquisition(
        self,
        acquisition_id: str,
        **values: object,
    ) -> SoulseekAcquisitionRecord:
        values["updated_at"] = datetime.now(UTC)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(soulseek_acquisitions_table)
                .where(soulseek_acquisitions_table.c.id == acquisition_id)
                .values(**values)
            )
            if result.rowcount == 0:
                raise SoulseekAcquisitionNotFoundError(acquisition_id)
            row = (
                connection.execute(
                    select(soulseek_acquisitions_table).where(
                        soulseek_acquisitions_table.c.id == acquisition_id
                    )
                )
                .mappings()
                .one()
            )
        return _acquisition_record(row)


def validate_candidate_enqueue(
    *,
    acquisition: SoulseekAcquisitionRecord,
    candidate: SoulseekCandidateRecord,
) -> None:
    if acquisition.id != candidate.acquisition_id:
        raise SoulseekCandidateConflictError("Candidate does not belong to acquisition")
    if (
        acquisition.selected_candidate_id is not None
        and acquisition.selected_candidate_id != candidate.id
        and acquisition.status not in _QUEUE_FAILED_STATUSES
    ):
        raise SoulseekCandidateConflictError(
            "A different candidate has already been selected"
        )


def soulseek_destination(
    *,
    acquisition_id: str,
    streaming_track_id: int,
) -> str:
    return f"cratelynx/{streaming_track_id}-{acquisition_id}"


def _stored_transfer_reference(transfer_id: str) -> str:
    stripped = transfer_id.strip()
    if stripped.startswith("transfer:"):
        return stripped
    return f"transfer:{stripped}"


def parse_acquisition_from_source_path(source_path: str) -> tuple[int, str] | None:
    parts = re.split(r"[\\/]+", source_path)
    for index, part in enumerate(parts[:-1]):
        if part != "cratelynx":
            continue
        match = _DESTINATION_MARKER_RE.fullmatch(parts[index + 1])
        if match is None:
            continue
        return int(match.group("streaming_track_id")), match.group("acquisition_id")
    return None


def _acquisition_reference_from_source_path(
    connection,
    source_path: str,
) -> tuple[int, str] | None:
    parsed = parse_acquisition_from_source_path(source_path)
    if parsed is not None:
        return parsed
    completed = _completed_source_acquisition_reference(connection, source_path)
    if completed is not None:
        return completed
    return _legacy_acquisition_reference_from_source_path(connection, source_path)


def _completed_source_acquisition_reference(
    connection,
    source_path: str,
) -> tuple[int, str] | None:
    normalized_source_path = _normalize_source_path_for_match(source_path)
    row = (
        connection.execute(
            select(
                soulseek_acquisitions_table.c.id,
                soulseek_acquisitions_table.c.streaming_track_id,
            )
            .where(
                soulseek_acquisitions_table.c.local_track_id.is_(None),
                soulseek_acquisitions_table.c.completed_source_path
                == normalized_source_path,
            )
            .order_by(
                desc(soulseek_acquisitions_table.c.updated_at),
                desc(soulseek_acquisitions_table.c.created_at),
            )
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return int(row["streaming_track_id"]), row["id"]


def _legacy_acquisition_reference_from_source_path(
    connection,
    source_path: str,
) -> tuple[int, str] | None:
    source_parts = _path_parts(source_path)
    if not source_parts:
        return None

    source_size = _source_file_size(source_path)
    rows = (
        connection.execute(
            select(
                soulseek_acquisitions_table.c.id,
                soulseek_acquisitions_table.c.streaming_track_id,
                soulseek_candidates_table.c.filename,
                soulseek_candidates_table.c.size,
            )
            .select_from(
                soulseek_acquisitions_table.join(
                    soulseek_candidates_table,
                    soulseek_acquisitions_table.c.selected_candidate_id
                    == soulseek_candidates_table.c.id,
                )
            )
            .where(
                soulseek_acquisitions_table.c.local_track_id.is_(None),
                soulseek_acquisitions_table.c.status.in_(_SOURCE_PATH_MATCH_STATUSES),
            )
            .order_by(
                desc(soulseek_acquisitions_table.c.updated_at),
                desc(soulseek_acquisitions_table.c.created_at),
            )
        )
        .mappings()
        .all()
    )

    for row in rows:
        if source_size is not None and int(row["size"]) != source_size:
            continue
        candidate_parts = _path_parts(row["filename"])
        if _path_has_suffix_overlap(source_parts, candidate_parts):
            return int(row["streaming_track_id"]), row["id"]
    return None


def _normalize_source_path_for_match(source_path: str) -> str:
    try:
        return str(Path(source_path).expanduser().resolve(strict=False))
    except OSError:
        return source_path


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in re.split(r"[\\/]+", path) if part)


def _path_has_suffix_overlap(
    parts: tuple[str, ...],
    candidate_parts: tuple[str, ...],
) -> bool:
    if not parts or not candidate_parts:
        return False
    normalized_parts = tuple(part.casefold() for part in parts)
    normalized_candidate_parts = tuple(part.casefold() for part in candidate_parts)
    max_overlap = min(len(normalized_parts), len(normalized_candidate_parts))
    for length in range(max_overlap, 0, -1):
        if normalized_parts[-length:] == normalized_candidate_parts[-length:] and (
            length >= 2
            or len(normalized_parts) == 1
            or len(normalized_candidate_parts) == 1
        ):
            return True
    return False


def _source_file_size(source_path: str) -> int | None:
    try:
        return Path(source_path).stat().st_size
    except OSError:
        return None


def _latest_acquisitions(connection) -> dict[int, SoulseekAcquisitionRecord]:
    rows = (
        connection.execute(
            select(soulseek_acquisitions_table).order_by(
                soulseek_acquisitions_table.c.streaming_track_id.asc(),
                desc(soulseek_acquisitions_table.c.created_at),
                desc(soulseek_acquisitions_table.c.id),
            )
        )
        .mappings()
        .all()
    )
    acquisitions: dict[int, SoulseekAcquisitionRecord] = {}
    for row in rows:
        track_id = int(row["streaming_track_id"])
        if track_id in acquisitions:
            continue
        acquisitions[track_id] = _acquisition_record(row)
    return acquisitions


def _missing_unsearched_tracks(
    connection,
    *,
    excluded_streaming_track_ids: Iterable[int],
) -> set[int]:
    excluded = set(excluded_streaming_track_ids)
    rows = (
        connection.execute(
            select(streaming_tracks_table.c.id)
            .select_from(
                streaming_tracks_table.join(
                    playlist_membership_table,
                    playlist_membership_table.c.streaming_track_id
                    == streaming_tracks_table.c.id,
                ).join(
                    streaming_playlists_table,
                    streaming_playlists_table.c.id
                    == playlist_membership_table.c.playlist_id,
                )
            )
            .where(streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL)
            .distinct()
            .order_by(streaming_tracks_table.c.id.asc())
        )
        .mappings()
        .all()
    )
    resolver = StreamingRelationshipResolver(connection)
    missing_track_ids: set[int] = set()
    for row in rows:
        track_id = int(row["id"])
        if track_id in excluded:
            continue
        if resolver.resolve(track_id) is None:
            missing_track_ids.add(track_id)
    return missing_track_ids


def _streaming_tracks(
    connection,
    streaming_track_ids: Iterable[int],
) -> dict[int, StreamingTrackForSoulseek]:
    target_ids = set(streaming_track_ids)
    if not target_ids:
        return {}
    rows = (
        connection.execute(
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.duration_ms,
            )
            .where(streaming_tracks_table.c.id.in_(target_ids))
            .order_by(streaming_tracks_table.c.title.asc(), streaming_tracks_table.c.id)
        )
        .mappings()
        .all()
    )
    return {
        int(row["id"]): StreamingTrackForSoulseek(
            id=int(row["id"]),
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            duration_ms=row["duration_ms"],
        )
        for row in rows
    }


def _playlist_usage(
    connection,
    streaming_track_ids: Iterable[int],
) -> dict[int, tuple[list[int], list[str]]]:
    target_ids = set(streaming_track_ids)
    if not target_ids:
        return {}
    rows = (
        connection.execute(
            select(
                playlist_membership_table.c.streaming_track_id,
                streaming_playlists_table.c.id.label("playlist_id"),
                streaming_playlists_table.c.title.label("playlist_title"),
            )
            .select_from(
                playlist_membership_table.join(
                    streaming_playlists_table,
                    streaming_playlists_table.c.id
                    == playlist_membership_table.c.playlist_id,
                )
            )
            .where(playlist_membership_table.c.streaming_track_id.in_(target_ids))
            .where(streaming_playlists_table.c.sync_mode == PLAYLIST_SYNC_MODE_FULL)
            .order_by(
                playlist_membership_table.c.streaming_track_id.asc(),
                streaming_playlists_table.c.title.asc(),
                streaming_playlists_table.c.id.asc(),
            )
        )
        .mappings()
        .all()
    )
    usage: dict[int, tuple[list[int], list[str]]] = {}
    for row in rows:
        track_id = int(row["streaming_track_id"])
        playlist_ids, playlist_titles = usage.setdefault(track_id, ([], []))
        playlist_ids.append(int(row["playlist_id"]))
        playlist_titles.append(row["playlist_title"])
    return usage


def _candidate_map(
    connection,
    acquisition_ids: Iterable[str],
    *,
    limit: int,
) -> dict[str, list[SoulseekCandidateRecord]]:
    target_ids = set(acquisition_ids)
    if not target_ids:
        return {}
    rows = (
        connection.execute(
            select(soulseek_candidates_table)
            .where(soulseek_candidates_table.c.acquisition_id.in_(target_ids))
            .order_by(
                soulseek_candidates_table.c.acquisition_id.asc(),
                soulseek_candidates_table.c.score.desc(),
                soulseek_candidates_table.c.id.asc(),
            )
        )
        .mappings()
        .all()
    )
    candidates_by_acquisition: dict[str, list[SoulseekCandidateRecord]] = {}
    for row in rows:
        candidates = candidates_by_acquisition.setdefault(row["acquisition_id"], [])
        if len(candidates) < limit:
            candidates.append(_candidate_record(row))
    return candidates_by_acquisition


def _selected_candidate_map(
    connection,
    acquisitions: Iterable[SoulseekAcquisitionRecord],
) -> dict[str, SoulseekCandidateRecord]:
    candidate_ids = {
        acquisition.selected_candidate_id
        for acquisition in acquisitions
        if acquisition.selected_candidate_id is not None
    }
    if not candidate_ids:
        return {}
    rows = (
        connection.execute(
            select(soulseek_candidates_table).where(
                soulseek_candidates_table.c.id.in_(candidate_ids)
            )
        )
        .mappings()
        .all()
    )
    return {row["id"]: _candidate_record(row) for row in rows}


def _queue_filter_matches(
    filter_key: str,
    acquisition: SoulseekAcquisitionRecord | None,
) -> bool:
    if filter_key == "all":
        return True
    if filter_key == "needs_search":
        return (
            acquisition is None or acquisition.status == SOULSEEK_STATUS_NO_CANDIDATES
        )
    if acquisition is None:
        return False
    if filter_key == "review":
        return acquisition.status in _QUEUE_REVIEW_STATUSES
    if filter_key in {"active", "downloading"}:
        return acquisition.status in _QUEUE_DOWNLOADING_STATUSES
    if filter_key == "failed":
        return acquisition.status in _QUEUE_FAILED_STATUSES
    if filter_key == "linked":
        return acquisition.status == SOULSEEK_STATUS_LINKED
    return True


def _queue_sort_key(item: SoulseekQueueItemRecord) -> tuple[int, str, int]:
    acquisition = item.acquisition
    status = acquisition.status if acquisition is not None else None
    status_rank = {
        SOULSEEK_STATUS_CANDIDATES_FOUND: 0,
        SOULSEEK_STATUS_FAILED: 1,
        SOULSEEK_STATUS_LINK_FAILED: 1,
        SOULSEEK_STATUS_SEARCHING: 2,
        SOULSEEK_STATUS_QUEUED: 2,
        SOULSEEK_STATUS_DOWNLOADING: 2,
        SOULSEEK_STATUS_COMPLETED: 2,
        SOULSEEK_STATUS_INGESTED: 2,
        SOULSEEK_STATUS_PROPOSAL_AVAILABLE: 2,
        SOULSEEK_STATUS_NO_CANDIDATES: 3,
        SOULSEEK_STATUS_LINKED: 4,
    }.get(status, 3)
    return (
        status_rank,
        item.streaming_track.title.casefold(),
        item.streaming_track.id,
    )


def _create_soulseek_final_link(
    connection,
    *,
    local_track_id: int,
    streaming_track_id: int,
) -> tuple[int, tuple[int, ...]]:
    existing_local_link = _final_link_for_local_track(connection, local_track_id)
    resolver = StreamingRelationshipResolver(connection)
    target_group_ids = resolver.equivalent_group_track_ids(streaming_track_id)
    affected_track_ids = set(target_group_ids)

    if existing_local_link is not None:
        existing_streaming_track_id = int(existing_local_link["streaming_track_id"])
        existing_group_ids = resolver.equivalent_group_track_ids(
            existing_streaming_track_id
        )
        if set(existing_group_ids).intersection(target_group_ids):
            return int(existing_local_link["id"]), (
                affected_full_sync_playlist_ids_for_streaming_tracks(
                    connection,
                    (*target_group_ids, *existing_group_ids),
                )
            )
        raise SoulseekAutoLinkConflictError(
            "Imported local track is already linked to another streaming track"
        )

    conflicting_links = _conflicting_group_final_links(
        connection,
        target_group_ids,
        local_track_id=local_track_id,
    )
    if conflicting_links:
        raise SoulseekAutoLinkConflictError(
            "Streaming track or equivalent group is already linked to another local track"
        )

    result = connection.execute(
        insert(final_links_table).values(
            local_track_id=local_track_id,
            streaming_track_id=streaming_track_id,
        )
    )
    final_link_id = result.inserted_primary_key[0]
    if not isinstance(final_link_id, int):
        raise ValueError("Failed to persist Soulseek final link")

    connection.execute(
        insert(suggested_links_table).values(
            local_track_id=local_track_id,
            streaming_track_id=streaming_track_id,
            match_method="soulseek",
            score=1.0,
            status=SUGGESTED_LINK_STATUS_APPROVED,
        )
    )
    connection.execute(
        delete(suggested_links_table).where(
            suggested_links_table.c.local_track_id == local_track_id,
            suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
        )
    )
    affected_playlist_ids = affected_full_sync_playlist_ids_for_streaming_tracks(
        connection,
        affected_track_ids,
    )
    return final_link_id, affected_playlist_ids


def _final_link_for_local_track(connection, local_track_id: int):
    return (
        connection.execute(
            select(
                final_links_table.c.id,
                final_links_table.c.local_track_id,
                final_links_table.c.streaming_track_id,
            ).where(final_links_table.c.local_track_id == local_track_id)
        )
        .mappings()
        .one_or_none()
    )


def _conflicting_group_final_links(
    connection,
    streaming_track_ids: tuple[int, ...],
    *,
    local_track_id: int,
):
    rows = (
        connection.execute(
            select(
                final_links_table.c.id,
                final_links_table.c.local_track_id,
                final_links_table.c.streaming_track_id,
            )
            .where(final_links_table.c.streaming_track_id.in_(streaming_track_ids))
            .order_by(final_links_table.c.id.asc())
        )
        .mappings()
        .all()
    )
    return [row for row in rows if row["local_track_id"] != local_track_id]


def _pending_proposal_id(
    connection,
    *,
    local_track_id: int,
    streaming_track_id: int,
) -> int | None:
    proposal_id = connection.execute(
        select(func.min(suggested_links_table.c.id)).where(
            suggested_links_table.c.local_track_id == local_track_id,
            suggested_links_table.c.streaming_track_id == streaming_track_id,
            suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
        )
    ).scalar_one_or_none()
    return int(proposal_id) if proposal_id is not None else None


def _acquisition_record(row) -> SoulseekAcquisitionRecord:
    return SoulseekAcquisitionRecord(
        id=row["id"],
        streaming_track_id=row["streaming_track_id"],
        status=row["status"],
        search_text=row["search_text"],
        fallback_search_text=row["fallback_search_text"],
        slskd_search_id=row["slskd_search_id"],
        slskd_fallback_search_id=row["slskd_fallback_search_id"],
        candidate_count=int(row["candidate_count"]),
        selected_candidate_id=row["selected_candidate_id"],
        slskd_batch_id=row["slskd_batch_id"],
        destination=row["destination"],
        completed_source_path=row["completed_source_path"],
        slskd_completed_event_id=row["slskd_completed_event_id"],
        local_track_id=row["local_track_id"],
        final_link_id=row["final_link_id"],
        job_id=row["job_id"],
        enqueue_job_id=row["enqueue_job_id"],
        refresh_job_id=row["refresh_job_id"],
        error_detail=row["error_detail"],
        link_error_detail=row["link_error_detail"],
        searched_at=row["searched_at"],
        queued_at=row["queued_at"],
        completed_at=row["completed_at"],
        ingested_at=row["ingested_at"],
        proposal_available_at=row["proposal_available_at"],
        linked_at=row["linked_at"],
        failed_at=row["failed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _candidate_record(row) -> SoulseekCandidateRecord:
    return SoulseekCandidateRecord(
        id=row["id"],
        acquisition_id=row["acquisition_id"],
        slskd_search_id=row["slskd_search_id"],
        username=row["username"],
        filename=row["filename"],
        size=int(row["size"]),
        extension=row["extension"],
        duration_seconds=row["duration_seconds"],
        bit_rate=row["bit_rate"],
        bit_depth=row["bit_depth"],
        sample_rate=row["sample_rate"],
        is_variable_bit_rate=row["is_variable_bit_rate"],
        has_free_upload_slot=bool(row["has_free_upload_slot"]),
        queue_length=(
            int(row["queue_length"]) if row["queue_length"] is not None else None
        ),
        upload_speed=row["upload_speed"],
        score=float(row["score"]),
        created_at=row["created_at"],
    )
