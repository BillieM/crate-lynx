import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.ingestion import BeetsImporter, IngestionProcessor, IngestionWatcher


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ingestion_root = Path(os.environ.get("INGESTION_ROOT", "/ingestion"))
    staging_root = Path(
        os.environ.get("INGESTION_STAGING_ROOT", "/tmp/crate-lynx-ingestion-staging")
    )
    library_root = Path(os.environ.get("LIBRARY_ROOT", "/library"))
    processor = IngestionProcessor(
        staging_root=staging_root,
        beets_importer=BeetsImporter(
            beet_binary=os.environ.get("BEET_BINARY", "beet"),
            library_root=library_root,
            library_database=os.environ.get("BEETS_LIBRARY"),
        ),
    )
    watcher = IngestionWatcher(
        root=ingestion_root,
        on_new_file=lambda path: logger.info(
            "Ingested track candidate: %s",
            processor.process(path).prepared_path,
        ),
    )
    watcher.start()

    try:
        yield
    finally:
        watcher.stop()


app = FastAPI(title="crate-lynx", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
