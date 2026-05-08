from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine, get_engine
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.rescue.metadata import MetadataRescueError, rescue_metadata


def create_router(
    *,
    require_database_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: object) -> Engine:
        if isinstance(engine, Engine):
            return engine
        return create_database_engine(
            require_database_url() if require_database_url is not None else None
        )

    @router.post("/local-tracks/{local_track_id}/rescue")
    def rescue_local_track_metadata(
        local_track_id: int,
        engine: Engine = Depends(get_engine),
    ) -> dict[str, object]:
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
                engine=engine,
                library_root=Path(os.environ.get("LIBRARY_ROOT", "/music")),
            )
        except MetadataRescueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return dict(local_track)

    return router
