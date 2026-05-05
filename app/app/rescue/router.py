from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.rescue.metadata import MetadataRescueError, rescue_metadata


def create_router(
    *,
    require_database_url: Callable[[], str],
    require_database_engine: Callable[[], Engine] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: Engine | None) -> Engine:
        if isinstance(engine, Engine):
            return engine
        if require_database_engine is not None:
            return require_database_engine()
        from sqlalchemy import create_engine

        return create_engine(require_database_url())

    @router.post("/local-tracks/{local_track_id}/rescue")
    def rescue_local_track_metadata(
        local_track_id: int,
        engine: object = Depends(require_database_engine)
        if require_database_engine is not None
        else None,
    ) -> dict[str, object]:
        database_url = require_database_url()
        engine = _engine(engine)

        with engine.connect() as connection:
            local_track = (
                connection.execute(
                    select(
                        local_tracks_table.c.id,
                        local_tracks_table.c.file_path,
                        local_tracks_table.c.library_root_rel_path,
                        local_tracks_table.c.beets_id,
                    ).where(local_tracks_table.c.id == local_track_id)
                )
                .mappings()
                .one_or_none()
            )

        if local_track is None:
            raise HTTPException(status_code=404, detail="Local track not found")

        with engine.connect() as connection:
            final_link_id = connection.execute(
                select(final_links_table.c.id).where(
                    final_links_table.c.local_track_id == local_track_id
                )
            ).scalar_one_or_none()

        if final_link_id is None:
            raise HTTPException(
                status_code=409,
                detail=f"No final link exists for local track {local_track_id}",
            )

        try:
            rescue_metadata(
                local_track_id,
                database_url=database_url,
                engine=engine,
                library_root=Path(os.environ.get("LIBRARY_ROOT", "/music")),
            )
        except MetadataRescueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return dict(local_track)

    return router
