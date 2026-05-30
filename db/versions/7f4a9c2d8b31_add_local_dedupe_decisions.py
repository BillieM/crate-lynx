"""add local dedupe decisions

Revision ID: 7f4a9c2d8b31
Revises: f3a9c2d7e1b4
Create Date: 2026-05-30 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "7f4a9c2d8b31"
down_revision = "f3a9c2d7e1b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_dedupe_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_key", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("keeper_local_track_id", sa.Integer(), nullable=True),
        sa.Column("track_ids_json", sa.JSON(), nullable=False),
        sa.Column("quarantined_track_ids_json", sa.JSON(), nullable=True),
        sa.Column("quarantine_paths_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_local_dedupe_decisions")),
        sa.UniqueConstraint(
            "group_key",
            name=op.f("uq_local_dedupe_decisions_group_key"),
        ),
    )
    op.create_index(
        "ix_local_dedupe_decisions_action",
        "local_dedupe_decisions",
        ["action"],
    )
    op.create_index(
        "ix_local_dedupe_decisions_source",
        "local_dedupe_decisions",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_local_dedupe_decisions_source",
        table_name="local_dedupe_decisions",
    )
    op.drop_index(
        "ix_local_dedupe_decisions_action",
        table_name="local_dedupe_decisions",
    )
    op.drop_table("local_dedupe_decisions")
