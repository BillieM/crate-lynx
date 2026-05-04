import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from app.ingestion import BeetsImporter, IngestionProcessor, IngestionWatcher
from app.ingestion.failures import FailedIngestionAttemptStore
from app.library.router import create_router as create_library_router
from app.links.router import create_router as create_links_router
from app.local_tracks.store import LocalTrackStore
from app.maintenance.router import create_router as create_maintenance_router
from app.matching.jobs import MatchingJobEnqueuer
from app.matching.router import create_router as create_matching_router
from app.rescue.router import create_router as create_rescue_router
from app.search.router import create_router as create_search_router
from app.streaming.router import create_router as create_streaming_router
from app.system.router import router as system_router


logger = logging.getLogger(__name__)


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
        processor = IngestionProcessor(
            staging_root=staging_root,
            beets_importer=BeetsImporter(
                beet_binary=os.environ.get("BEET_BINARY", "beet"),
                library_root=library_root,
                library_database=os.environ.get("BEETS_LIBRARY"),
            ),
            track_store=LocalTrackStore(database_url) if database_url else None,
            failed_attempt_store=(
                FailedIngestionAttemptStore(database_url) if database_url else None
            ),
            matching_job_enqueuer=MatchingJobEnqueuer(redis_url) if redis_url else None,
        )

        def process_new_file(path: Path) -> None:
            prepared = processor.process(path)
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

    app.include_router(system_router)
    app.include_router(
        create_streaming_router(
            require_database_url=require_database_url,
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_matching_router(
            require_database_url=require_database_url,
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_rescue_router(require_database_url=require_database_url),
        prefix="/api",
    )
    app.include_router(create_search_router(require_database_url=require_database_url))
    app.include_router(
        create_library_router(require_database_url=require_database_url),
        prefix="/api",
    )
    app.include_router(
        create_maintenance_router(require_database_url=require_database_url),
        prefix="/api",
    )
    app.include_router(
        create_links_router(require_database_url=require_database_url),
        prefix="/api",
    )

    return app


app = create_app()
