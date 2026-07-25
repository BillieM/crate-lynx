from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.sonic.generation import (
    build_generation_preview,
    normalize_generation_config,
)
from app.sonic.jobs import SonicJobEnqueuer, enqueue_sonic_feature_backfill
from app.sonic.models import PLAYLIST_GENERATION_TRIGGER_RECIPE
from app.sonic.profiles import resolve_feature_profile_from_config
from app.sonic.schemas import (
    CreatePlaylistGenerationRunRequest,
    CreatePlaylistGenerationRunResponse,
    DeletePlaylistGenerationRunsRequest,
    DeletePlaylistGenerationRunsResponse,
    GeneratedPlaylistListResponse,
    GeneratedPlaylistResponse,
    GeneratedPlaylistTrackResponse,
    GeneratedPlaylistTracksResponse,
    PlaylistGenerationProjectionResponse,
    PlaylistGenerationRecipeListResponse,
    PlaylistGenerationRecipeResponse,
    PlaylistGenerationRecipeUpsertRequest,
    PlaylistGenerationRunDetailResponse,
    PlaylistGenerationRunListResponse,
    PlaylistGenerationRunResponse,
    RegeneratePlaylistGenerationRecipeResponse,
    SonicBackfillRequest,
    SonicBackfillResponse,
    SonicFeatureSummaryResponse,
    SonicGenerationPreviewResponse,
)
from app.sonic.store import (
    PlaylistGenerationRecipeNameConflictError,
    PlaylistGenerationRecipeNotFoundError,
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
        tracks = _store(engine).ready_tracks_for_source(
            payload.source_filter.model_dump(),
            analyzer_key=profile.analyzer_key,
            analyzer_version=profile.analyzer_version,
        )
        actual_preview = build_generation_preview(
            tracks,
            generation_config,
            failed_feature_count=preview.failed_feature_count,
            missing_feature_count=preview.missing_feature_count,
            pending_feature_count=preview.pending_feature_count,
            source_track_count=preview.source_track_count,
        )
        projection = _actual_projection(actual_preview["playlists"])
        return SonicGenerationPreviewResponse(
            analyzer_key=preview.analyzer_key,
            analyzer_version=preview.analyzer_version,
            can_generate=bool(actual_preview["readiness"]["can_generate"]),
            failed_feature_count=preview.failed_feature_count,
            feature_profile=preview.feature_profile,
            missing_feature_count=preview.missing_feature_count,
            pending_feature_count=preview.pending_feature_count,
            projection=PlaylistGenerationProjectionResponse.model_validate(projection),
            ready_track_count=preview.ready_track_count,
            skipped_track_count=preview.skipped_track_count,
            source_track_count=preview.source_track_count,
            analyzer_evidence=actual_preview["analyzer_evidence"],
            confidence=actual_preview["confidence"],
            coverage=actual_preview["coverage"],
            current_feature_count=preview.current_feature_count,
            legacy_descriptor_feature_count=preview.legacy_descriptor_feature_count,
            playlists=actual_preview["playlists"],
            readiness=actual_preview["readiness"],
            skipped_reasons=actual_preview["skipped_reasons"],
            warnings=actual_preview["warnings"],
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
            run_name=payload.run_name or "Generated crates",
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

    @router.get(
        "/sonic/recipes",
        response_model=PlaylistGenerationRecipeListResponse,
    )
    def list_generation_recipes(
        engine: Engine = Depends(get_engine),
    ) -> PlaylistGenerationRecipeListResponse:
        return PlaylistGenerationRecipeListResponse(
            recipes=[
                _recipe_response(recipe)
                for recipe in _store(engine).list_generation_recipes()
            ]
        )

    @router.post(
        "/sonic/recipes",
        response_model=PlaylistGenerationRecipeResponse,
        status_code=201,
    )
    def create_generation_recipe(
        payload: PlaylistGenerationRecipeUpsertRequest,
        engine: Engine = Depends(get_engine),
    ) -> PlaylistGenerationRecipeResponse:
        try:
            recipe = _store(engine).create_generation_recipe(
                enabled=payload.enabled,
                export_config=payload.export_config,
                generation_config=normalize_generation_config(
                    payload.generation_config.model_dump()
                ),
                name=payload.name,
                regenerate_on_change=payload.regenerate_on_change,
                source_filter=payload.source_filter.model_dump(),
            )
        except PlaylistGenerationRecipeNameConflictError as exc:
            raise HTTPException(
                status_code=409, detail="Recipe name already exists"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _recipe_response(recipe)

    @router.put(
        "/sonic/recipes/{recipe_id}",
        response_model=PlaylistGenerationRecipeResponse,
    )
    def update_generation_recipe(
        recipe_id: int,
        payload: PlaylistGenerationRecipeUpsertRequest,
        engine: Engine = Depends(get_engine),
    ) -> PlaylistGenerationRecipeResponse:
        try:
            recipe = _store(engine).update_generation_recipe(
                recipe_id,
                enabled=payload.enabled,
                export_config=payload.export_config,
                generation_config=normalize_generation_config(
                    payload.generation_config.model_dump()
                ),
                name=payload.name,
                regenerate_on_change=payload.regenerate_on_change,
                source_filter=payload.source_filter.model_dump(),
            )
        except PlaylistGenerationRecipeNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Recipe not found") from exc
        except PlaylistGenerationRecipeNameConflictError as exc:
            raise HTTPException(
                status_code=409, detail="Recipe name already exists"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _recipe_response(recipe)

    @router.delete("/sonic/recipes/{recipe_id}", status_code=204)
    def delete_generation_recipe(
        recipe_id: int,
        engine: Engine = Depends(get_engine),
    ) -> Response:
        try:
            _store(engine).delete_generation_recipe(recipe_id)
        except PlaylistGenerationRecipeNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Recipe not found") from exc
        return Response(status_code=204)

    @router.post(
        "/sonic/recipes/{recipe_id}/regenerate",
        response_model=RegeneratePlaylistGenerationRecipeResponse,
        status_code=201,
    )
    def regenerate_generation_recipe(
        recipe_id: int,
        engine: Engine = Depends(get_engine),
    ) -> RegeneratePlaylistGenerationRecipeResponse:
        store = _store(engine)
        recipe = store.get_generation_recipe(recipe_id)
        if recipe is None:
            raise HTTPException(status_code=404, detail="Recipe not found")
        run = store.create_generation_run(
            generation_config=normalize_generation_config(
                recipe.generation_config_json
            ),
            recipe_id=recipe.id,
            run_name=recipe.name,
            source_filter=recipe.source_filter_json,
            trigger=PLAYLIST_GENERATION_TRIGGER_RECIPE,
        )
        try:
            job_id = _enqueuer().enqueue_generation(run.id)
        except Exception as exc:
            store.mark_generation_run_failed(
                run.id,
                f"Failed to enqueue playlist generation job: {exc}",
            )
            raise HTTPException(
                status_code=503,
                detail="Failed to enqueue playlist generation job",
            ) from exc
        return RegeneratePlaylistGenerationRecipeResponse(
            recipe=_recipe_response(recipe),
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
        recipe_id=run.recipe_id,
        run_name=run.run_name,
        trigger=run.trigger,
        readiness_summary=run.readiness_summary_json,
        analyzer_evidence=run.analyzer_evidence_json,
        playlist_count=run.playlist_count,
        track_count=run.track_count,
        error_detail=run.error_detail,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _recipe_response(recipe) -> PlaylistGenerationRecipeResponse:
    return PlaylistGenerationRecipeResponse(
        id=recipe.id,
        name=recipe.name,
        source_filter=recipe.source_filter_json,
        generation_config=recipe.generation_config_json,
        enabled=recipe.enabled,
        regenerate_on_change=recipe.regenerate_on_change,
        export_config=recipe.export_config_json,
        last_run_id=recipe.last_run_id,
        last_regenerated_at=recipe.last_regenerated_at,
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
    )


def _actual_projection(playlists: list[dict[str, object]]) -> dict[str, object]:
    sizes = sorted(
        int(playlist["size"])
        for playlist in playlists
        if isinstance(playlist.get("size"), int)
    )
    depth_counts: dict[str, int] = {}
    for playlist in playlists:
        depth = str(playlist.get("depth", 0))
        depth_counts[depth] = depth_counts.get(depth, 0) + 1
    leaf_count = sum(bool(playlist.get("export_default")) for playlist in playlists)
    midpoint = sizes[len(sizes) // 2] if sizes else 0
    return {
        "config_notes": [],
        "depth_counts": depth_counts,
        "leaf_playlist_count": leaf_count,
        "mode": "actual",
        "playlist_count": len(playlists),
        "sample_names": [
            str(playlist["name"])
            for playlist in playlists[:5]
            if isinstance(playlist.get("name"), str)
        ],
        "size_max": max(sizes) if sizes else 0,
        "size_median": midpoint,
        "size_min": min(sizes) if sizes else 0,
    }


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
