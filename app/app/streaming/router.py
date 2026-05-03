import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from app.core.queueing import StreamingSyncJobEnqueuer
from app.streaming.schemas import (
    CreateStreamingAccountRequest,
    PlaylistDetail,
    PlaylistDetailResponse,
    PlaylistSyncResponse,
    PlaylistTrackResponse,
    PlaylistTracksResponse,
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
            last_sync_error=playlist.last_sync_error,
            last_sync_error_at=(
                playlist.last_sync_error_at.isoformat()
                if playlist.last_sync_error_at is not None
                else None
            ),
        )

    def serialize_playlist_detail(playlist: object) -> PlaylistDetailResponse:
        return PlaylistDetailResponse(
            playlist=PlaylistDetail(
                id=playlist.id,
                account_id=playlist.account_id,
                provider_playlist_id=playlist.provider_playlist_id,
                name=playlist.title,
                cover_art_url=playlist.cover_art_url,
                track_count=playlist.track_count,
                linked_count=playlist.linked_count,
                pending_count=playlist.pending_count,
                unlinked_count=playlist.unlinked_count,
                synced_at=(
                    playlist.synced_at.isoformat()
                    if playlist.synced_at is not None
                    else None
                ),
                last_sync_error=playlist.last_sync_error,
                last_sync_error_at=(
                    playlist.last_sync_error_at.isoformat()
                    if playlist.last_sync_error_at is not None
                    else None
                ),
            )
        )

    def serialize_playlist_track(track: object) -> PlaylistTrackResponse:
        return PlaylistTrackResponse(
            id=track.id,
            provider_track_id=track.provider_track_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            duration_ms=track.duration_ms,
            position=track.position,
            status=track.status,
            final_link_id=track.final_link_id,
            local_track_id=track.local_track_id,
            proposal_id=track.proposal_id,
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

    @router.get("/playlists/{playlist_id}")
    async def get_playlist_detail(playlist_id: int) -> PlaylistDetailResponse:
        playlist = StreamingAccountStore(require_database_url()).get_playlist_detail(
            playlist_id
        )
        if playlist is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        return serialize_playlist_detail(playlist)

    @router.get("/playlists/{playlist_id}/tracks")
    async def list_playlist_tracks(playlist_id: int) -> PlaylistTracksResponse:
        store = StreamingAccountStore(require_database_url())
        if store.get_playlist_detail(playlist_id) is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        return PlaylistTracksResponse(
            tracks=[
                serialize_playlist_track(track)
                for track in store.list_playlist_tracks(playlist_id)
            ]
        )

    @router.get("/playlists/{playlist_id}/m3u")
    async def export_playlist_m3u(playlist_id: int) -> Response:
        from app.m3u.generator import build_m3u_filename, generate_m3u

        store = StreamingAccountStore(require_database_url())
        playlist = next(
            (
                playlist
                for playlist in store.list_playlists()
                if playlist.id == playlist_id
            ),
            None,
        )
        if playlist is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        library_root = Path(os.environ.get("LIBRARY_ROOT", "/library"))
        content = generate_m3u(playlist_id, library_root)
        filename = build_m3u_filename(playlist.title)
        return Response(
            content=content,
            media_type="audio/x-mpegurl",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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

    @router.post(
        "/streaming/accounts/{account_id}/refresh-metadata",
        status_code=202,
    )
    async def refresh_streaming_account_metadata(
        account_id: int,
    ) -> StreamingSyncResponse:
        database_url = require_database_url()
        store = StreamingAccountStore(database_url)
        if not any(account.id == account_id for account in store.list_accounts()):
            raise HTTPException(status_code=404, detail="Streaming account not found")

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue_metadata_refresh(
            account_id=account_id,
        )
        return StreamingSyncResponse(account_id=account_id, job_id=job_id)

    @router.post("/streaming/playlists/{playlist_id}/sync", status_code=202)
    async def sync_streaming_playlist(playlist_id: int) -> PlaylistSyncResponse:
        store = StreamingAccountStore(require_database_url())
        if not any(playlist.id == playlist_id for playlist in store.list_playlists()):
            raise HTTPException(status_code=404, detail="Playlist not found")

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue_playlist_sync(
            playlist_id=playlist_id,
        )
        return PlaylistSyncResponse(playlist_id=playlist_id, job_id=job_id)

    return router
