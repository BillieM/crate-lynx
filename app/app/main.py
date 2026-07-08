import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import RuntimeConfig, load_runtime_config
from app.core.db import create_database_engine
from app.core.paths import resolve_staging_path
from app.ingestion import IngestionJobEnqueuer, IngestionWatcher
from app.ingestion.failures import FailedIngestionAttemptStore
from app.library.router import create_router as create_library_router
from app.links.router import create_router as create_links_router
from app.local_dedupe.router import create_router as create_local_dedupe_router
from app.local_tracks.router import create_router as create_local_tracks_router
from app.maintenance.router import create_router as create_maintenance_router
from app.matching.router import create_router as create_matching_router
from app.m3u.router import create_router as create_m3u_router
from app.relationships.router import create_router as create_relationships_router
from app.rescue.router import create_router as create_rescue_router
from app.settings.router import create_router as create_settings_router
from app.settings.store import GeneralSettingsStore
from app.shell.router import create_router as create_shell_router
from app.sonic.router import create_router as create_sonic_router
from app.soulseek.router import create_router as create_soulseek_router
from app.streaming import crypto
from app.streaming.router import create_router as create_streaming_router


logger = logging.getLogger(__name__)


class HealthzResponse(BaseModel):
    ok: bool
    database: str


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = load_runtime_config()
        for warning in config.warnings:
            logger.warning(warning)

        database_url = config.database_url
        redis_url = config.redis_url
        if database_url or config.token_encryption_key:
            crypto.validate_token_encryption_key()
        database_engine = create_database_engine(database_url) if database_url else None
        app.state.database_engine = database_engine
        ingest_roots = _resolve_ingest_roots(database_engine, config)
        ingestion_enqueuer = IngestionJobEnqueuer(redis_url) if redis_url else None
        failed_attempt_store = (
            FailedIngestionAttemptStore(engine=database_engine)
            if database_engine is not None
            else None
        )

        def enqueue_new_file(path: Path) -> None:
            if ingestion_enqueuer is None:
                logger.error(
                    "REDIS_URL is not configured; skipping ingestion candidate: %s",
                    path,
                )
                return

            if (
                failed_attempt_store is not None
                and failed_attempt_store.should_skip_auto_enqueue(path)
            ):
                logger.info("Skipped unchanged failed ingestion source: %s", path)
                return

            job_id = ingestion_enqueuer.enqueue(path)
            if job_id is None:
                logger.info("Skipped duplicate ingestion candidate: %s", path)
                return

            logger.info("Queued ingestion candidate: %s job_id=%s", path, job_id)

        watcher = IngestionWatcher(
            root=ingest_roots,
            on_new_file=enqueue_new_file,
            recursive=True,
            stability_workers=config.ingestion_stability_workers,
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

    @app.get("/healthz", response_model=HealthzResponse)
    def healthz() -> HealthzResponse:
        database_engine = getattr(app.state, "database_engine", None)
        if database_engine is None:
            if load_runtime_config().database_url:
                raise HTTPException(
                    status_code=503,
                    detail={"ok": False, "database": "unavailable"},
                )
            return HealthzResponse(ok=True, database="not_configured")

        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.exception("Health check database ping failed")
            raise HTTPException(
                status_code=503,
                detail={"ok": False, "database": "unavailable"},
            ) from exc

        return HealthzResponse(ok=True, database="ok")

    def require_redis_url() -> str:
        redis_url = load_runtime_config().redis_url
        if not redis_url:
            raise HTTPException(
                status_code=503,
                detail="REDIS_URL must be configured for background jobs",
            )
        return redis_url

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
        create_maintenance_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_links_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_relationships_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_local_tracks_router(),
        prefix="/api",
    )
    app.include_router(
        create_local_dedupe_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_m3u_router(),
        prefix="/api",
    )
    app.include_router(
        create_sonic_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_soulseek_router(
            require_redis_url=require_redis_url,
        ),
        prefix="/api",
    )
    app.include_router(
        create_settings_router(
            on_ingest_folder_created=lambda path: _add_active_ingest_root(app, path),
            on_ingest_folder_deleted=lambda path: _remove_active_ingest_root(app, path),
        ),
        prefix="/api",
    )
    app.include_router(create_shell_router(), prefix="/api")

    return app


def get_ingestion_staging_root() -> Path:
    return resolve_staging_path("INGESTION_STAGING_ROOT", "ingestion-staging")


def _resolve_ingest_roots(
    database_engine: Engine | None,
    config: RuntimeConfig | None = None,
) -> list[Path]:
    resolved_config = config or load_runtime_config()
    if database_engine is None:
        return [resolved_config.ingestion_root]

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
