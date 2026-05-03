from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, func


metadata = MetaData()

final_links_table = Table(
    "final_links",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("local_track_id", Integer, nullable=False, unique=True),
    Column("streaming_track_id", Integer, nullable=False),
    Column(
        "approved_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)
