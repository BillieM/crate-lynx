"""move default ingest folders to nas mount

Revision ID: 8d1f6a3c4b2e
Revises: 2f4e8a9c7b6d
Create Date: 2026-05-16 17:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


revision = "8d1f6a3c4b2e"
down_revision = "2f4e8a9c7b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    _replace_path(connection, "/ingestion", "/nas/cratelynx/music-in")
    _replace_path(connection, "/soulseek", "/nas/soulseek/downloads")


def downgrade() -> None:
    connection = op.get_bind()
    _replace_path(connection, "/nas/cratelynx/music-in", "/ingestion")
    _replace_path(connection, "/nas/soulseek/downloads", "/soulseek")


def _replace_path(connection: Connection, old_path: str, new_path: str) -> None:
    new_path_exists = connection.execute(
        sa.text("SELECT 1 FROM ingest_folders WHERE path = :path LIMIT 1"),
        {"path": new_path},
    ).first()

    if new_path_exists is None:
        connection.execute(
            sa.text(
                """
                UPDATE ingest_folders
                SET path = :new_path, updated_at = CURRENT_TIMESTAMP
                WHERE path = :old_path
                """
            ),
            {"old_path": old_path, "new_path": new_path},
        )
    else:
        connection.execute(
            sa.text("DELETE FROM ingest_folders WHERE path = :old_path"),
            {"old_path": old_path},
        )
