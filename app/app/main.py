import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request

from app.ingest_status import IngestionStatusStore
from app.ingestion import BeetsImporter, IngestionProcessor, IngestionWatcher
from app.local_tracks import LocalTrackStore
from app.queueing import MatchingJobEnqueuer, QueueDepthReader
from app.worker import resolve_queue_names


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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ingest/status")
    async def ingest_status(request: Request) -> dict[str, object]:
        return {"status": "ok", **request.app.state.ingestion_status.snapshot()}

    return app


app = create_app()
