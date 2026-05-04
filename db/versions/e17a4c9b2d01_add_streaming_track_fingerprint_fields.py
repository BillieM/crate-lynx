"""add streaming track fingerprint fields

Revision ID: e17a4c9b2d01
Revises: d4c1b2a9e8f0
Create Date: 2026-05-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e17a4c9b2d01"
down_revision = "d4c1b2a9e8f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "streaming_tracks",
        sa.Column("fingerprint", sa.String(), nullable=True),
    )
    op.add_column(
        "streaming_tracks",
        sa.Column("fingerprint_duration_seconds", sa.Float(), nullable=True),
    )
    op.add_column(
        "streaming_tracks",
        sa.Column("fingerprinted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("streaming_tracks", "fingerprinted_at")
    op.drop_column("streaming_tracks", "fingerprint_duration_seconds")
    op.drop_column("streaming_tracks", "fingerprint")
