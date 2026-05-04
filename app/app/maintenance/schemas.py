from pydantic import BaseModel


class MissingLocallyTrackResponse(BaseModel):
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    playlist_count: int
    playlist_titles: list[str]


class MissingLocallyResponse(BaseModel):
    tracks: list[MissingLocallyTrackResponse]
