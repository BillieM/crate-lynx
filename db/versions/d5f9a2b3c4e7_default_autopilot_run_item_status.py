"""default autopilot run item status

Revision ID: d5f9a2b3c4e7
Revises: c4e8f1a2b3d6
Create Date: 2026-07-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5f9a2b3c4e7"
down_revision: str | None = "c4e8f1a2b3d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("autopilot_run_items") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(),
            server_default=sa.text("'planned'"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("autopilot_run_items") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(),
            server_default=None,
            existing_nullable=False,
        )
