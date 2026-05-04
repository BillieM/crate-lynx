from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.exc import IntegrityError

from app.settings.models import (
    DEFAULT_INGEST_FOLDER_PATHS,
    IngestFolderRecord,
    ingest_folders_table,
)


class InvalidIngestFolderPathError(ValueError):
    pass


class DuplicateIngestFolderPathError(ValueError):
    pass


class IngestFolderNotFoundError(ValueError):
    pass


class GeneralSettingsStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def list_ingest_folders(self) -> list[IngestFolderRecord]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(ingest_folders_table).order_by(
                        ingest_folders_table.c.id.asc()
                    )
                )
                .mappings()
                .all()
            )

        return [_record_from_row(row) for row in rows]

    def seed_default_ingest_folders(self) -> list[IngestFolderRecord]:
        with self._engine.begin() as connection:
            existing_id = connection.execute(
                select(ingest_folders_table.c.id).limit(1)
            ).scalar_one_or_none()
            if existing_id is None:
                connection.execute(
                    insert(ingest_folders_table),
                    [
                        {"path": _normalize_ingest_folder_path(path)}
                        for path in DEFAULT_INGEST_FOLDER_PATHS
                    ],
                )

        return self.list_ingest_folders()

    def create_ingest_folder(self, path: str) -> IngestFolderRecord:
        normalized_path = _normalize_ingest_folder_path(path)

        with self._engine.begin() as connection:
            existing_id = connection.execute(
                select(ingest_folders_table.c.id).where(
                    ingest_folders_table.c.path == normalized_path
                )
            ).scalar_one_or_none()
            if existing_id is not None:
                raise DuplicateIngestFolderPathError(normalized_path)

            try:
                result = connection.execute(
                    insert(ingest_folders_table).values(path=normalized_path)
                )
            except IntegrityError as exc:
                raise DuplicateIngestFolderPathError(normalized_path) from exc

            inserted_id = result.inserted_primary_key[0]
            if not isinstance(inserted_id, int):
                raise ValueError("Failed to persist ingest folder")

            row = (
                connection.execute(
                    select(ingest_folders_table).where(
                        ingest_folders_table.c.id == inserted_id
                    )
                )
                .mappings()
                .one()
            )

        return _record_from_row(row)

    def delete_ingest_folder(self, folder_id: int) -> IngestFolderRecord:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(ingest_folders_table).where(
                        ingest_folders_table.c.id == folder_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise IngestFolderNotFoundError(str(folder_id))

            result = connection.execute(
                delete(ingest_folders_table).where(
                    ingest_folders_table.c.id == folder_id
                )
            )
            if result.rowcount == 0:
                raise IngestFolderNotFoundError(str(folder_id))

        return _record_from_row(row)


def normalize_ingest_folder_path(path: str) -> str:
    return _normalize_ingest_folder_path(path)


def _normalize_ingest_folder_path(path: str) -> str:
    stripped_path = path.strip()
    if stripped_path == "":
        raise InvalidIngestFolderPathError("Ingest folder path cannot be empty")

    expanded_path = Path(stripped_path).expanduser()
    if not expanded_path.is_absolute():
        raise InvalidIngestFolderPathError(
            "Ingest folder path must be an absolute container path"
        )

    return str(expanded_path.resolve(strict=False))


def _record_from_row(row) -> IngestFolderRecord:
    return IngestFolderRecord(
        id=row["id"],
        path=row["path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
