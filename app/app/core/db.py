"""Shared SQLAlchemy engine helpers.

Connection-context rule:
- Use ``Engine.connect()`` for read-only units of work.
- Use ``Engine.begin()`` for units that write or may write, including
  read-before-write flows.
- Helpers that receive an existing ``Connection`` inherit the caller's
  transaction choice instead of opening a second engine context.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request
import sqlalchemy
from sqlalchemy.engine import Engine


DATABASE_UNAVAILABLE_DETAIL = "DATABASE_URL must be configured for database access"


def require_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail=DATABASE_UNAVAILABLE_DETAIL)
    return database_url


def create_database_engine(database_url: str | None = None) -> Engine:
    return sqlalchemy.create_engine(database_url or require_database_url())


def get_engine(request: Request) -> Engine:
    engine = getattr(request.app.state, "database_engine", None)
    if isinstance(engine, Engine):
        return engine

    raise HTTPException(status_code=503, detail=DATABASE_UNAVAILABLE_DETAIL)
