from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine, get_engine
from app.m3u.exporter import (
    InvalidM3uExportFormatError,
    M3uExportPackage,
    M3uExportPlaylistNotFoundError,
    build_m3u_export_package,
    build_m3u_export_zip,
)
from app.m3u.generator import InvalidM3uExportPathFormatError
from app.m3u.schemas import (
    CreateM3uExportProfileRequest,
    M3uExportPlaylistPreviewResponse,
    M3uExportPreviewResponse,
    M3uExportProfileListResponse,
    M3uExportProfileResponse,
    M3uExportRequest,
    UpdateM3uExportProfileRequest,
)
from app.m3u.store import (
    InvalidM3uExportLibraryPathError,
    InvalidM3uExportProfileNameError,
    M3uExportProfileNotFoundError,
    M3uExportProfileStore,
    normalize_m3u_export_library_path,
)


def create_router(
    *,
    require_database_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: object) -> Engine:
        if isinstance(engine, Engine):
            return engine
        return create_database_engine(
            require_database_url() if require_database_url is not None else None
        )

    def _store(engine: Engine) -> M3uExportProfileStore:
        return M3uExportProfileStore(engine=engine)

    @router.get(
        "/m3u/export-profiles",
        response_model=M3uExportProfileListResponse,
    )
    def list_export_profiles(
        engine: Engine = Depends(get_engine),
    ) -> M3uExportProfileListResponse:
        return M3uExportProfileListResponse(
            profiles=[
                _serialize_profile(profile)
                for profile in _store(_engine(engine)).list_profiles()
            ]
        )

    @router.post(
        "/m3u/export-profiles",
        response_model=M3uExportProfileResponse,
        status_code=201,
    )
    def create_export_profile(
        payload: CreateM3uExportProfileRequest,
        engine: Engine = Depends(get_engine),
    ) -> M3uExportProfileResponse:
        try:
            profile = _store(_engine(engine)).create_profile(
                name=payload.name,
                library_path=payload.library_path,
                is_default=payload.is_default,
            )
        except (
            InvalidM3uExportLibraryPathError,
            InvalidM3uExportProfileNameError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return _serialize_profile(profile)

    @router.patch(
        "/m3u/export-profiles/{profile_id}",
        response_model=M3uExportProfileResponse,
    )
    def update_export_profile(
        profile_id: int,
        payload: UpdateM3uExportProfileRequest,
        engine: Engine = Depends(get_engine),
    ) -> M3uExportProfileResponse:
        try:
            profile = _store(_engine(engine)).update_profile(
                profile_id=profile_id,
                name=payload.name,
                library_path=payload.library_path,
                is_default=payload.is_default,
            )
        except M3uExportProfileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Export profile not found"
            ) from exc
        except (
            InvalidM3uExportLibraryPathError,
            InvalidM3uExportProfileNameError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return _serialize_profile(profile)

    @router.delete("/m3u/export-profiles/{profile_id}", status_code=204)
    def delete_export_profile(
        profile_id: int,
        engine: Engine = Depends(get_engine),
    ) -> Response:
        try:
            _store(_engine(engine)).delete_profile(profile_id)
        except M3uExportProfileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Export profile not found"
            ) from exc

        return Response(status_code=204)

    @router.post(
        "/m3u/export/preview",
        response_model=M3uExportPreviewResponse,
    )
    def preview_export(
        payload: M3uExportRequest,
        engine: Engine = Depends(get_engine),
    ) -> M3uExportPreviewResponse:
        try:
            export_package = _build_export_package(
                payload,
                engine=_engine(engine),
                persist_initial_profile=False,
            )
        except M3uExportProfileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Export profile not found"
            ) from exc
        except M3uExportPlaylistNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidM3uExportFormatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except InvalidM3uExportPathFormatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except InvalidM3uExportLibraryPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return _serialize_preview(export_package)

    @router.post("/m3u/export")
    def export_m3u_zip(
        payload: M3uExportRequest,
        engine: Engine = Depends(get_engine),
    ) -> Response:
        try:
            export_package = _build_export_package(
                payload,
                engine=_engine(engine),
                persist_initial_profile=True,
            )
        except M3uExportProfileNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Export profile not found"
            ) from exc
        except M3uExportPlaylistNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidM3uExportFormatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except InvalidM3uExportPathFormatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except InvalidM3uExportLibraryPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        archive = build_m3u_export_zip(export_package)
        return Response(
            content=archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="m3u-export.zip"',
            },
        )

    return router


def _build_export_package(
    payload: M3uExportRequest,
    *,
    engine: Engine,
    persist_initial_profile: bool,
) -> M3uExportPackage:
    store = M3uExportProfileStore(engine=engine)
    should_persist_initial_profile = False
    if payload.profile_id is not None:
        profile = store.get_profile(payload.profile_id)
        if profile is None:
            raise M3uExportProfileNotFoundError(str(payload.profile_id))
        library_path = profile.library_path
    else:
        if payload.library_path is None:
            raise InvalidM3uExportLibraryPathError("Music library path is required")
        library_path = normalize_m3u_export_library_path(payload.library_path)
        if persist_initial_profile:
            should_persist_initial_profile = True

    export_package = build_m3u_export_package(
        engine=engine,
        formats=payload.formats,
        generated_playlist_ids=payload.generated_playlist_ids,
        library_path=library_path,
        path_format=payload.path_format,
        playlist_ids=payload.playlist_ids,
    )
    if should_persist_initial_profile:
        store.create_default_profile_if_none(library_path=library_path)

    return export_package


def _serialize_profile(profile: object) -> M3uExportProfileResponse:
    return M3uExportProfileResponse(
        id=profile.id,
        name=profile.name,
        library_path=profile.library_path,
        is_default=profile.is_default,
    )


def _serialize_preview(export_package: M3uExportPackage) -> M3uExportPreviewResponse:
    return M3uExportPreviewResponse(
        library_path=export_package.library_path,
        formats=list(export_package.formats),
        path_format=export_package.path_format,
        playlist_count=len(export_package.playlists),
        total_exported_track_count=export_package.total_exported_track_count,
        total_skipped_track_count=export_package.total_skipped_track_count,
        playlists=[
            M3uExportPlaylistPreviewResponse(
                playlist_id=playlist.playlist_id,
                generated_playlist_id=playlist.generated_playlist_id,
                source=playlist.source,
                title=playlist.title,
                filename_m3u=playlist.filename_m3u,
                filename_m3u8=playlist.filename_m3u8,
                filenames=playlist.filenames(export_package.formats),
                exported_track_count=playlist.rendered.exported_track_count,
                skipped_track_count=playlist.rendered.skipped_track_count,
                sample_path=playlist.rendered.sample_path,
            )
            for playlist in export_package.playlists
        ],
    )
