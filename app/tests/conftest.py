from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
import os
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url


BACKEND_SRC = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_SRC.parent

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def library_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    root = tmp_path / "library"
    monkeypatch.setenv("LIBRARY_ROOT", str(root))
    return root


@pytest.fixture(scope="session")
def postgres_database_url() -> Iterator[str]:
    configured_url = os.environ.get("TEST_DATABASE_URL")
    if configured_url:
        yield _normalize_postgres_url(configured_url)
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError as exc:
        pytest.skip(f"testcontainers is required for migrated database tests: {exc}")

    container = None
    try:
        container = _create_postgres_container(PostgresContainer)
        container.start()
    except Exception as exc:
        if container is not None:
            with suppress(Exception):
                container.stop()
        pytest.skip(f"Postgres test container unavailable: {exc}")

    try:
        yield _normalize_postgres_url(container.get_connection_url())
    finally:
        container.stop()


@pytest.fixture
def migrated_database(
    monkeypatch: pytest.MonkeyPatch,
    postgres_database_url: str,
) -> tuple[str, Engine]:
    database_name = f"crate_lynx_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(postgres_database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    database_url = str(make_url(postgres_database_url).set(database=database_name))
    engine: Engine | None = None
    try:
        monkeypatch.setenv("DATABASE_URL", database_url)

        alembic_config = Config(str(PROJECT_ROOT / "db" / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(PROJECT_ROOT / "db"))
        command.upgrade(alembic_config, "head")

        engine = create_engine(database_url)
        yield database_url, engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


@pytest.fixture
def test_data(migrated_database: tuple[str, Engine]):
    from tests.factories import TestDataFactory

    _, engine = migrated_database
    return TestDataFactory(engine)


def _normalize_postgres_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + database_url.removeprefix(
            "postgresql+psycopg2://"
        )
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def _create_postgres_container(postgres_container_type):
    try:
        return postgres_container_type("postgres:16-alpine", driver="psycopg")
    except TypeError:
        return postgres_container_type("postgres:16-alpine")
