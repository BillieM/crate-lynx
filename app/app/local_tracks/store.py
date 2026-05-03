from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    insert,
)


metadata = MetaData()

local_tracks_table = Table(
    "local_tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("file_path", String, nullable=False),
    Column("library_root_rel_path", String, nullable=False),
    Column("fingerprint", String, nullable=True),
    Column("beets_id", Integer, nullable=True),
    Column(
        "created_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
    Column(
        "updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False
    ),
)


@dataclass(slots=True)
class PersistedLocalTrack:
    id: int
    file_path: str


class LocalTrackStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def persist(
        self,
        *,
        library_root: Path | str,
        library_path: Path | str,
        fingerprint: str | None,
        beets_id: int | None,
    ) -> PersistedLocalTrack:
        relative_path = _relative_library_path(library_root, library_path)

        with self._engine.begin() as connection:
            result = connection.execute(
                insert(local_tracks_table).values(
                    file_path=relative_path,
                    library_root_rel_path=relative_path,
                    fingerprint=fingerprint,
                    beets_id=beets_id,
                )
            )

        inserted_id = result.inserted_primary_key[0]
        if not isinstance(inserted_id, int):
            raise ValueError("Failed to persist local track")

        return PersistedLocalTrack(id=inserted_id, file_path=relative_path)


def _relative_library_path(library_root: Path | str, library_path: Path | str) -> str:
    library_root_path = Path(library_root).resolve()
    track_path = Path(library_path).resolve()
    return str(track_path.relative_to(library_root_path))
