"""remove non-audio failed ingestion attempts

Revision ID: f8a3d2c1b0e4
Revises: 5c3ef4a8d2b1
Create Date: 2026-05-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "f8a3d2c1b0e4"
down_revision = "5c3ef4a8d2b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM failed_ingestion_attempts
        WHERE lower(filename) NOT LIKE '%.mp3'
          AND lower(filename) NOT LIKE '%.flac'
          AND lower(filename) NOT LIKE '%.wav'
          AND lower(filename) NOT LIKE '%.aiff'
          AND lower(filename) NOT LIKE '%.aif'
        """
    )


def downgrade() -> None:
    raise NotImplementedError(
        "downgrade is destructive; restore failed ingestion attempts from backup"
    )
