from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.settings.models import metadata
from app.settings.router import create_router
from app.settings.schemas import CreateIngestFolderRequest
from app.settings.store import GeneralSettingsStore


def test_get_general_settings_lists_ingest_folders(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    store = GeneralSettingsStore(database_url)
    store.create_ingest_folder("/ingestion")
    store.create_ingest_folder("/soulseek")

    route = _route("GET", "/settings/general", database_url)
    response = route.endpoint()

    assert response.model_dump() == {
        "ingest_folders": [
            {"id": 1, "path": "/ingestion"},
            {"id": 2, "path": "/soulseek"},
        ]
    }


def test_create_ingest_folder_returns_created_folder(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    route = _route("POST", "/settings/ingest-folders", database_url)
    response = route.endpoint(CreateIngestFolderRequest(path="/music-in/../incoming"))

    assert response.model_dump() == {"id": 1, "path": "/incoming"}


def test_create_ingest_folder_calls_created_callback(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    created_paths: list[str] = []
    router = create_router(
        require_database_url=lambda: database_url,
        on_ingest_folder_created=created_paths.append,
    )
    route = _route_from_router("POST", "/settings/ingest-folders", router)

    response = route.endpoint(CreateIngestFolderRequest(path="/music-in/../incoming"))

    assert response.model_dump() == {"id": 1, "path": "/incoming"}
    assert created_paths == ["/incoming"]


def test_create_ingest_folder_rejects_duplicate_path(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    GeneralSettingsStore(database_url).create_ingest_folder("/incoming")

    route = _route("POST", "/settings/ingest-folders", database_url)
    try:
        route.endpoint(CreateIngestFolderRequest(path="/incoming/."))
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Expected duplicate path to be rejected")


def test_create_ingest_folder_rejects_relative_path(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    route = _route("POST", "/settings/ingest-folders", database_url)
    try:
        route.endpoint(CreateIngestFolderRequest(path="incoming"))
    except StarletteHTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("Expected relative path to be rejected")


def test_delete_ingest_folder_removes_folder(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    folder = GeneralSettingsStore(database_url).create_ingest_folder("/incoming")

    route = _route("DELETE", "/settings/ingest-folders/{folder_id}", database_url)
    response = route.endpoint(folder.id)

    assert response.status_code == 204
    assert GeneralSettingsStore(database_url).list_ingest_folders() == []


def test_delete_ingest_folder_calls_deleted_callback(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)
    folder = GeneralSettingsStore(database_url).create_ingest_folder("/incoming")
    deleted_paths: list[str] = []
    router = create_router(
        require_database_url=lambda: database_url,
        on_ingest_folder_deleted=deleted_paths.append,
    )
    route = _route_from_router("DELETE", "/settings/ingest-folders/{folder_id}", router)

    response = route.endpoint(folder.id)

    assert response.status_code == 204
    assert deleted_paths == ["/incoming"]
    assert GeneralSettingsStore(database_url).list_ingest_folders() == []


def test_delete_ingest_folder_returns_404_for_missing_folder(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'settings.db'}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    route = _route("DELETE", "/settings/ingest-folders/{folder_id}", database_url)
    try:
        route.endpoint(999)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected missing folder to return 404")


def test_settings_routes_return_503_without_database_url() -> None:
    router = create_router(
        require_database_url=lambda: (_ for _ in ()).throw(
            StarletteHTTPException(status_code=503, detail="DATABASE_URL required")
        )
    )
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/settings/general"
        and "GET" in getattr(route, "methods", set())
    )

    try:
        route.endpoint()
    except StarletteHTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("Expected missing DATABASE_URL to return 503")


def _route(method: str, path: str, database_url: str):
    router = create_router(require_database_url=lambda: database_url)
    return _route_from_router(method, path, router)


def _route_from_router(method: str, path: str, router):
    return next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )
