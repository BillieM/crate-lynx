from pydantic import BaseModel


class MissingLocallyTrackResponse(BaseModel):
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    playlist_count: int
    playlist_ids: list[int]
    playlist_titles: list[str]


class MissingLocallyResponse(BaseModel):
    tracks: list[MissingLocallyTrackResponse]


class UnidentifiedTrackResponse(BaseModel):
    id: int
    attempt_count: int
    can_rematch_local_track: bool
    can_rescue_metadata: bool
    failed_at: str
    failure_reason: str
    filename: str
    first_failed_at: str
    ignored_at: str | None
    local_track_id: int | None
    source_mtime_ns: int | None
    source_path: str
    source_size: int | None


class UnidentifiedResponse(BaseModel):
    tracks: list[UnidentifiedTrackResponse]


class UnidentifiedRetryResponse(BaseModel):
    id: int
    job_id: str | None
    source_path: str


class UnidentifiedIgnoreResponse(BaseModel):
    id: int
    ignored_at: str
    source_path: str


class UnidentifiedRestoreResponse(BaseModel):
    id: int
    ignored_at: None
    source_path: str
