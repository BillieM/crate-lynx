from pydantic import BaseModel


class StreamingAccountResponse(BaseModel):
    id: int
    provider: str
    display_name: str
    auth_state: str
    auth_error: str | None
    auth_error_at: str | None
    created_at: str
    updated_at: str


class StreamingPlaylistResponse(BaseModel):
    id: int
    account_id: int
    provider_playlist_id: str
    title: str
    track_count: int
    synced_at: str | None


class CreateStreamingAccountRequest(BaseModel):
    display_name: str
    browser_headers: dict[str, object]


class StreamingSyncResponse(BaseModel):
    account_id: int
    job_id: str
