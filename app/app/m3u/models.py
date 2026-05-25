from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, func


metadata = MetaData()

m3u_export_profiles_table = Table(
    "m3u_export_profiles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("library_path", String, nullable=False),
    Column("is_default", Boolean, nullable=False, server_default="false"),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
)


@dataclass(frozen=True, slots=True)
class M3uExportProfileRecord:
    id: int
    name: str
    library_path: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
