from pydantic import BaseModel


class LibraryTrackResponse(BaseModel):
    id: int
    final_link_id: int | None
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None
    file_path: str
    library_root_rel_path: str
    link_status: str
    match_method: str | None
    file_status: str


class LibraryStatsResponse(BaseModel):
    total: int
    linked: int
    pending: int
    unlinked: int


class LibraryTracksResponse(BaseModel):
    stats: LibraryStatsResponse
    tracks: list[LibraryTrackResponse]
    next_cursor: int | None
