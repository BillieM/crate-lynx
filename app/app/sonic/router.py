from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.sonic.generation import normalize_generation_config
from app.sonic.jobs import SonicJobEnqueuer, enqueue_sonic_feature_backfill
from app.sonic.schemas import (
    CreatePlaylistGenerationRunRequest,
    CreatePlaylistGenerationRunResponse,
    DeletePlaylistGenerationRunsRequest,
    DeletePlaylistGenerationRunsResponse,
    GeneratedPlaylistListResponse,
    GeneratedPlaylistResponse,
    GeneratedPlaylistTrackResponse,
    GeneratedPlaylistTracksResponse,
    PlaylistGenerationRunDetailResponse,
    PlaylistGenerationRunListResponse,
    PlaylistGenerationRunResponse,
    SonicBackfillRequest,
    SonicBackfillResponse,
    SonicFeatureSummaryResponse,
    SonicGenerationPreviewResponse,
)
from app.sonic.profiles import resolve_feature_profile_from_config
from app.sonic.store import (
    PlaylistGenerationRunActiveError,
    PlaylistGenerationRunNotFoundError,
    SonicStore,
)


def create_router(
    *,
    require_redis_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _store(engine: Engine) -> SonicStore:
        return SonicStore(engine=engine)

    def _redis_url() -> str:
        if require_redis_url is None:
            raise HTTPException(
                status_code=503,
                detail="REDIS_URL must be configured for sonic background jobs",
            )
        return require_redis_url()

    def _enqueuer() -> SonicJobEnqueuer:
        return SonicJobEnqueuer(_redis_url())

    @router.get("/sonic/features/summary", response_model=SonicFeatureSummaryResponse)
    def get_feature_summary(
        engine: Engine = Depends(get_engine),
    ) -> SonicFeatureSummaryResponse:
        summary = _store(engine).feature_summary()
        return SonicFeatureSummaryResponse(
            total_tracks=summary.total_tracks,
            ready_tracks=summary.ready_tracks,
            pending_tracks=summary.pending_tracks,
            failed_tracks=summary.failed_tracks,
            missing_tracks=summary.missing_tracks,
        )

    @router.post("/sonic/features/backfill", response_model=SonicBackfillResponse)
    def backfill_features(
        payload: SonicBackfillRequest,
        engine: Engine = Depends(get_engine),
    ) -> SonicBackfillResponse:
        result = enqueue_sonic_feature_backfill(
            limit=payload.limit,
            redis_url=_redis_url(),
            store=_store(engine),
        )
        return SonicBackfillResponse(job_id=result.job_id, limit=payload.limit)

    @router.get("/sonic/runs", response_model=PlaylistGenerationRunListResponse)
    def list_generation_runs(
        engine: Engine = Depends(get_engine),
    ) -> PlaylistGenerationRunListResponse:
        return PlaylistGenerationRunListResponse(
            runs=[_run_response(run) for run in _store(engine).list_generation_runs()]
        )

    @router.post(
        "/sonic/runs/preview",
        response_model=SonicGenerationPreviewResponse,
    )
    def preview_generation_run(
        payload: CreatePlaylistGenerationRunRequest,
        engine: Engine = Depends(get_engine),
    ) -> SonicGenerationPreviewResponse:
        generation_config = normalize_generation_config(
            payload.generation_config.model_dump()
        )
        profile = resolve_feature_profile_from_config(generation_config)
        preview = _store(engine).generation_preview(
            payload.source_filter.model_dump(),
            analyzer_key=profile.analyzer_key,
            analyzer_version=profile.analyzer_version,
            feature_profile=profile.key,
        )
        return SonicGenerationPreviewResponse(
            analyzer_key=preview.analyzer_key,
            analyzer_version=preview.analyzer_version,
            can_generate=preview.can_generate,
            failed_feature_count=preview.failed_feature_count,
            feature_profile=preview.feature_profile,
            missing_feature_count=preview.missing_feature_count,
            pending_feature_count=preview.pending_feature_count,
            ready_track_count=preview.ready_track_count,
            skipped_track_count=preview.skipped_track_count,
            source_track_count=preview.source_track_count,
        )

    @router.post(
        "/sonic/runs",
        response_model=CreatePlaylistGenerationRunResponse,
        status_code=201,
    )
    def create_generation_run(
        payload: CreatePlaylistGenerationRunRequest,
        engine: Engine = Depends(get_engine),
    ) -> CreatePlaylistGenerationRunResponse:
        source_filter = payload.source_filter.model_dump()
        generation_config = normalize_generation_config(
            payload.generation_config.model_dump()
        )
        store = _store(engine)
        enqueuer = _enqueuer()
        run = store.create_generation_run(
            generation_config=generation_config,
            source_filter=source_filter,
        )
        try:
            job_id = enqueuer.enqueue_generation(run.id)
        except Exception as exc:
            store.mark_generation_run_failed(
                run.id,
                f"Failed to enqueue playlist generation job: {exc}",
            )
            raise HTTPException(
                status_code=503,
                detail="Failed to enqueue playlist generation job",
            ) from exc
        return CreatePlaylistGenerationRunResponse(
            run=_run_response(run),
            job_id=job_id,
        )

    @router.post(
        "/sonic/runs/delete-selected",
        response_model=DeletePlaylistGenerationRunsResponse,
    )
    def delete_selected_generation_runs(
        payload: DeletePlaylistGenerationRunsRequest,
        engine: Engine = Depends(get_engine),
    ) -> DeletePlaylistGenerationRunsResponse:
        store = _store(engine)
        deleted_run_ids: list[int] = []
        missing_run_ids: list[int] = []
        skipped_active_run_ids: list[int] = []

        for run_id in payload.run_ids:
            try:
                store.delete_generation_run(run_id)
            except PlaylistGenerationRunNotFoundError:
                missing_run_ids.append(run_id)
            except PlaylistGenerationRunActiveError:
                skipped_active_run_ids.append(run_id)
            else:
                deleted_run_ids.append(run_id)

        return DeletePlaylistGenerationRunsResponse(
            deleted_run_ids=deleted_run_ids,
            missing_run_ids=missing_run_ids,
            skipped_active_run_ids=skipped_active_run_ids,
        )

    @router.get(
        "/sonic/runs/{run_id}",
        response_model=PlaylistGenerationRunDetailResponse,
    )
    def get_generation_run(
        run_id: int,
        engine: Engine = Depends(get_engine),
    ) -> PlaylistGenerationRunDetailResponse:
        store = _store(engine)
        run = store.get_generation_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Generation run not found")

        return PlaylistGenerationRunDetailResponse(
            run=_run_response(run),
            playlists=[
                _generated_playlist_response(playlist)
                for playlist in store.list_generated_playlists(run_id=run_id)
            ],
        )

    @router.delete("/sonic/runs/{run_id}", status_code=204)
    def delete_generation_run(
        run_id: int,
        engine: Engine = Depends(get_engine),
    ) -> Response:
        try:
            _store(engine).delete_generation_run(run_id)
        except PlaylistGenerationRunNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Generation run not found"
            ) from exc
        except PlaylistGenerationRunActiveError as exc:
            raise HTTPException(
                status_code=409,
                detail="Active generation runs cannot be deleted",
            ) from exc

        return Response(status_code=204)

    @router.get(
        "/sonic/generated-playlists",
        response_model=GeneratedPlaylistListResponse,
    )
    def list_generated_playlists(
        engine: Engine = Depends(get_engine),
    ) -> GeneratedPlaylistListResponse:
        return GeneratedPlaylistListResponse(
            playlists=[
                _generated_playlist_response(playlist)
                for playlist in _store(engine).list_generated_playlists(limit=500)
            ]
        )

    @router.get(
        "/sonic/generated-playlists/{generated_playlist_id}/tracks",
        response_model=GeneratedPlaylistTracksResponse,
    )
    def list_generated_playlist_tracks(
        generated_playlist_id: int,
        engine: Engine = Depends(get_engine),
    ) -> GeneratedPlaylistTracksResponse:
        store = _store(engine)
        if store.get_generated_playlist(generated_playlist_id) is None:
            raise HTTPException(status_code=404, detail="Generated playlist not found")

        return GeneratedPlaylistTracksResponse(
            tracks=[
                GeneratedPlaylistTrackResponse(
                    id=track.id,
                    local_track_id=track.local_track_id,
                    position=track.position,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration_ms=track.duration_ms,
                    file_path=track.file_path,
                    library_root_rel_path=track.library_root_rel_path,
                )
                for track in store.list_generated_playlist_tracks(generated_playlist_id)
            ]
        )

    return router


def _run_response(run) -> PlaylistGenerationRunResponse:
    return PlaylistGenerationRunResponse(
        id=run.id,
        generation_number=run.generation_number,
        status=run.status,
        source_filter=run.source_filter_json,
        generation_config=run.generation_config_json,
        playlist_count=run.playlist_count,
        track_count=run.track_count,
        error_detail=run.error_detail,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _generated_playlist_response(playlist) -> GeneratedPlaylistResponse:
    return GeneratedPlaylistResponse(
        id=playlist.id,
        run_id=playlist.run_id,
        parent_playlist_id=playlist.parent_playlist_id,
        depth=playlist.depth,
        position=playlist.position,
        name=playlist.name,
        summary=playlist.summary_json,
        track_count=playlist.track_count,
        created_at=playlist.created_at,
    )
