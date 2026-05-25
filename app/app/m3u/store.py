from __future__ import annotations

import ntpath
import posixpath
from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine
from app.m3u.models import M3uExportProfileRecord, m3u_export_profiles_table


class InvalidM3uExportProfileNameError(ValueError):
    pass


class InvalidM3uExportLibraryPathError(ValueError):
    pass


class M3uExportProfileNotFoundError(ValueError):
    pass


class M3uExportProfileStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def list_profiles(self) -> list[M3uExportProfileRecord]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(m3u_export_profiles_table).order_by(
                        m3u_export_profiles_table.c.is_default.desc(),
                        m3u_export_profiles_table.c.id.asc(),
                    )
                )
                .mappings()
                .all()
            )

        return [_profile_from_row(row) for row in rows]

    def get_profile(self, profile_id: int) -> M3uExportProfileRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(m3u_export_profiles_table).where(
                        m3u_export_profiles_table.c.id == profile_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        return _profile_from_row(row) if row is not None else None

    def create_profile(
        self,
        *,
        library_path: str,
        name: str,
        is_default: bool = False,
    ) -> M3uExportProfileRecord:
        normalized_name = _normalize_profile_name(name)
        normalized_library_path = normalize_m3u_export_library_path(library_path)

        with self._engine.begin() as connection:
            has_profiles = (
                connection.execute(
                    select(func.count(m3u_export_profiles_table.c.id))
                ).scalar_one()
                > 0
            )
            should_be_default = is_default or not has_profiles
            if should_be_default:
                _clear_default_profile(connection)

            result = connection.execute(
                insert(m3u_export_profiles_table).values(
                    name=normalized_name,
                    library_path=normalized_library_path,
                    is_default=should_be_default,
                )
            )
            profile_id = result.inserted_primary_key[0]
            row = (
                connection.execute(
                    select(m3u_export_profiles_table).where(
                        m3u_export_profiles_table.c.id == profile_id
                    )
                )
                .mappings()
                .one()
            )

        return _profile_from_row(row)

    def create_default_profile_if_none(
        self,
        *,
        library_path: str,
        name: str = "Default export",
    ) -> M3uExportProfileRecord | None:
        normalized_library_path = normalize_m3u_export_library_path(library_path)
        with self._engine.connect() as connection:
            existing_count = connection.execute(
                select(func.count(m3u_export_profiles_table.c.id))
            ).scalar_one()

        if existing_count > 0:
            return None

        return self.create_profile(
            library_path=normalized_library_path,
            name=name,
            is_default=True,
        )

    def get_profile_by_library_path(
        self,
        library_path: str,
    ) -> M3uExportProfileRecord | None:
        normalized_library_path = normalize_m3u_export_library_path(library_path)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(m3u_export_profiles_table).where(
                        m3u_export_profiles_table.c.library_path
                        == normalized_library_path
                    )
                )
                .mappings()
                .first()
            )

        return _profile_from_row(row) if row is not None else None

    def update_profile(
        self,
        *,
        profile_id: int,
        is_default: bool | None = None,
        library_path: str | None = None,
        name: str | None = None,
    ) -> M3uExportProfileRecord:
        values: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if name is not None:
            values["name"] = _normalize_profile_name(name)
        if library_path is not None:
            values["library_path"] = normalize_m3u_export_library_path(library_path)
        if is_default is not None:
            values["is_default"] = is_default

        with self._engine.begin() as connection:
            existing_id = connection.execute(
                select(m3u_export_profiles_table.c.id).where(
                    m3u_export_profiles_table.c.id == profile_id
                )
            ).scalar_one_or_none()
            if existing_id is None:
                raise M3uExportProfileNotFoundError(str(profile_id))

            if is_default is True:
                _clear_default_profile(connection)

            connection.execute(
                update(m3u_export_profiles_table)
                .where(m3u_export_profiles_table.c.id == profile_id)
                .values(**values)
            )
            row = (
                connection.execute(
                    select(m3u_export_profiles_table).where(
                        m3u_export_profiles_table.c.id == profile_id
                    )
                )
                .mappings()
                .one()
            )

        return _profile_from_row(row)

    def delete_profile(self, profile_id: int) -> M3uExportProfileRecord:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(m3u_export_profiles_table).where(
                        m3u_export_profiles_table.c.id == profile_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise M3uExportProfileNotFoundError(str(profile_id))

            deleted_profile = _profile_from_row(row)
            result = connection.execute(
                delete(m3u_export_profiles_table).where(
                    m3u_export_profiles_table.c.id == profile_id
                )
            )
            if result.rowcount == 0:
                raise M3uExportProfileNotFoundError(str(profile_id))

            if deleted_profile.is_default:
                next_id = connection.execute(
                    select(m3u_export_profiles_table.c.id)
                    .order_by(m3u_export_profiles_table.c.id.asc())
                    .limit(1)
                ).scalar_one_or_none()
                if next_id is not None:
                    connection.execute(
                        update(m3u_export_profiles_table)
                        .where(m3u_export_profiles_table.c.id == next_id)
                        .values(is_default=True, updated_at=datetime.now(UTC))
                    )

        return deleted_profile


def normalize_m3u_export_library_path(path: str) -> str:
    stripped_path = path.strip()
    if stripped_path == "":
        raise InvalidM3uExportLibraryPathError("Music library path cannot be empty")

    if _is_windows_absolute_path(stripped_path):
        return ntpath.normpath(stripped_path)

    if not stripped_path.startswith("/"):
        raise InvalidM3uExportLibraryPathError("Music library path must be absolute")

    return posixpath.normpath(stripped_path)


def _normalize_profile_name(name: str) -> str:
    normalized_name = name.strip()
    if normalized_name == "":
        raise InvalidM3uExportProfileNameError("Export profile name cannot be empty")
    return normalized_name


def _is_windows_absolute_path(path: str) -> bool:
    drive, tail = ntpath.splitdrive(path)
    return bool(drive and tail.startswith(("\\", "/"))) or path.startswith("\\\\")


def _clear_default_profile(connection) -> None:
    connection.execute(
        update(m3u_export_profiles_table)
        .where(m3u_export_profiles_table.c.is_default.is_(True))
        .values(is_default=False, updated_at=datetime.now(UTC))
    )


def _profile_from_row(row) -> M3uExportProfileRecord:
    return M3uExportProfileRecord(
        id=row["id"],
        name=row["name"],
        library_path=row["library_path"],
        is_default=bool(row["is_default"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
