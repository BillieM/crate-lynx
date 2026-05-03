"""add playlist sync failure columns

Revision ID: 7a90b6dfc1e2
Revises: a3f82c91d450
Create Date: 2026-05-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "7a90b6dfc1e2"
down_revision = "a3f82c91d450"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "streaming_playlists",
        sa.Column("last_sync_error", sa.String(), nullable=True),
    )
    op.add_column(
        "streaming_playlists",
        sa.Column("last_sync_error_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("streaming_playlists", "last_sync_error_at")
    op.drop_column("streaming_playlists", "last_sync_error")
