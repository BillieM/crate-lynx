from typing import Literal

from pydantic import BaseModel

PlaylistSyncMode = Literal["off", "match_only", "full"]


class StreamingAccountResponse(BaseModel):
    id: int
    provider: str
    display_name: str
    auth_state: str
    auth_error: str | None
    auth_error_at: str | None
    created_at: str
    updated_at: str


class StreamingAccountsResponse(BaseModel):
    accounts: list[StreamingAccountResponse]


class StreamingPlaylistResponse(BaseModel):
    id: int
    account_id: int
    provider_playlist_id: str
    title: str
    sync_mode: PlaylistSyncMode
    provider_track_count: int | None
    imported_track_count: int
    metadata_synced_at: str | None
    tracks_synced_at: str | None
    last_sync_error: str | None
    last_sync_error_at: str | None


class StreamingPlaylistConfigResponse(StreamingPlaylistResponse):
    pass


class StreamingPlaylistsResponse(BaseModel):
    playlists: list[StreamingPlaylistResponse]


class StreamingPlaylistConfigListResponse(BaseModel):
    playlists: list[StreamingPlaylistConfigResponse]


class UpdateStreamingPlaylistRequest(BaseModel):
    sync_mode: PlaylistSyncMode


class PlaylistDetail(BaseModel):
    id: int
    account_id: int
    provider_playlist_id: str
    name: str
    cover_art_url: str | None
    sync_mode: PlaylistSyncMode
    provider_track_count: int | None
    imported_track_count: int
    linked_count: int
    pending_count: int
    unlinked_count: int
    metadata_synced_at: str | None
    tracks_synced_at: str | None
    last_sync_error: str | None
    last_sync_error_at: str | None


class PlaylistDetailResponse(BaseModel):
    playlist: PlaylistDetail


class PlaylistTrackResponse(BaseModel):
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    duration_ms: int | None
    position: int
    status: str
    final_link_id: int | None
    local_track_id: int | None
    proposal_id: int | None


class PlaylistTracksResponse(BaseModel):
    tracks: list[PlaylistTrackResponse]


class CreateStreamingAccountRequest(BaseModel):
    display_name: str
    browser_headers: dict[str, object]


class UpdateStreamingAccountAuthRequest(BaseModel):
    browser_headers: dict[str, object]


class StreamingSyncResponse(BaseModel):
    account_id: int
    job_id: str


class PlaylistSyncResponse(BaseModel):
    playlist_id: int
    job_id: str
