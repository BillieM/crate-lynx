"""add auth_state to streaming_accounts

Revision ID: a3f82c91d450
Revises: 0f693d613d73
Create Date: 2026-05-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a3f82c91d450"
down_revision = "0f693d613d73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "streaming_accounts",
        sa.Column(
            "auth_state", sa.String(), nullable=False, server_default="connected"
        ),
    )
    op.add_column(
        "streaming_accounts",
        sa.Column("auth_error", sa.String(), nullable=True),
    )
    op.add_column(
        "streaming_accounts",
        sa.Column("auth_error_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("streaming_accounts", "auth_error_at")
    op.drop_column("streaming_accounts", "auth_error")
    op.drop_column("streaming_accounts", "auth_state")
