from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from app.core.queueing import StreamingSyncJobEnqueuer
from app.streaming.schemas import (
    CreateStreamingAccountRequest,
    StreamingAccountResponse,
    StreamingPlaylistResponse,
    StreamingSyncResponse,
)
from app.streaming.store import StreamingAccountStore


def create_router(
    *,
    require_database_url: Callable[[], str],
    require_redis_url: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    def serialize_streaming_account(account: object) -> StreamingAccountResponse:
        return StreamingAccountResponse(
            id=account.id,
            provider=account.provider,
            display_name=account.display_name,
            auth_state=account.auth_state,
            auth_error=account.auth_error,
            auth_error_at=(
                account.auth_error_at.isoformat()
                if account.auth_error_at is not None
                else None
            ),
            created_at=account.created_at.isoformat(),
            updated_at=account.updated_at.isoformat(),
        )

    def serialize_streaming_playlist(playlist: object) -> StreamingPlaylistResponse:
        return StreamingPlaylistResponse(
            id=playlist.id,
            account_id=playlist.account_id,
            provider_playlist_id=playlist.provider_playlist_id,
            title=playlist.title,
            track_count=playlist.track_count,
            synced_at=(
                playlist.synced_at.isoformat()
                if playlist.synced_at is not None
                else None
            ),
        )

    @router.get("/streaming/accounts")
    async def list_streaming_accounts() -> dict[str, list[StreamingAccountResponse]]:
        accounts = StreamingAccountStore(require_database_url()).list_accounts()
        return {
            "accounts": [serialize_streaming_account(account) for account in accounts]
        }

    @router.get("/streaming/playlists")
    async def list_streaming_playlists() -> dict[str, list[StreamingPlaylistResponse]]:
        playlists = StreamingAccountStore(require_database_url()).list_playlists()
        return {
            "playlists": [
                serialize_streaming_playlist(playlist) for playlist in playlists
            ]
        }

    @router.post("/streaming/accounts", status_code=201)
    async def create_streaming_account(
        payload: CreateStreamingAccountRequest,
    ) -> StreamingAccountResponse:
        database_url = require_database_url()
        account = StreamingAccountStore(database_url).create_youtube_music_account(
            display_name=payload.display_name,
            browser_headers=payload.browser_headers,
        )

        created_account = next(
            account_record
            for account_record in StreamingAccountStore(database_url).list_accounts()
            if account_record.id == account.id
        )
        return serialize_streaming_account(created_account)

    @router.post("/streaming/accounts/{account_id}/sync", status_code=202)
    async def sync_streaming_account(account_id: int) -> StreamingSyncResponse:
        database_url = require_database_url()
        store = StreamingAccountStore(database_url)
        if not any(account.id == account_id for account in store.list_accounts()):
            raise HTTPException(status_code=404, detail="Streaming account not found")

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue(
            account_id=account_id,
        )
        return StreamingSyncResponse(account_id=account_id, job_id=job_id)

    return router
