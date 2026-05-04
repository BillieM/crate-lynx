from pydantic import BaseModel


class IngestFolderResponse(BaseModel):
    id: int
    path: str


class GeneralSettingsResponse(BaseModel):
    ingest_folders: list[IngestFolderResponse]


class CreateIngestFolderRequest(BaseModel):
    path: str
