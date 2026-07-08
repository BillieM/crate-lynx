from pydantic import BaseModel

from app.sonic.schemas import PlaylistGenerationRunResponse
from app.streaming.schemas import StreamingPlaylistResponse


class ShellCountsResponse(BaseModel):
    library_track_total: int
    link_proposal_count: int
    relationship_suggestion_count: int
    soulseek_unlinked_count: int
    unidentified_active_count: int


class ShellSummaryResponse(BaseModel):
    counts: ShellCountsResponse
    generated_runs: list[PlaylistGenerationRunResponse]
    playlists: list[StreamingPlaylistResponse]
