"""add failed ingestion attempts

Revision ID: d4c1b2a9e8f0
Revises: bc4c3e1785d7
Create Date: 2026-05-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d4c1b2a9e8f0"
down_revision = "bc4c3e1785d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "failed_ingestion_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_path", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=True),
        sa.Column("failure_reason", sa.String(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("local_track_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["local_track_id"],
            ["local_tracks.id"],
            name=op.f("fk_failed_ingestion_attempts_local_track_id_local_tracks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_failed_ingestion_attempts")),
    )


def downgrade() -> None:
    op.drop_table("failed_ingestion_attempts")
