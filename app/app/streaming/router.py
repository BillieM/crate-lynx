import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.core.queueing import StreamingSyncJobEnqueuer
from app.streaming.schemas import (
    CreateStreamingAccountRequest,
    PlaylistDetail,
    PlaylistDetailResponse,
    PlaylistSyncResponse,
    PlaylistTrackResponse,
    PlaylistTracksResponse,
    StreamingAccountResponse,
    StreamingAccountsResponse,
    StreamingPlaylistConfigListResponse,
    StreamingPlaylistConfigResponse,
    StreamingTrackDetailResponse,
    StreamingTrackLocalLinkResponse,
    StreamingTrackLocalSummaryResponse,
    StreamingTrackPendingLocalSuggestionResponse,
    StreamingTrackPlaylistAppearanceResponse,
    StreamingTrackRelationshipPeerResponse,
    StreamingTrackRelationshipResponse,
    StreamingTrackSearchResponse,
    StreamingTrackSearchResultResponse,
    StreamingPlaylistResponse,
    StreamingPlaylistsResponse,
    StreamingSyncResponse,
    UpdateStreamingAccountAuthRequest,
    UpdateStreamingPlaylistRequest,
)
from app.streaming.adapters.youtube_music import (
    YouTubeMusicAuthValidationError,
    validate_youtube_music_browser_auth,
)
from app.streaming.models import PLAYLIST_SYNC_MODE_FULL
from app.streaming.store import StreamingAccountStore


def create_router(
    *,
    require_redis_url: Callable[[], str],
) -> APIRouter:
    router = APIRouter()

    def _store(engine: Engine) -> StreamingAccountStore:
        return StreamingAccountStore(engine=engine)

    def serialize_datetime(value: object) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

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

    def streaming_playlist_payload(playlist: object) -> dict[str, object]:
        return {
            "id": playlist.id,
            "account_id": playlist.account_id,
            "provider_playlist_id": playlist.provider_playlist_id,
            "title": playlist.title,
            "sync_mode": playlist.sync_mode,
            "provider_track_count": playlist.provider_track_count,
            "imported_track_count": playlist.imported_track_count,
            "metadata_synced_at": serialize_datetime(playlist.metadata_synced_at),
            "tracks_synced_at": serialize_datetime(playlist.tracks_synced_at),
            "last_sync_error": playlist.last_sync_error,
            "last_sync_error_at": serialize_datetime(playlist.last_sync_error_at),
        }

    def serialize_streaming_playlist(playlist: object) -> StreamingPlaylistResponse:
        return StreamingPlaylistResponse(**streaming_playlist_payload(playlist))

    def serialize_streaming_playlist_config(
        playlist: object,
    ) -> StreamingPlaylistConfigResponse:
        return StreamingPlaylistConfigResponse(**streaming_playlist_payload(playlist))

    def serialize_playlist_detail(playlist: object) -> PlaylistDetailResponse:
        return PlaylistDetailResponse(
            playlist=PlaylistDetail(
                id=playlist.id,
                account_id=playlist.account_id,
                provider_playlist_id=playlist.provider_playlist_id,
                name=playlist.title,
                cover_art_url=playlist.cover_art_url,
                sync_mode=playlist.sync_mode,
                provider_track_count=playlist.provider_track_count,
                imported_track_count=playlist.imported_track_count,
                linked_count=playlist.linked_count,
                pending_count=playlist.pending_count,
                unlinked_count=playlist.unlinked_count,
                metadata_synced_at=serialize_datetime(playlist.metadata_synced_at),
                tracks_synced_at=serialize_datetime(playlist.tracks_synced_at),
                last_sync_error=playlist.last_sync_error,
                last_sync_error_at=serialize_datetime(playlist.last_sync_error_at),
            )
        )

    def serialize_streaming_track_peer(
        track: object,
    ) -> StreamingTrackRelationshipPeerResponse:
        return StreamingTrackRelationshipPeerResponse(
            id=track.id,
            provider_track_id=track.provider_track_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            year=track.year,
            isrc=track.isrc,
            duration_ms=track.duration_ms,
        )

    def serialize_local_summary(track: object) -> StreamingTrackLocalSummaryResponse:
        return StreamingTrackLocalSummaryResponse(
            id=track.id,
            file_path=track.file_path,
            library_root_rel_path=track.library_root_rel_path,
            title=track.title,
            artist=track.artist,
            album=track.album,
        )

    def serialize_local_link(link: object) -> StreamingTrackLocalLinkResponse:
        return StreamingTrackLocalLinkResponse(
            final_link_id=link.final_link_id,
            local_track_id=link.local_track_id,
            source_streaming_track_id=link.source_streaming_track_id,
            resolution_source=link.resolution_source,
            approved_at=serialize_datetime(link.approved_at) or "",
            local_track=serialize_local_summary(link.local_track),
        )

    def serialize_streaming_track_detail(track: object) -> StreamingTrackDetailResponse:
        return StreamingTrackDetailResponse(
            id=track.id,
            provider_track_id=track.provider_track_id,
            title=track.title,
            artist=track.artist,
            album=track.album,
            year=track.year,
            isrc=track.isrc,
            duration_ms=track.duration_ms,
            resolved_local_link=(
                serialize_local_link(track.resolved_local_link)
                if track.resolved_local_link is not None
                else None
            ),
            equivalent_tracks=[
                serialize_streaming_track_peer(peer) for peer in track.equivalent_tracks
            ],
            relationships=[
                StreamingTrackRelationshipResponse(
                    id=relationship.id,
                    relationship_type=relationship.relationship_type,
                    accepted_at=serialize_datetime(relationship.accepted_at) or "",
                    peer_track=serialize_streaming_track_peer(relationship.peer_track),
                )
                for relationship in track.relationships
            ],
            playlist_appearances=[
                StreamingTrackPlaylistAppearanceResponse(
                    playlist_id=appearance.playlist_id,
                    account_id=appearance.account_id,
                    provider_playlist_id=appearance.provider_playlist_id,
                    title=appearance.title,
                    sync_mode=appearance.sync_mode,
                    position=appearance.position,
                )
                for appearance in track.playlist_appearances
            ],
            pending_local_suggestions=[
                StreamingTrackPendingLocalSuggestionResponse(
                    id=suggestion.id,
                    local_track_id=suggestion.local_track_id,
                    match_method=suggestion.match_method,
                    score=suggestion.score,
                    status=suggestion.status,
                    created_at=serialize_datetime(suggestion.created_at) or "",
                    local_track=serialize_local_summary(suggestion.local_track),
                )
                for suggestion in track.pending_local_suggestions
            ],
        )

    def validate_browser_headers(browser_headers: dict[str, object]) -> None:
        try:
            validate_youtube_music_browser_auth(browser_headers)
        except YouTubeMusicAuthValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def require_streaming_account(
        store: StreamingAccountStore,
        account_id: int,
    ) -> None:
        if not any(account.id == account_id for account in store.list_accounts()):
            raise HTTPException(status_code=404, detail="Streaming account not found")

    @router.get("/streaming/accounts", response_model=StreamingAccountsResponse)
    def list_streaming_accounts(
        engine: Engine = Depends(get_engine),
    ) -> StreamingAccountsResponse:
        accounts = _store(engine).list_accounts()
        return StreamingAccountsResponse(
            accounts=[serialize_streaming_account(account) for account in accounts]
        )

    @router.get("/streaming/playlists", response_model=StreamingPlaylistsResponse)
    def list_streaming_playlists(
        engine: Engine = Depends(get_engine),
    ) -> StreamingPlaylistsResponse:
        playlists = _store(engine).list_playlists(sync_mode=PLAYLIST_SYNC_MODE_FULL)
        return StreamingPlaylistsResponse(
            playlists=[serialize_streaming_playlist(playlist) for playlist in playlists]
        )

    @router.get(
        "/streaming/playlists/config",
        response_model=StreamingPlaylistConfigListResponse,
    )
    def list_streaming_playlist_config(
        engine: Engine = Depends(get_engine),
    ) -> StreamingPlaylistConfigListResponse:
        playlists = _store(engine).list_playlists()
        return StreamingPlaylistConfigListResponse(
            playlists=[
                serialize_streaming_playlist_config(playlist) for playlist in playlists
            ]
        )

    @router.patch(
        "/streaming/playlists/{playlist_id}",
        response_model=StreamingPlaylistConfigResponse,
    )
    def update_streaming_playlist(
        playlist_id: int,
        payload: UpdateStreamingPlaylistRequest,
        engine: Engine = Depends(get_engine),
    ) -> StreamingPlaylistConfigResponse:
        playlist = _store(engine).set_playlist_sync_mode(
            playlist_id=playlist_id,
            sync_mode=payload.sync_mode,
        )
        if playlist is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        return serialize_streaming_playlist_config(playlist)

    @router.get("/playlists/{playlist_id}", response_model=PlaylistDetailResponse)
    def get_playlist_detail(
        playlist_id: int,
        engine: Engine = Depends(get_engine),
    ) -> PlaylistDetailResponse:
        playlist = _store(engine).get_playlist_detail(
            playlist_id,
            sync_mode=PLAYLIST_SYNC_MODE_FULL,
        )
        if playlist is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        return serialize_playlist_detail(playlist)

    @router.get(
        "/playlists/{playlist_id}/tracks", response_model=PlaylistTracksResponse
    )
    def list_playlist_tracks(
        playlist_id: int,
        engine: Engine = Depends(get_engine),
    ) -> PlaylistTracksResponse:
        store = _store(engine)
        if not store.playlist_exists(
            playlist_id,
            sync_mode=PLAYLIST_SYNC_MODE_FULL,
        ):
            raise HTTPException(status_code=404, detail="Playlist not found")

        return PlaylistTracksResponse(
            tracks=[
                PlaylistTrackResponse(
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
                for track in store.list_playlist_tracks(playlist_id)
            ]
        )

    @router.get(
        "/streaming/tracks/search",
        response_model=StreamingTrackSearchResponse,
    )
    def search_streaming_tracks(
        q: str = "",
        limit: int = 20,
        engine: Engine = Depends(get_engine),
    ) -> StreamingTrackSearchResponse:
        tracks = _store(engine).search_tracks(
            query=q,
            limit=max(1, min(limit, 50)),
        )
        return StreamingTrackSearchResponse(
            tracks=[
                StreamingTrackSearchResultResponse(
                    id=track.id,
                    provider_track_id=track.provider_track_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    year=track.year,
                    isrc=track.isrc,
                    duration_ms=track.duration_ms,
                    link_status=track.link_status,
                    final_link_id=track.final_link_id,
                    local_track_id=track.local_track_id,
                )
                for track in tracks
            ]
        )

    @router.get(
        "/streaming/tracks/{streaming_track_id}",
        response_model=StreamingTrackDetailResponse,
    )
    def get_streaming_track_detail(
        streaming_track_id: int,
        engine: Engine = Depends(get_engine),
    ) -> StreamingTrackDetailResponse:
        track = _store(engine).get_track_detail(streaming_track_id)
        if track is None:
            raise HTTPException(status_code=404, detail="Streaming track not found")

        return serialize_streaming_track_detail(track)

    @router.get("/playlists/{playlist_id}/m3u")
    def export_playlist_m3u(
        playlist_id: int,
        engine: Engine = Depends(get_engine),
    ) -> Response:
        from app.m3u.generator import build_m3u_filename, generate_m3u

        store = _store(engine)
        playlist = store.get_playlist_summary(
            playlist_id,
            sync_mode=PLAYLIST_SYNC_MODE_FULL,
        )
        if playlist is None:
            raise HTTPException(status_code=404, detail="Playlist not found")

        library_root = Path(os.environ.get("LIBRARY_ROOT", "/nas/media/music"))
        content = generate_m3u(playlist_id, library_root, engine=engine)
        filename = build_m3u_filename(playlist.title)
        return Response(
            content=content,
            media_type="audio/x-mpegurl",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post(
        "/streaming/accounts",
        response_model=StreamingAccountResponse,
        status_code=201,
    )
    def create_streaming_account(
        payload: CreateStreamingAccountRequest,
        engine: Engine = Depends(get_engine),
    ) -> StreamingAccountResponse:
        validate_browser_headers(payload.browser_headers)
        store = _store(engine)
        account = store.create_youtube_music_account(
            display_name=payload.display_name,
            browser_headers=payload.browser_headers,
        )

        created_account = next(
            account_record
            for account_record in store.list_accounts()
            if account_record.id == account.id
        )
        return serialize_streaming_account(created_account)

    @router.patch(
        "/streaming/accounts/{account_id}/auth",
        response_model=StreamingAccountResponse,
    )
    def update_streaming_account_auth(
        account_id: int,
        payload: UpdateStreamingAccountAuthRequest,
        engine: Engine = Depends(get_engine),
    ) -> StreamingAccountResponse:
        store = _store(engine)
        require_streaming_account(store, account_id)

        validate_browser_headers(payload.browser_headers)
        account = store.update_youtube_music_account_auth(
            account_id=account_id,
            browser_headers=payload.browser_headers,
        )
        if account is None:
            raise HTTPException(status_code=404, detail="Streaming account not found")

        return serialize_streaming_account(account)

    @router.post(
        "/streaming/accounts/{account_id}/sync",
        response_model=StreamingSyncResponse,
        status_code=202,
    )
    def sync_streaming_account(
        account_id: int,
        engine: Engine = Depends(get_engine),
    ) -> StreamingSyncResponse:
        store = _store(engine)
        require_streaming_account(store, account_id)

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue(
            account_id=account_id,
        )
        return StreamingSyncResponse(account_id=account_id, job_id=job_id)

    @router.post(
        "/streaming/accounts/{account_id}/refresh-metadata",
        response_model=StreamingSyncResponse,
        status_code=202,
    )
    def refresh_streaming_account_metadata(
        account_id: int,
        engine: Engine = Depends(get_engine),
    ) -> StreamingSyncResponse:
        store = _store(engine)
        require_streaming_account(store, account_id)

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue_metadata_refresh(
            account_id=account_id,
        )
        return StreamingSyncResponse(account_id=account_id, job_id=job_id)

    @router.post(
        "/streaming/playlists/{playlist_id}/sync",
        response_model=PlaylistSyncResponse,
        status_code=202,
    )
    def sync_streaming_playlist(
        playlist_id: int,
        engine: Engine = Depends(get_engine),
    ) -> PlaylistSyncResponse:
        store = _store(engine)
        if not store.playlist_exists(playlist_id):
            raise HTTPException(status_code=404, detail="Playlist not found")

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue_playlist_sync(
            playlist_id=playlist_id,
        )
        return PlaylistSyncResponse(playlist_id=playlist_id, job_id=job_id)

    return router
