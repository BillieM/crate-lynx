"""add sonic feature attempt count

Revision ID: 0b7c9d2e4f6a
Revises: f1a2b3c4d5e6
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0b7c9d2e4f6a"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sonic_track_features",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_index(
        op.f("ix_sonic_track_features_status_updated_at"),
        "sonic_track_features",
        ["status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sonic_track_features_status_updated_at"),
        table_name="sonic_track_features",
    )
    op.drop_column("sonic_track_features", "attempt_count")
