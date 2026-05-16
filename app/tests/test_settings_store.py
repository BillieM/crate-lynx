from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select

from app.settings.models import ingest_folders_table, metadata
from app.settings.store import (
    DuplicateIngestFolderPathError,
    GeneralSettingsStore,
    IngestFolderNotFoundError,
    InvalidIngestFolderPathError,
    normalize_ingest_folder_path,
)


DEFAULT_INGEST_PATHS = ["/nas/cratelynx/music-in", "/nas/soulseek/downloads"]


def test_general_settings_store_seeds_default_ingest_folders_when_empty(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    folders = GeneralSettingsStore(database_url).seed_default_ingest_folders()

    assert [folder.path for folder in folders] == DEFAULT_INGEST_PATHS
    assert all(folder.created_at is not None for folder in folders)
    assert all(folder.updated_at is not None for folder in folders)

    with engine.connect() as connection:
        stored_paths = [
            row["path"]
            for row in connection.execute(
                select(ingest_folders_table).order_by(ingest_folders_table.c.id.asc())
            ).mappings()
        ]

    assert stored_paths == DEFAULT_INGEST_PATHS


def test_general_settings_store_does_not_seed_defaults_when_table_has_rows(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    store = GeneralSettingsStore(database_url)
    store.create_ingest_folder("/custom")

    folders = store.seed_default_ingest_folders()

    assert [folder.path for folder in folders] == ["/custom"]


def test_general_settings_store_creates_normalized_absolute_ingest_folder(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    folder = GeneralSettingsStore(database_url).create_ingest_folder(
        "/music/../incoming"
    )

    assert folder.id == 1
    assert folder.path == "/incoming"
    assert folder.created_at is not None
    assert folder.updated_at is not None


def test_general_settings_store_rejects_invalid_ingest_folder_paths(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    store = GeneralSettingsStore(database_url)

    for invalid_path in ("", "   ", "relative/path"):
        try:
            store.create_ingest_folder(invalid_path)
        except InvalidIngestFolderPathError:
            pass
        else:
            raise AssertionError(f"accepted invalid path: {invalid_path!r}")


def test_general_settings_store_rejects_duplicate_normalized_ingest_folder(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    store = GeneralSettingsStore(database_url)
    store.create_ingest_folder("/downloads")

    try:
        store.create_ingest_folder("/downloads/../downloads")
    except DuplicateIngestFolderPathError:
        pass
    else:
        raise AssertionError("accepted duplicate ingest folder path")


def test_general_settings_store_deletes_ingest_folder(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    store = GeneralSettingsStore(database_url)
    folder = store.create_ingest_folder("/incoming")

    store.delete_ingest_folder(folder.id)

    assert store.list_ingest_folders() == []
    try:
        store.delete_ingest_folder(folder.id)
    except IngestFolderNotFoundError:
        pass
    else:
        raise AssertionError("deleted a missing ingest folder")


def test_normalize_ingest_folder_path_expands_users_and_resolves() -> None:
    path = "~/incoming/../downloads"

    assert normalize_ingest_folder_path(path) == str(
        Path(path).expanduser().resolve(strict=False)
    )
