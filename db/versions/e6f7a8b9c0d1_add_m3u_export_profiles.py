"""add m3u export profiles

Revision ID: e6f7a8b9c0d1
Revises: 4d6e7f8a9b10
Create Date: 2026-05-23 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "4d6e7f8a9b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m3u_export_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("library_path", sa.String(), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_m3u_export_profiles")),
    )


def downgrade() -> None:
    op.drop_table("m3u_export_profiles")
