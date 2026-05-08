"""remove streaming fingerprints and acoustic suggestions

Revision ID: 9b7e3c2d1a4f
Revises: f8a3d2c1b0e4
Create Date: 2026-05-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "9b7e3c2d1a4f"
down_revision = "f8a3d2c1b0e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM suggested_links "
        "WHERE match_method = 'acoustic' AND status = 'pending'"
    )
    op.execute(
        "UPDATE suggested_links SET match_method = 'manual' "
        "WHERE match_method = 'acoustic' AND status IN ('approved', 'rejected')"
    )
    op.drop_column("streaming_tracks", "fingerprinted_at")
    op.drop_column("streaming_tracks", "fingerprint_duration_seconds")
    op.drop_column("streaming_tracks", "fingerprint")


def downgrade() -> None:
    raise NotImplementedError(
        "downgrade cannot restore removed fingerprints or acoustic match methods; "
        "restore from backup"
    )
