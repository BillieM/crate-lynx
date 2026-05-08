import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.ingestion import BeetsImporter, IngestionProcessor, IngestionWatcher
from app.ingestion.failures import FailedIngestionAttemptStore
from app.library.router import create_router as create_library_router
from app.links.router import create_router as create_links_router
from app.local_tracks.router import create_router as create_local_tracks_router
from app.local_tracks.store import LocalTrackStore
from app.maintenance.router import create_router as create_maintenance_router
from app.matching.jobs import MatchingJobEnqueuer
from app.matching.router import create_router as create_matching_router
from app.rescue.router import create_router as create_rescue_router
from app.settings.router import create_router as create_settings_router
from app.settings.store import GeneralSettingsStore
from app.streaming import crypto
from app.streaming.router import create_router as create_streaming_router
from app.system.router import router as system_router


logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        staging_root = Path(
            os.environ.get(
                "INGESTION_STAGING_ROOT", "/tmp/crate-lynx-ingestion-staging"
            )
        )
        library_root = Path(os.environ.get("LIBRARY_ROOT", "/music"))
        database_url = os.environ.get("DATABASE_URL")
        redis_url = os.environ.get("REDIS_URL")
        if database_url or os.environ.get("TOKEN_ENCRYPTION_KEY"):
            crypto.validate_token_encryption_key()
        database_engine = create_database_engine(database_url) if database_url else None
        app.state.database_engine = database_engine
        ingest_roots = _resolve_ingest_roots(database_engine)
        processor = IngestionProcessor(
            staging_root=staging_root,
            beets_importer=BeetsImporter(
                beet_binary=os.environ.get("BEET_BINARY", "beet"),
                library_root=library_root,
                library_database=os.environ.get(
                    "BEETS_LIBRARY", "/data/beets/library.db"
                ),
            ),
            track_store=(
                LocalTrackStore(engine=database_engine)
                if database_engine is not None
                else None
            ),
            failed_attempt_store=(
                FailedIngestionAttemptStore(engine=database_engine)
                if database_engine is not None
                else None
            ),
            matching_job_enqueuer=MatchingJobEnqueuer(redis_url) if redis_url else None,
            database_engine=database_engine,
        )

        def process_new_file(path: Path) -> None:
            prepared = processor.process(path)
            logger.info("Ingested track candidate: %s", prepared.library_path)

        watcher = IngestionWatcher(
            root=ingest_roots,
            on_new_file=process_new_file,
            recursive=True,
        )
        app.state.ingestion_watcher = watcher
        watcher.start()

        try:
            yield
        finally:
            watcher.stop()
            app.state.ingestion_watcher = None
            if database_engine is not None:
                database_engine.dispose()
            app.state.database_engine = None

    app = FastAPI(title="crate-lynx", lifespan=lifespan)

    def require_redis_url() -> str:
        redis_url = os.environ.get("REDIS_URL")
        if not redis_url:
            raise HTTPException(
                status_code=503,
                detail="REDIS_URL must be configured for streaming sync jobs",
            )
        return redis_url

    app.include_router(system_router)
    app.include_router(
        create_streaming_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_matching_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_rescue_router(),
        prefix="/api",
    )
    app.include_router(
        create_library_router(),
        prefix="/api",
    )
    app.include_router(
        create_maintenance_router(),
        prefix="/api",
    )
    app.include_router(
        create_links_router(),
        prefix="/api",
    )
    app.include_router(
        create_local_tracks_router(),
        prefix="/api",
    )
    app.include_router(
        create_settings_router(
            on_ingest_folder_created=lambda path: _add_active_ingest_root(app, path),
            on_ingest_folder_deleted=lambda path: _remove_active_ingest_root(app, path),
        ),
        prefix="/api",
    )

    return app


def _resolve_ingest_roots(database_engine: Engine | None) -> list[Path]:
    if database_engine is None:
        return [Path(os.environ.get("INGESTION_ROOT", "/ingestion"))]

    folders = GeneralSettingsStore(engine=database_engine).seed_default_ingest_folders()
    return [Path(folder.path) for folder in folders]


def _add_active_ingest_root(app: FastAPI, path: str) -> None:
    watcher = getattr(app.state, "ingestion_watcher", None)
    if watcher is not None:
        watcher.add_root(path)


def _remove_active_ingest_root(app: FastAPI, path: str) -> None:
    watcher = getattr(app.state, "ingestion_watcher", None)
    if watcher is not None:
        watcher.remove_root(path)


app = create_app()
