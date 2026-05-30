from __future__ import annotations

from collections.abc import Callable
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.soulseek.client import SlskdClient, SlskdClientError, SlskdHttpError
from app.soulseek.config import (
    SoulseekConfigurationError,
    is_slskd_configured,
    load_slskd_config,
)
from app.soulseek.jobs import SoulseekJobEnqueuer, enqueue_soulseek_candidate_now
from app.soulseek.schemas import (
    SlskdDownloadCompleteWebhook,
    SoulseekAcquisitionDetailResponse,
    SoulseekAcquisitionSummaryResponse,
    SoulseekBulkSearchItemResponse,
    SoulseekBulkSearchRequest,
    SoulseekBulkSearchResponse,
    SoulseekCandidateResponse,
    SoulseekCandidatesResponse,
    SoulseekEnqueueResponse,
    SoulseekQueueFilter,
    SoulseekQueueItemResponse,
    SoulseekQueueResponse,
    SoulseekRefreshResponse,
    SoulseekSearchResponse,
    SoulseekStreamingTrackResponse,
    SoulseekStatusResponse,
    SoulseekWebhookResponse,
)
from app.soulseek.store import (
    SoulseekAcquisitionNotFoundError,
    SoulseekCandidateConflictError,
    SoulseekCandidateNotFoundError,
    SoulseekStore,
    validate_candidate_enqueue,
)


def create_router(
    *,
    require_redis_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _redis_url() -> str:
        if require_redis_url is None:
            raise HTTPException(
                status_code=503,
                detail="REDIS_URL must be configured for Soulseek jobs",
            )
        return require_redis_url()

    def _require_slskd_configured() -> None:
        try:
            load_slskd_config()
        except SoulseekConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("/soulseek/status", response_model=SoulseekStatusResponse)
    def get_soulseek_status() -> SoulseekStatusResponse:
        if not is_slskd_configured():
            return SoulseekStatusResponse(
                configured=False,
                ok=False,
                detail="SLSKD_BASE_URL and SLSKD_API_KEY must be configured",
            )

        try:
            SlskdClient(load_slskd_config()).status()
        except SlskdHttpError as exc:
            return SoulseekStatusResponse(
                configured=True,
                ok=False,
                detail=f"slskd returned status {exc.status_code}",
            )
        except (SoulseekConfigurationError, SlskdClientError) as exc:
            return SoulseekStatusResponse(configured=True, ok=False, detail=str(exc))
        return SoulseekStatusResponse(configured=True, ok=True)

    @router.post(
        "/soulseek/missing-tracks/{streaming_track_id}/search",
        response_model=SoulseekSearchResponse,
        status_code=202,
    )
    def search_missing_track(
        streaming_track_id: int,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekSearchResponse:
        _require_slskd_configured()
        store = SoulseekStore(engine=engine)
        if store.get_streaming_track(streaming_track_id) is None:
            raise HTTPException(status_code=404, detail="Streaming track not found")

        acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
        try:
            job_id = SoulseekJobEnqueuer(_redis_url()).enqueue_search(acquisition.id)
        except Exception as exc:
            store.mark_failed(
                acquisition.id,
                f"Failed to enqueue Soulseek search job: {exc}",
            )
            raise HTTPException(
                status_code=503,
                detail="Failed to enqueue Soulseek search job",
            ) from exc
        store.set_search_job_id(acquisition.id, job_id)
        acquisition = store.get_acquisition(acquisition.id)
        if acquisition is None:
            raise HTTPException(status_code=500, detail="Soulseek acquisition lost")
        return SoulseekSearchResponse(
            acquisition=_acquisition_response(acquisition),
            job_id=job_id,
        )

    @router.post(
        "/soulseek/missing-tracks/search-selected",
        response_model=SoulseekBulkSearchResponse,
        status_code=202,
    )
    def search_selected_missing_tracks(
        payload: SoulseekBulkSearchRequest,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekBulkSearchResponse:
        _require_slskd_configured()
        store = SoulseekStore(engine=engine)
        enqueuer = SoulseekJobEnqueuer(_redis_url())
        jobs: list[SoulseekBulkSearchItemResponse] = []

        for streaming_track_id in dict.fromkeys(payload.streaming_track_ids):
            if store.get_streaming_track(streaming_track_id) is None:
                raise HTTPException(status_code=404, detail="Streaming track not found")
            acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
            try:
                job_id = enqueuer.enqueue_search(acquisition.id)
            except Exception as exc:
                store.mark_failed(
                    acquisition.id,
                    f"Failed to enqueue Soulseek search job: {exc}",
                )
                raise HTTPException(
                    status_code=503,
                    detail="Failed to enqueue Soulseek search job",
                ) from exc
            store.set_search_job_id(acquisition.id, job_id)
            acquisition = store.get_acquisition(acquisition.id)
            if acquisition is None:
                raise HTTPException(status_code=500, detail="Soulseek acquisition lost")
            jobs.append(
                SoulseekBulkSearchItemResponse(
                    acquisition=_acquisition_response(acquisition),
                    job_id=job_id,
                    streaming_track_id=streaming_track_id,
                )
            )

        return SoulseekBulkSearchResponse(jobs=jobs)

    @router.get(
        "/soulseek/queue",
        response_model=SoulseekQueueResponse,
    )
    def list_soulseek_queue(
        filter: SoulseekQueueFilter = "all",
        engine: Engine = Depends(get_engine),
    ) -> SoulseekQueueResponse:
        items = SoulseekStore(engine=engine).list_queue_items(filter_key=filter)
        return SoulseekQueueResponse(
            filter=filter,
            items=[_queue_item_response(item) for item in items],
            total_count=len(items),
        )

    @router.get(
        "/soulseek/acquisitions/{acquisition_id}",
        response_model=SoulseekQueueItemResponse,
    )
    def get_acquisition_detail(
        acquisition_id: str,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekQueueItemResponse:
        item = SoulseekStore(engine=engine).get_queue_item_for_acquisition(
            acquisition_id
        )
        if item is None:
            raise HTTPException(
                status_code=404, detail="Soulseek acquisition not found"
            )
        return _queue_item_response(item)

    @router.get(
        "/soulseek/acquisitions/{acquisition_id}/candidates",
        response_model=SoulseekCandidatesResponse,
    )
    def list_candidates(
        acquisition_id: str,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekCandidatesResponse:
        store = SoulseekStore(engine=engine)
        acquisition = store.get_acquisition(acquisition_id)
        if acquisition is None:
            raise HTTPException(
                status_code=404, detail="Soulseek acquisition not found"
            )
        return SoulseekCandidatesResponse(
            acquisition=_acquisition_response(acquisition),
            candidates=[
                _candidate_response(candidate)
                for candidate in store.list_candidates(acquisition_id)
            ],
        )

    @router.post(
        "/soulseek/candidates/{candidate_id}/enqueue",
        response_model=SoulseekEnqueueResponse,
        status_code=202,
    )
    def enqueue_candidate(
        candidate_id: str,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekEnqueueResponse:
        return _approve_candidate_download(candidate_id, engine=engine)

    @router.post(
        "/soulseek/candidates/{candidate_id}/approve-download",
        response_model=SoulseekEnqueueResponse,
        status_code=202,
    )
    def approve_candidate_download(
        candidate_id: str,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekEnqueueResponse:
        return _approve_candidate_download(candidate_id, engine=engine)

    def _approve_candidate_download(
        candidate_id: str,
        *,
        engine: Engine,
    ) -> SoulseekEnqueueResponse:
        _require_slskd_configured()
        store = SoulseekStore(engine=engine)
        try:
            candidate = store.get_candidate(candidate_id)
            if candidate is None:
                raise SoulseekCandidateNotFoundError(candidate_id)
            acquisition = store.get_acquisition(candidate.acquisition_id)
            if acquisition is None:
                raise SoulseekAcquisitionNotFoundError(candidate.acquisition_id)
            validate_candidate_enqueue(acquisition=acquisition, candidate=candidate)
        except SoulseekCandidateNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Soulseek candidate not found",
            ) from exc
        except SoulseekAcquisitionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Soulseek acquisition not found",
            ) from exc
        except SoulseekCandidateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        try:
            acquisition = enqueue_soulseek_candidate_now(
                candidate.id,
                client=SlskdClient(load_slskd_config()),
                store=store,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Failed to queue Soulseek download: {exc}",
            ) from exc
        return SoulseekEnqueueResponse(
            acquisition=_acquisition_response(acquisition),
            job_id=None,
        )

    @router.post(
        "/soulseek/acquisitions/{acquisition_id}/refresh",
        response_model=SoulseekRefreshResponse,
        status_code=202,
    )
    def refresh_acquisition(
        acquisition_id: str,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekRefreshResponse:
        _require_slskd_configured()
        store = SoulseekStore(engine=engine)
        acquisition = store.get_acquisition(acquisition_id)
        if acquisition is None:
            raise HTTPException(
                status_code=404, detail="Soulseek acquisition not found"
            )
        try:
            job_id = SoulseekJobEnqueuer(_redis_url()).enqueue_refresh(acquisition.id)
        except Exception as exc:
            store.mark_failed(
                acquisition.id,
                f"Failed to enqueue Soulseek refresh job: {exc}",
            )
            raise HTTPException(
                status_code=503,
                detail="Failed to enqueue Soulseek refresh job",
            ) from exc
        store.set_refresh_job_id(acquisition.id, job_id)
        acquisition = store.get_acquisition(acquisition.id)
        if acquisition is None:
            raise HTTPException(status_code=500, detail="Soulseek acquisition lost")
        return SoulseekRefreshResponse(
            acquisition=_acquisition_response(acquisition),
            job_id=job_id,
        )

    @router.post(
        "/soulseek/slskd/download-complete",
        response_model=SoulseekWebhookResponse,
        status_code=202,
    )
    def receive_slskd_download_complete(
        payload: SlskdDownloadCompleteWebhook,
        x_cratelynx_webhook_token: Annotated[
            str | None, Header(alias="X-CrateLynx-Webhook-Token")
        ] = None,
        engine: Engine = Depends(get_engine),
    ) -> SoulseekWebhookResponse:
        expected_token = os.environ.get("SLSKD_WEBHOOK_TOKEN")
        if expected_token is None or expected_token.strip() == "":
            raise HTTPException(
                status_code=503,
                detail="SLSKD_WEBHOOK_TOKEN must be configured",
            )
        if x_cratelynx_webhook_token != expected_token:
            raise HTTPException(status_code=401, detail="Invalid webhook token")
        if payload.type != "DownloadFileComplete":
            raise HTTPException(status_code=400, detail="Unsupported slskd event type")

        acquisition = SoulseekStore(engine=engine).mark_download_completed_from_webhook(
            event_id=payload.id,
            source_path=_translate_slskd_download_path(payload.local_filename),
            transfer_id=payload.transfer.id,
        )
        return SoulseekWebhookResponse(
            matched=acquisition is not None,
            acquisition=(
                _acquisition_response(acquisition) if acquisition is not None else None
            ),
        )

    return router


def _acquisition_response(acquisition) -> SoulseekAcquisitionSummaryResponse:
    return SoulseekAcquisitionSummaryResponse(
        id=acquisition.id,
        status=acquisition.status,
        candidate_count=acquisition.candidate_count,
        selected_candidate_id=acquisition.selected_candidate_id,
        slskd_batch_id=acquisition.slskd_batch_id,
        slskd_transfer_id=_slskd_transfer_id(acquisition.slskd_batch_id),
        completed_source_path=acquisition.completed_source_path,
        slskd_completed_event_id=acquisition.slskd_completed_event_id,
        job_id=acquisition.job_id,
        enqueue_job_id=acquisition.enqueue_job_id,
        refresh_job_id=acquisition.refresh_job_id,
        local_track_id=acquisition.local_track_id,
        final_link_id=acquisition.final_link_id,
        error_detail=acquisition.error_detail,
        link_error_detail=acquisition.link_error_detail,
    )


def _acquisition_detail_response(acquisition) -> SoulseekAcquisitionDetailResponse:
    return SoulseekAcquisitionDetailResponse(
        **_acquisition_response(acquisition).model_dump(),
        streaming_track_id=acquisition.streaming_track_id,
        search_text=acquisition.search_text,
        fallback_search_text=acquisition.fallback_search_text,
        slskd_search_id=acquisition.slskd_search_id,
        slskd_fallback_search_id=acquisition.slskd_fallback_search_id,
        destination=acquisition.destination,
        searched_at=_optional_isoformat(acquisition.searched_at),
        queued_at=_optional_isoformat(acquisition.queued_at),
        completed_at=_optional_isoformat(acquisition.completed_at),
        ingested_at=_optional_isoformat(acquisition.ingested_at),
        proposal_available_at=_optional_isoformat(acquisition.proposal_available_at),
        linked_at=_optional_isoformat(acquisition.linked_at),
        failed_at=_optional_isoformat(acquisition.failed_at),
        created_at=acquisition.created_at.isoformat(),
        updated_at=acquisition.updated_at.isoformat(),
    )


def _candidate_response(candidate) -> SoulseekCandidateResponse:
    return SoulseekCandidateResponse(
        id=candidate.id,
        acquisition_id=candidate.acquisition_id,
        slskd_search_id=candidate.slskd_search_id,
        username=candidate.username,
        filename=candidate.filename,
        size=candidate.size,
        extension=candidate.extension,
        duration_seconds=candidate.duration_seconds,
        bit_rate=candidate.bit_rate,
        bit_depth=candidate.bit_depth,
        sample_rate=candidate.sample_rate,
        is_variable_bit_rate=candidate.is_variable_bit_rate,
        has_free_upload_slot=candidate.has_free_upload_slot,
        queue_length=candidate.queue_length,
        upload_speed=candidate.upload_speed,
        score=candidate.score,
        created_at=candidate.created_at.isoformat(),
    )


def _queue_item_response(item) -> SoulseekQueueItemResponse:
    return SoulseekQueueItemResponse(
        acquisition=(
            _acquisition_detail_response(item.acquisition)
            if item.acquisition is not None
            else None
        ),
        candidates=[_candidate_response(candidate) for candidate in item.candidates],
        playlist_count=item.playlist_count,
        playlist_ids=item.playlist_ids,
        playlist_titles=item.playlist_titles,
        selected_candidate=(
            _candidate_response(item.selected_candidate)
            if item.selected_candidate is not None
            else None
        ),
        streaming_track=SoulseekStreamingTrackResponse(
            id=item.streaming_track.id,
            title=item.streaming_track.title,
            artist=item.streaming_track.artist,
            album=item.streaming_track.album,
            duration_ms=item.streaming_track.duration_ms,
        ),
    )


def _optional_isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None


def _slskd_transfer_id(stored_id: str | None) -> str | None:
    if stored_id is None:
        return None
    if stored_id.startswith("transfer:"):
        transfer_id = stored_id[len("transfer:") :].strip()
        return transfer_id or None
    return stored_id


def _translate_slskd_download_path(local_filename: str) -> str:
    container_root = os.environ.get(
        "SLSKD_DOWNLOADS_CONTAINER_ROOT",
        "/data/soulseek/downloads",
    ).rstrip("/")
    app_root = os.environ.get(
        "SLSKD_DOWNLOADS_APP_ROOT",
        "/nas/soulseek/downloads",
    ).rstrip("/")
    if not container_root or not app_root:
        return local_filename
    if local_filename == container_root:
        return app_root
    prefix = f"{container_root}/"
    if local_filename.startswith(prefix):
        return f"{app_root}/{local_filename[len(prefix) :]}"
    return local_filename
