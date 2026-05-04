"""add ingest folders

Revision ID: 5c3ef4a8d2b1
Revises: e17a4c9b2d01
Create Date: 2026-05-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "5c3ef4a8d2b1"
down_revision = "e17a4c9b2d01"
branch_labels = None
depends_on = None


ingest_folders_table = sa.table(
    "ingest_folders",
    sa.column("path", sa.String()),
)


def upgrade() -> None:
    op.create_table(
        "ingest_folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingest_folders")),
        sa.UniqueConstraint("path", name=op.f("uq_ingest_folders_path")),
    )
    op.bulk_insert(
        ingest_folders_table,
        [
            {"path": "/ingestion"},
            {"path": "/soulseek"},
        ],
    )


def downgrade() -> None:
    op.drop_table("ingest_folders")
