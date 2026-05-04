from pydantic import BaseModel


class LibraryTrackResponse(BaseModel):
    id: int
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None
    file_path: str
    library_root_rel_path: str
    link_status: str
    match_method: str | None
    file_status: str


class LibraryTracksResponse(BaseModel):
    tracks: list[LibraryTrackResponse]
