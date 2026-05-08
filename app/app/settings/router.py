from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine, get_engine
from app.settings.schemas import (
    CreateIngestFolderRequest,
    GeneralSettingsResponse,
    IngestFolderResponse,
)
from app.settings.store import (
    DuplicateIngestFolderPathError,
    GeneralSettingsStore,
    IngestFolderNotFoundError,
    InvalidIngestFolderPathError,
)


IngestFolderMutationCallback = Callable[[str], None]


def create_router(
    *,
    require_database_url: Callable[[], str] | None = None,
    on_ingest_folder_created: IngestFolderMutationCallback | None = None,
    on_ingest_folder_deleted: IngestFolderMutationCallback | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: object) -> Engine:
        if isinstance(engine, Engine):
            return engine
        return create_database_engine(
            require_database_url() if require_database_url is not None else None
        )

    @router.get("/settings/general", response_model=GeneralSettingsResponse)
    def get_general_settings(
        engine: Engine = Depends(get_engine),
    ) -> GeneralSettingsResponse:
        folders = GeneralSettingsStore(engine=_engine(engine)).list_ingest_folders()
        return GeneralSettingsResponse(
            ingest_folders=[_serialize_ingest_folder(folder) for folder in folders]
        )

    @router.post(
        "/settings/ingest-folders",
        response_model=IngestFolderResponse,
        status_code=201,
    )
    def create_ingest_folder(
        payload: CreateIngestFolderRequest,
        engine: Engine = Depends(get_engine),
    ) -> IngestFolderResponse:
        try:
            folder = GeneralSettingsStore(engine=_engine(engine)).create_ingest_folder(
                payload.path
            )
        except InvalidIngestFolderPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DuplicateIngestFolderPathError as exc:
            raise HTTPException(
                status_code=409,
                detail="Ingest folder path already exists",
            ) from exc

        if on_ingest_folder_created is not None:
            on_ingest_folder_created(folder.path)

        return _serialize_ingest_folder(folder)

    @router.delete("/settings/ingest-folders/{folder_id}", status_code=204)
    def delete_ingest_folder(
        folder_id: int,
        engine: Engine = Depends(get_engine),
    ) -> Response:
        try:
            folder = GeneralSettingsStore(engine=_engine(engine)).delete_ingest_folder(
                folder_id
            )
        except IngestFolderNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Ingest folder not found"
            ) from exc

        if on_ingest_folder_deleted is not None:
            on_ingest_folder_deleted(folder.path)

        return Response(status_code=204)

    return router


def _serialize_ingest_folder(folder: object) -> IngestFolderResponse:
    return IngestFolderResponse(id=folder.id, path=folder.path)
