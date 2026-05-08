from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.local_tracks.schemas import (
    LocalTrackDetailResponse,
    LocalTrackFailedIngestionResponse,
    LocalTrackFinalLinkResponse,
    LocalTrackSuggestionResponse,
)
from app.local_tracks.store import LocalTrackStore


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get(
        "/local-tracks/{local_track_id}", response_model=LocalTrackDetailResponse
    )
    def get_local_track_detail(
        local_track_id: int,
        engine: Engine = Depends(get_engine),
    ) -> LocalTrackDetailResponse:
        detail = LocalTrackStore(engine=engine).get_detail(local_track_id)

        if detail is None:
            raise HTTPException(status_code=404, detail="Local track not found")

        return LocalTrackDetailResponse(
            id=detail.id,
            file_path=detail.file_path,
            library_root_rel_path=detail.library_root_rel_path,
            link_status=detail.link_status,
            final_link=(
                LocalTrackFinalLinkResponse(
                    id=detail.final_link.id,
                    streaming_track_id=detail.final_link.streaming_track_id,
                    approved_at=detail.final_link.approved_at,
                )
                if detail.final_link is not None
                else None
            ),
            pending_suggestions=[
                LocalTrackSuggestionResponse(
                    id=suggestion.id,
                    streaming_track_id=suggestion.streaming_track_id,
                    match_method=suggestion.match_method,
                    score=suggestion.score,
                    status=suggestion.status,
                    created_at=suggestion.created_at,
                )
                for suggestion in detail.pending_suggestions
            ],
            failed_ingestion_attempts=[
                LocalTrackFailedIngestionResponse(
                    id=attempt.id,
                    source_path=attempt.source_path,
                    filename=attempt.filename,
                    failure_reason=attempt.failure_reason,
                    failed_at=attempt.failed_at,
                )
                for attempt in detail.failed_ingestion_attempts
            ],
        )

    return router
