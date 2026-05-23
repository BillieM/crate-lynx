import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.local_tracks.schemas import (
    BeetsAlbumDetailResponse,
    BeetsItemDetailResponse,
    LocalTrackDetailResponse,
    LocalTrackFailedIngestionResponse,
    LocalTrackFinalLinkResponse,
    LocalTrackSearchResponse,
    LocalTrackSearchResultResponse,
    LocalTrackSuggestionResponse,
    MetadataFieldResponse,
    StreamingTrackSummaryResponse,
)
from app.local_tracks.store import LocalTrackStore


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/local-tracks/search", response_model=LocalTrackSearchResponse)
    def search_local_tracks(
        q: str = "",
        limit: int = 20,
        engine: Engine = Depends(get_engine),
    ) -> LocalTrackSearchResponse:
        tracks = LocalTrackStore(engine=engine).search(
            query=q,
            limit=max(1, min(limit, 50)),
        )
        return LocalTrackSearchResponse(
            tracks=[
                LocalTrackSearchResultResponse(
                    id=track.id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    file_path=track.file_path,
                    library_root_rel_path=track.library_root_rel_path,
                    link_status=track.link_status,
                    final_link_id=track.final_link_id,
                )
                for track in tracks
            ]
        )

    @router.get("/local-tracks/{local_track_id}/audio", response_class=FileResponse)
    def get_local_track_audio(
        local_track_id: int,
        engine: Engine = Depends(get_engine),
    ) -> FileResponse:
        file_path = LocalTrackStore(engine=engine).get_file_path(local_track_id)
        if file_path is None:
            raise HTTPException(status_code=404, detail="Local track not found")

        audio_path = _resolve_library_audio_path(file_path)
        if audio_path is None or not audio_path.is_file():
            raise HTTPException(status_code=404, detail="Local audio file not found")

        return FileResponse(
            audio_path,
            content_disposition_type="inline",
            filename=audio_path.name,
            media_type=mimetypes.guess_type(audio_path.name)[0]
            or "application/octet-stream",
        )

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
            fingerprint=detail.fingerprint,
            beets_id=detail.beets_id,
            created_at=detail.created_at,
            updated_at=detail.updated_at,
            link_status=detail.link_status,
            title=detail.title,
            artist=detail.artist,
            album=detail.album,
            duration_ms=detail.duration_ms,
            final_link=(
                LocalTrackFinalLinkResponse(
                    id=detail.final_link.id,
                    streaming_track_id=detail.final_link.streaming_track_id,
                    approved_at=detail.final_link.approved_at,
                    streaming_track=_streaming_track_summary_response(
                        detail.final_link.streaming_track
                    ),
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
                    streaming_track=_streaming_track_summary_response(
                        suggestion.streaming_track
                    ),
                )
                for suggestion in detail.pending_suggestions
            ],
            beets_item=(
                BeetsItemDetailResponse(
                    beets_id=detail.beets_item.beets_id,
                    fields=_metadata_field_responses(detail.beets_item.fields),
                    attributes=_metadata_field_responses(detail.beets_item.attributes),
                )
                if detail.beets_item is not None
                else None
            ),
            beets_album=(
                BeetsAlbumDetailResponse(
                    beets_album_id=detail.beets_album.beets_album_id,
                    fields=_metadata_field_responses(detail.beets_album.fields),
                    attributes=_metadata_field_responses(detail.beets_album.attributes),
                )
                if detail.beets_album is not None
                else None
            ),
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


def _streaming_track_summary_response(track) -> StreamingTrackSummaryResponse:
    return StreamingTrackSummaryResponse(
        id=track.streaming_track_id,
        provider_track_id=track.provider_track_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        year=track.year,
        isrc=track.isrc,
        duration_ms=track.duration_ms,
    )


def _metadata_field_responses(fields) -> list[MetadataFieldResponse]:
    return [MetadataFieldResponse(key=field.key, value=field.value) for field in fields]


def _resolve_library_audio_path(file_path: str) -> Path | None:
    library_root = Path(os.environ.get("LIBRARY_ROOT", "/nas/media/music")).resolve()
    candidate = (library_root / Path(file_path)).resolve()

    try:
        candidate.relative_to(library_root)
    except ValueError:
        return None

    return candidate
