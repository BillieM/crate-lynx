import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from app.ingest_status import IngestionStatusStore
from app.ingestion import BeetsImporter, IngestionProcessor, IngestionWatcher
from app.local_tracks import LocalTrackStore
from app.queueing import (
    MatchingJobEnqueuer,
    QueueDepthReader,
    StreamingSyncJobEnqueuer,
)
from app.streaming_accounts import (
    StreamingAccountStore,
    begin_youtube_music_account_oauth,
    complete_youtube_music_account_oauth,
)
from app.worker import resolve_queue_names
from app.youtube_music import YouTubeMusicOAuthCredentials


logger = logging.getLogger(__name__)


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
    client_id: str
    client_secret: str
    device_code: str | None = None
    open_browser: bool = False


class StreamingAccountAuthChallengeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


class SyncStreamingAccountRequest(BaseModel):
    client_id: str
    client_secret: str


class StreamingSyncResponse(BaseModel):
    account_id: int
    job_id: str


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ingestion_root = Path(os.environ.get("INGESTION_ROOT", "/ingestion"))
        staging_root = Path(
            os.environ.get(
                "INGESTION_STAGING_ROOT", "/tmp/crate-lynx-ingestion-staging"
            )
        )
        library_root = Path(os.environ.get("LIBRARY_ROOT", "/library"))
        database_url = os.environ.get("DATABASE_URL")
        redis_url = os.environ.get("REDIS_URL")
        queue_depth_reader = QueueDepthReader(
            redis_url=redis_url,
            queue_names=resolve_queue_names(),
        )
        app.state.ingestion_status = IngestionStatusStore(
            queue_depth_reader=queue_depth_reader.read
        )
        processor = IngestionProcessor(
            staging_root=staging_root,
            beets_importer=BeetsImporter(
                beet_binary=os.environ.get("BEET_BINARY", "beet"),
                library_root=library_root,
                library_database=os.environ.get("BEETS_LIBRARY"),
            ),
            track_store=LocalTrackStore(database_url) if database_url else None,
            matching_job_enqueuer=MatchingJobEnqueuer(redis_url) if redis_url else None,
        )

        def process_new_file(path: Path) -> None:
            try:
                prepared = processor.process(path)
            except Exception as exc:
                app.state.ingestion_status.record_failure(source_path=path, error=exc)
                raise

            app.state.ingestion_status.record_success(
                source_path=path,
                prepared_track=prepared,
            )
            logger.info("Ingested track candidate: %s", prepared.library_path)

        watcher = IngestionWatcher(
            root=ingestion_root,
            on_new_file=process_new_file,
        )
        watcher.start()

        try:
            yield
        finally:
            watcher.stop()

    app = FastAPI(title="crate-lynx", lifespan=lifespan)
    app.state.ingestion_status = IngestionStatusStore(queue_depth_reader=lambda: {})

    def require_database_url() -> str:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise HTTPException(
                status_code=503,
                detail="DATABASE_URL must be configured for streaming account access",
            )
        return database_url

    def require_redis_url() -> str:
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            raise HTTPException(
                status_code=503,
                detail="REDIS_URL must be configured for streaming sync jobs",
            )
        return redis_url

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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ingest/status")
    async def ingest_status(request: Request) -> dict[str, object]:
        return {"status": "ok", **request.app.state.ingestion_status.snapshot()}

    @app.get("/streaming/accounts")
    async def list_streaming_accounts() -> dict[str, list[StreamingAccountResponse]]:
        accounts = StreamingAccountStore(require_database_url()).list_accounts()
        return {
            "accounts": [serialize_streaming_account(account) for account in accounts]
        }

    @app.get("/streaming/playlists")
    async def list_streaming_playlists() -> dict[str, list[StreamingPlaylistResponse]]:
        playlists = StreamingAccountStore(require_database_url()).list_playlists()
        return {
            "playlists": [
                serialize_streaming_playlist(playlist) for playlist in playlists
            ]
        }

    @app.post("/streaming/accounts", status_code=201)
    async def create_streaming_account(
        payload: CreateStreamingAccountRequest,
        response: Response,
    ) -> StreamingAccountResponse | StreamingAccountAuthChallengeResponse:
        database_url = require_database_url()
        credentials = YouTubeMusicOAuthCredentials(
            client_id=payload.client_id,
            client_secret=payload.client_secret,
        )
        if payload.device_code is None:
            auth_code = begin_youtube_music_account_oauth(
                credentials=credentials,
            )
            response.status_code = 202
            return StreamingAccountAuthChallengeResponse(
                device_code=auth_code["device_code"],
                user_code=auth_code["user_code"],
                verification_url=auth_code["verification_url"],
                expires_in=auth_code["expires_in"],
                interval=auth_code["interval"],
            )

        account = complete_youtube_music_account_oauth(
            database_url=database_url,
            display_name=payload.display_name,
            credentials=credentials,
            device_code=payload.device_code,
        )

        created_account = next(
            account_record
            for account_record in StreamingAccountStore(database_url).list_accounts()
            if account_record.id == account.id
        )
        return serialize_streaming_account(created_account)

    @app.post("/streaming/accounts/{account_id}/sync", status_code=202)
    async def sync_streaming_account(
        account_id: int,
        payload: SyncStreamingAccountRequest,
    ) -> StreamingSyncResponse:
        database_url = require_database_url()
        store = StreamingAccountStore(database_url)
        if not any(account.id == account_id for account in store.list_accounts()):
            raise HTTPException(status_code=404, detail="Streaming account not found")

        job_id = StreamingSyncJobEnqueuer(require_redis_url()).enqueue(
            account_id=account_id,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
        )
        return StreamingSyncResponse(account_id=account_id, job_id=job_id)

    return app


app = create_app()
