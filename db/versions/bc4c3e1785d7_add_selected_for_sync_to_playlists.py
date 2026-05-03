"""add selected_for_sync to streaming_playlists

Revision ID: bc4c3e1785d7
Revises: 7a90b6dfc1e2
Create Date: 2026-05-03 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "bc4c3e1785d7"
down_revision = "7a90b6dfc1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "streaming_playlists",
        sa.Column(
            "selected_for_sync",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE streaming_playlists
            SET selected_for_sync = TRUE
            WHERE EXISTS (
                SELECT 1
                FROM playlist_membership
                WHERE playlist_membership.playlist_id = streaming_playlists.id
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("streaming_playlists", "selected_for_sync")
