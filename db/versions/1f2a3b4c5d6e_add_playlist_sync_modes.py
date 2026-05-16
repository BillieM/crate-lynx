"""add playlist sync modes

Revision ID: 1f2a3b4c5d6e
Revises: 8d1f6a3c4b2e
Create Date: 2026-05-16 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "1f2a3b4c5d6e"
down_revision = "8d1f6a3c4b2e"
branch_labels = None
depends_on = None

SYNC_MODE_OFF = "off"
SYNC_MODE_FULL = "full"
SYNC_MODE_CHECK = "sync_mode IN ('off', 'match_only', 'full')"


def upgrade() -> None:
    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sync_mode",
                sa.String(),
                nullable=False,
                server_default=sa.text(f"'{SYNC_MODE_OFF}'"),
            )
        )
        batch_op.add_column(
            sa.Column("provider_track_count", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("metadata_synced_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("tracks_synced_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.execute(
        sa.text(
            """
            UPDATE streaming_playlists
            SET sync_mode = CASE
                    WHEN selected_for_sync THEN :sync_mode_full
                    ELSE :sync_mode_off
                END,
                metadata_synced_at = synced_at
            """
        ).bindparams(
            sync_mode_full=SYNC_MODE_FULL,
            sync_mode_off=SYNC_MODE_OFF,
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE streaming_playlists
            SET tracks_synced_at = synced_at
            WHERE synced_at IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM playlist_membership
                  WHERE playlist_membership.playlist_id = streaming_playlists.id
              )
            """
        )
    )

    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.create_check_constraint(
            "ck_streaming_playlists_sync_mode",
            SYNC_MODE_CHECK,
        )
        batch_op.drop_column("selected_for_sync")
        batch_op.drop_column("synced_at")


def downgrade() -> None:
    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.add_column(
            sa.Column(
                "selected_for_sync",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.execute(
        sa.text(
            """
            UPDATE streaming_playlists
            SET selected_for_sync = CASE
                    WHEN sync_mode = :sync_mode_full THEN TRUE
                    ELSE FALSE
                END,
                synced_at = COALESCE(tracks_synced_at, metadata_synced_at)
            """
        ).bindparams(sync_mode_full=SYNC_MODE_FULL)
    )

    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.drop_constraint(
            "ck_streaming_playlists_sync_mode",
            type_="check",
        )
        batch_op.drop_column("tracks_synced_at")
        batch_op.drop_column("metadata_synced_at")
        batch_op.drop_column("provider_track_count")
        batch_op.drop_column("sync_mode")
