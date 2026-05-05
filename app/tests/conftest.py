import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine


BACKEND_SRC = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_SRC.parent

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def migrated_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[str, Engine]:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    alembic_config = Config(str(PROJECT_ROOT / "db" / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    try:
        yield database_url, engine
    finally:
        engine.dispose()


@pytest.fixture
def test_data(migrated_database: tuple[str, Engine]):
    from tests.factories import TestDataFactory

    _, engine = migrated_database
    return TestDataFactory(engine)
