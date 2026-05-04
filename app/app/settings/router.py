from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Response

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


def create_router(*, require_database_url: Callable[[], str]) -> APIRouter:
    router = APIRouter()

    @router.get("/settings/general", response_model=GeneralSettingsResponse)
    async def get_general_settings() -> GeneralSettingsResponse:
        folders = GeneralSettingsStore(require_database_url()).list_ingest_folders()
        return GeneralSettingsResponse(
            ingest_folders=[_serialize_ingest_folder(folder) for folder in folders]
        )

    @router.post(
        "/settings/ingest-folders",
        response_model=IngestFolderResponse,
        status_code=201,
    )
    async def create_ingest_folder(
        payload: CreateIngestFolderRequest,
    ) -> IngestFolderResponse:
        try:
            folder = GeneralSettingsStore(require_database_url()).create_ingest_folder(
                payload.path
            )
        except InvalidIngestFolderPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DuplicateIngestFolderPathError as exc:
            raise HTTPException(
                status_code=409,
                detail="Ingest folder path already exists",
            ) from exc

        return _serialize_ingest_folder(folder)

    @router.delete("/settings/ingest-folders/{folder_id}", status_code=204)
    async def delete_ingest_folder(folder_id: int) -> Response:
        try:
            GeneralSettingsStore(require_database_url()).delete_ingest_folder(folder_id)
        except IngestFolderNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Ingest folder not found"
            ) from exc

        return Response(status_code=204)

    return router


def _serialize_ingest_folder(folder: object) -> IngestFolderResponse:
    return IngestFolderResponse(id=folder.id, path=folder.path)
