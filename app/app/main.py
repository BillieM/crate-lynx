import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.ingestion import IngestionWatcher


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    watcher = IngestionWatcher(
        root=os.environ.get("INGESTION_ROOT", "/ingestion"),
        on_new_file=lambda path: logger.info("Queued ingestion candidate: %s", path),
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
