"""Streaming domain package."""

from app.streaming.jobs import run_youtube_music_sync_job
from app.streaming.models import (
    PlaylistMembershipRecord,
    PersistedStreamingAccount,
    StoredStreamingAccount,
    StreamingAccountRecord,
    StreamingPlaylistRecord,
    StreamingPlaylistSummary,
    StreamingTrackRecord,
    STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
    STREAMING_ACCOUNT_AUTH_STATE_ERROR,
    YOUTUBE_MUSIC_PROVIDER,
    metadata,
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.router import create_router
from app.streaming.schemas import (
    CreateStreamingAccountRequest,
    StreamingAccountResponse,
    StreamingPlaylistResponse,
    StreamingSyncResponse,
)
from app.streaming.store import StreamingAccountStore

__all__ = [
    "PlaylistMembershipRecord",
    "PersistedStreamingAccount",
    "StoredStreamingAccount",
    "StreamingAccountRecord",
    "StreamingAccountStore",
    "StreamingPlaylistRecord",
    "StreamingPlaylistSummary",
    "StreamingTrackRecord",
    "STREAMING_ACCOUNT_AUTH_STATE_CONNECTED",
    "STREAMING_ACCOUNT_AUTH_STATE_ERROR",
    "CreateStreamingAccountRequest",
    "StreamingAccountResponse",
    "StreamingPlaylistResponse",
    "YOUTUBE_MUSIC_PROVIDER",
    "StreamingSyncResponse",
    "create_router",
    "metadata",
    "playlist_membership_table",
    "run_youtube_music_sync_job",
    "streaming_accounts_table",
    "streaming_playlists_table",
    "streaming_tracks_table",
]
