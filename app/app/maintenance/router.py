from collections.abc import Callable
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.ingestion.failures import FailedIngestionAttemptStore
from app.ingestion.jobs import IngestionJobEnqueuer
from app.maintenance.schemas import (
    MissingLocallyResponse,
    MissingLocallyTrackResponse,
    UnidentifiedIgnoreResponse,
    UnidentifiedResponse,
    UnidentifiedRestoreResponse,
    UnidentifiedRetryResponse,
    UnidentifiedTrackResponse,
)
from app.maintenance.store import MaintenanceStore


def create_router(
    *,
    require_redis_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _require_redis_url() -> str:
        if require_redis_url is not None:
            return require_redis_url()

        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            raise HTTPException(
                status_code=503,
                detail="REDIS_URL must be configured for ingestion retry jobs",
            )
        return redis_url

    @router.get("/maintenance/missing-locally", response_model=MissingLocallyResponse)
    def list_missing_locally(
        engine: Engine = Depends(get_engine),
    ) -> MissingLocallyResponse:
        tracks = MaintenanceStore(engine=engine).list_missing_locally()
        return MissingLocallyResponse(
            tracks=[
                MissingLocallyTrackResponse(
                    id=track.id,
                    provider_track_id=track.provider_track_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_ms=track.duration_ms,
                    playlist_count=track.playlist_count,
                    playlist_ids=track.playlist_ids,
                    playlist_titles=track.playlist_titles,
                )
                for track in tracks
            ]
        )

    @router.get("/maintenance/unidentified", response_model=UnidentifiedResponse)
    def list_unidentified(
        engine: Engine = Depends(get_engine),
    ) -> UnidentifiedResponse:
        tracks = MaintenanceStore(engine=engine).list_unidentified()
        return UnidentifiedResponse(
            tracks=[
                UnidentifiedTrackResponse(
                    id=track.id,
                    attempt_count=track.attempt_count,
                    can_rematch_local_track=track.can_rematch_local_track,
                    can_rescue_metadata=track.can_rescue_metadata,
                    failed_at=track.failed_at,
                    failure_reason=track.failure_reason,
                    filename=track.filename,
                    first_failed_at=track.first_failed_at,
                    ignored_at=track.ignored_at,
                    local_track_id=track.local_track_id,
                    source_mtime_ns=track.source_mtime_ns,
                    source_path=track.source_path,
                    source_size=track.source_size,
                )
                for track in tracks
            ]
        )

    @router.post(
        "/maintenance/unidentified/{attempt_id}/retry",
        response_model=UnidentifiedRetryResponse,
        status_code=202,
    )
    def retry_unidentified(
        attempt_id: int,
        engine: Engine = Depends(get_engine),
    ) -> UnidentifiedRetryResponse:
        failure_store = FailedIngestionAttemptStore(engine=engine)
        attempt = failure_store.get(attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Unidentified source not found")

        source_path = Path(attempt.source_path)
        if not source_path.is_file():
            failure_store.clear_for_source_path(source_path)
            raise HTTPException(status_code=404, detail="Source file not found")

        redis_url = _require_redis_url()
        failure_store.clear_for_source_path(source_path)
        job_id = IngestionJobEnqueuer(redis_url).enqueue(source_path)
        return UnidentifiedRetryResponse(
            id=attempt.id,
            job_id=job_id,
            source_path=attempt.source_path,
        )

    @router.post(
        "/maintenance/unidentified/{attempt_id}/ignore",
        response_model=UnidentifiedIgnoreResponse,
    )
    def ignore_unidentified(
        attempt_id: int,
        engine: Engine = Depends(get_engine),
    ) -> UnidentifiedIgnoreResponse:
        failure_store = FailedIngestionAttemptStore(engine=engine)
        if failure_store.get(attempt_id) is None:
            raise HTTPException(status_code=404, detail="Unidentified source not found")

        attempt = failure_store.mark_ignored(attempt_id)
        if attempt is None:
            raise HTTPException(
                status_code=409,
                detail="Source file changed; stale failure was cleared",
            )
        if attempt.ignored_at is None:
            raise HTTPException(
                status_code=500,
                detail="Failed to mark unidentified source ignored",
            )

        return UnidentifiedIgnoreResponse(
            id=attempt.id,
            ignored_at=attempt.ignored_at.isoformat(),
            source_path=attempt.source_path,
        )

    @router.post(
        "/maintenance/unidentified/{attempt_id}/restore",
        response_model=UnidentifiedRestoreResponse,
    )
    def restore_unidentified(
        attempt_id: int,
        engine: Engine = Depends(get_engine),
    ) -> UnidentifiedRestoreResponse:
        failure_store = FailedIngestionAttemptStore(engine=engine)
        attempt = failure_store.restore(attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Unidentified source not found")

        return UnidentifiedRestoreResponse(
            id=attempt.id,
            ignored_at=None,
            source_path=attempt.source_path,
        )

    return router
