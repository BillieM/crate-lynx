"""add matching queue pagination indexes

Revision ID: 4d6e7f8a9b10
Revises: 3c9a1e8b7d4f
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "4d6e7f8a9b10"
down_revision = "3c9a1e8b7d4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_suggested_links_pending_queue",
        "suggested_links",
        ["status", "score", "id"],
    )
    op.create_index(
        "ix_streaming_relationship_suggestions_pending_queue",
        "streaming_relationship_suggestions",
        ["status", "score", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_streaming_relationship_suggestions_pending_queue",
        table_name="streaming_relationship_suggestions",
    )
    op.drop_index(
        "ix_suggested_links_pending_queue",
        table_name="suggested_links",
    )
