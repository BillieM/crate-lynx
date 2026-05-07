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
    failed_at: str
    failure_reason: str
    filename: str
    local_track_id: int | None
    source_path: str


class UnidentifiedResponse(BaseModel):
    tracks: list[UnidentifiedTrackResponse]
