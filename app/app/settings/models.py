from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, func


DEFAULT_INGEST_FOLDER_PATHS = ("/ingestion", "/soulseek")

metadata = MetaData()

ingest_folders_table = Table(
    "ingest_folders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("path", String, nullable=False, unique=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
)


@dataclass(frozen=True, slots=True)
class IngestFolderRecord:
    id: int
    path: str
    created_at: datetime
    updated_at: datetime
