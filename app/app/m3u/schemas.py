from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.m3u.exporter import (
    DEFAULT_M3U_EXPORT_FORMATS,
    M3uExportFormat,
    normalize_m3u_export_formats,
)
from app.m3u.generator import (
    DEFAULT_M3U_EXPORT_PATH_FORMAT,
    M3uExportPathFormat,
    normalize_m3u_export_path_format,
)


class M3uExportProfileResponse(BaseModel):
    id: int
    name: str
    library_path: str
    is_default: bool


class M3uExportProfileListResponse(BaseModel):
    profiles: list[M3uExportProfileResponse]


class CreateM3uExportProfileRequest(BaseModel):
    name: str
    library_path: str
    is_default: bool = False


class UpdateM3uExportProfileRequest(BaseModel):
    name: str | None = None
    library_path: str | None = None
    is_default: bool | None = None


class M3uExportRequest(BaseModel):
    playlist_ids: list[int] = Field(default_factory=list)
    formats: list[M3uExportFormat] = Field(
        default_factory=lambda: list(DEFAULT_M3U_EXPORT_FORMATS)
    )
    path_format: M3uExportPathFormat = DEFAULT_M3U_EXPORT_PATH_FORMAT
    profile_id: int | None = None
    library_path: str | None = None

    @model_validator(mode="after")
    def normalize_request(self) -> "M3uExportRequest":
        if self.profile_id is None and self.library_path is None:
            raise ValueError("Either profile_id or library_path is required")
        self.formats = list(normalize_m3u_export_formats(self.formats))
        self.path_format = normalize_m3u_export_path_format(self.path_format)
        return self


class M3uExportPlaylistPreviewResponse(BaseModel):
    playlist_id: int
    title: str
    filename_m3u: str
    filename_m3u8: str
    filenames: list[str]
    exported_track_count: int
    skipped_track_count: int
    sample_path: str | None


class M3uExportPreviewResponse(BaseModel):
    library_path: str
    formats: list[M3uExportFormat]
    path_format: M3uExportPathFormat
    playlist_count: int
    total_exported_track_count: int
    total_skipped_track_count: int
    playlists: list[M3uExportPlaylistPreviewResponse]
