"""add soulseek completion tracking

Revision ID: f3a9c2d7e1b4
Revises: d2b6c9a4e1f0
Create Date: 2026-05-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f3a9c2d7e1b4"
down_revision = "d2b6c9a4e1f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.add_column(
            sa.Column("completed_source_path", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("slskd_completed_event_id", sa.String(), nullable=True)
        )
        batch_op.create_index(
            "ix_soulseek_acquisitions_completed_source_path",
            ["completed_source_path"],
        )


def downgrade() -> None:
    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.drop_index("ix_soulseek_acquisitions_completed_source_path")
        batch_op.drop_column("slskd_completed_event_id")
        batch_op.drop_column("completed_source_path")
