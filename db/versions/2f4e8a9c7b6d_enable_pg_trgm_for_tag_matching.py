"""enable pg_trgm for tag matching

Revision ID: 2f4e8a9c7b6d
Revises: a7b9c8d6e5f4
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "2f4e8a9c7b6d"
down_revision = "a7b9c8d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_index(
        "ix_streaming_tracks_title_trgm",
        "streaming_tracks",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_streaming_tracks_title_trgm", table_name="streaming_tracks")
