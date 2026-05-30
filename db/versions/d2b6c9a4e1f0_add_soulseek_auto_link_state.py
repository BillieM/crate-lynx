"""add soulseek auto link state

Revision ID: d2b6c9a4e1f0
Revises: 9e8f7a6b5c4d
Create Date: 2026-05-28 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d2b6c9a4e1f0"
down_revision = "9e8f7a6b5c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.add_column(sa.Column("final_link_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("link_error_detail", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_soulseek_acquisitions_final_link_id_final_links",
            "final_links",
            ["final_link_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.drop_constraint(
            "fk_soulseek_acquisitions_final_link_id_final_links",
            type_="foreignkey",
        )
        batch_op.drop_column("linked_at")
        batch_op.drop_column("link_error_detail")
        batch_op.drop_column("final_link_id")
