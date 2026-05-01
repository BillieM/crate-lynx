import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.ingest_status import IngestionStatusStore
from app.ingestion import BeetsImporter, IngestionProcessor, IngestionWatcher
from app.local_tracks import LocalTrackStore
from app.queueing import (
    MatchingJobEnqueuer,
    QueueDepthReader,
    StreamingSyncJobEnqueuer,
)
from app.streaming_accounts import StreamingAccountStore, connect_youtube_music_account
from app.worker import resolve_queue_names
from app.youtube_music import YouTubeMusicOAuthCredentials


logger = logging.getLogger(__name__)


class StreamingAccountResponse(BaseModel):
    id: int
    provider: str
    display_name: str
    created_at: str
    updated_at: str


class CreateStreamingAccountRequest(BaseModel):
    display_name: str
    client_id: str
    client_secret: str
    open_browser: bool = False


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
            created_at=account.created_at.isoformat(),
            updated_at=account.updated_at.isoformat(),
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

    @app.post("/streaming/accounts", status_code=201)
    async def create_streaming_account(
        payload: CreateStreamingAccountRequest,
    ) -> StreamingAccountResponse:
        database_url = require_database_url()
        account = connect_youtube_music_account(
            database_url=database_url,
            display_name=payload.display_name,
            credentials=YouTubeMusicOAuthCredentials(
                client_id=payload.client_id,
                client_secret=payload.client_secret,
            ),
            open_browser=payload.open_browser,
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
