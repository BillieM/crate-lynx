# ruff: noqa: B008

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Engine

from app.autopilot.jobs import AutopilotJobEnqueuer
from app.autopilot.models import (
    AUTOPILOT_TRIGGER_MANUAL,
    AutopilotRunItemRecord,
    AutopilotRunRecord,
    AutopilotSettingsRecord,
)
from app.autopilot.schemas import (
    AutopilotRunDetailResponse,
    AutopilotRunItemResponse,
    AutopilotRunResponse,
    AutopilotRunsResponse,
    AutopilotSettingsResponse,
    StartAutopilotRunRequest,
    StartAutopilotRunResponse,
    UpdateAutopilotSettingsRequest,
)
from app.autopilot.store import AutopilotStore
from app.core.db import get_engine


def create_router(*, require_redis_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/autopilot/settings", response_model=AutopilotSettingsResponse)
    def get_autopilot_settings(
        engine: Engine = Depends(get_engine),
    ) -> AutopilotSettingsResponse:
        return _settings_response(AutopilotStore(engine=engine).get_settings())

    @router.patch("/autopilot/settings", response_model=AutopilotSettingsResponse)
    def update_autopilot_settings(
        payload: UpdateAutopilotSettingsRequest,
        engine: Engine = Depends(get_engine),
    ) -> AutopilotSettingsResponse:
        try:
            settings = AutopilotStore(engine=engine).update_settings(
                **payload.model_dump(exclude_unset=True)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _settings_response(settings)

    @router.get("/autopilot/runs", response_model=AutopilotRunsResponse)
    def list_autopilot_runs(
        limit: int = Query(default=20, ge=1, le=100),
        engine: Engine = Depends(get_engine),
    ) -> AutopilotRunsResponse:
        return AutopilotRunsResponse(
            runs=[
                _run_response(run)
                for run in AutopilotStore(engine=engine).list_runs(limit=limit)
            ]
        )

    @router.get("/autopilot/runs/{run_id}", response_model=AutopilotRunDetailResponse)
    def get_autopilot_run(
        run_id: str,
        engine: Engine = Depends(get_engine),
    ) -> AutopilotRunDetailResponse:
        store = AutopilotStore(engine=engine)
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Autopilot run not found")
        return AutopilotRunDetailResponse(
            **_run_response(run).model_dump(),
            items=[_item_response(item) for item in store.list_run_items(run.id)],
        )

    @router.post(
        "/autopilot/runs",
        response_model=StartAutopilotRunResponse,
        status_code=202,
    )
    def start_autopilot_run(
        payload: StartAutopilotRunRequest,
        engine: Engine = Depends(get_engine),
    ) -> StartAutopilotRunResponse:
        idempotency_key = f"manual:{uuid.uuid4().hex}"
        store = AutopilotStore(engine=engine)
        run, _ = store.get_or_create_run(
            dry_run=payload.dry_run,
            idempotency_key=idempotency_key,
            trigger=AUTOPILOT_TRIGGER_MANUAL,
        )
        try:
            job_id = AutopilotJobEnqueuer(require_redis_url()).enqueue(
                dry_run=payload.dry_run,
                idempotency_key=idempotency_key,
                trigger=AUTOPILOT_TRIGGER_MANUAL,
            )
        except Exception as exc:
            store.update_run(
                run.id,
                status="failed",
                error_detail=f"Failed to enqueue autopilot run: {exc}",
            )
            raise HTTPException(
                status_code=503, detail="Failed to enqueue autopilot run"
            ) from exc
        return StartAutopilotRunResponse(run=_run_response(run), job_id=job_id)

    return router


def _settings_response(
    settings: AutopilotSettingsRecord,
) -> AutopilotSettingsResponse:
    return AutopilotSettingsResponse(
        id=settings.id,
        paused=settings.paused,
        schedule_minutes=settings.schedule_minutes,
        quiet_period_seconds=settings.quiet_period_seconds,
        max_concurrent_downloads=settings.max_concurrent_downloads,
        max_downloads_per_run=settings.max_downloads_per_run,
        max_searches_per_run=settings.max_searches_per_run,
        max_storage_bytes_per_run=settings.max_storage_bytes_per_run,
        retry_max_attempts=settings.retry_max_attempts,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        created_at=settings.created_at.isoformat(),
        updated_at=settings.updated_at.isoformat(),
    )


def _run_response(run: AutopilotRunRecord) -> AutopilotRunResponse:
    return AutopilotRunResponse(
        id=run.id,
        idempotency_key=run.idempotency_key,
        trigger=run.trigger,
        dry_run=run.dry_run,
        status=run.status,
        started_at=run.started_at.isoformat(),
        heartbeat_at=_iso(run.heartbeat_at),
        finished_at=_iso(run.finished_at),
        error_detail=run.error_detail,
        refreshed_playlists=run.refreshed_playlists,
        searched_tracks=run.searched_tracks,
        queued_downloads=run.queued_downloads,
        downloaded_tracks=run.downloaded_tracks,
        ingested_tracks=run.ingested_tracks,
        analyzed_tracks=run.analyzed_tracks,
        regenerated_recipes=run.regenerated_recipes,
        refreshed_exports=run.refreshed_exports,
        review_items=run.review_items,
        failed_items=run.failed_items,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
    )


def _item_response(item: AutopilotRunItemRecord) -> AutopilotRunItemResponse:
    return AutopilotRunItemResponse(
        id=item.id,
        run_id=item.run_id,
        idempotency_key=item.idempotency_key,
        stage=item.stage,
        action=item.action,
        status=item.status,
        playlist_id=item.playlist_id,
        streaming_track_id=item.streaming_track_id,
        acquisition_id=item.acquisition_id,
        recipe_id=item.recipe_id,
        candidate_id=item.candidate_id,
        attempt_count=item.attempt_count,
        next_attempt_at=_iso(item.next_attempt_at),
        identity_confidence=item.identity_confidence,
        version_confidence=item.version_confidence,
        quality_score=item.quality_score,
        runner_up_margin=item.runner_up_margin,
        expected_duration_ms=item.expected_duration_ms,
        candidate_duration_ms=item.candidate_duration_ms,
        reason_code=item.reason_code,
        detail=item.detail,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
        completed_at=_iso(item.completed_at),
    )


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None
