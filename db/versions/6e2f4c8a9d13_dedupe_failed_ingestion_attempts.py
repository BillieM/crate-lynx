"""dedupe failed ingestion attempts

Revision ID: 6e2f4c8a9d13
Revises: 1f2a3b4c5d6e
Create Date: 2026-05-19 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "6e2f4c8a9d13"
down_revision = "1f2a3b4c5d6e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("failed_ingestion_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_size", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("source_mtime_ns", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.execute(
        sa.text(
            """
            UPDATE failed_ingestion_attempts
            SET first_failed_at = failed_at,
                attempt_count = 1
            """
        )
    )
    _deduplicate_failed_ingestion_attempts()

    with op.batch_alter_table("failed_ingestion_attempts") as batch_op:
        batch_op.alter_column(
            "first_failed_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )
        batch_op.alter_column(
            "attempt_count",
            existing_type=sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        )
        batch_op.create_unique_constraint(
            "uq_failed_ingestion_attempts_source_path",
            ["source_path"],
        )


def downgrade() -> None:
    with op.batch_alter_table("failed_ingestion_attempts") as batch_op:
        batch_op.drop_constraint(
            "uq_failed_ingestion_attempts_source_path",
            type_="unique",
        )
        batch_op.drop_column("ignored_at")
        batch_op.drop_column("source_mtime_ns")
        batch_op.drop_column("source_size")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("first_failed_at")


def _deduplicate_failed_ingestion_attempts() -> None:
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT id, source_path, filename, fingerprint, failure_reason,
                       failed_at, first_failed_at, attempt_count, local_track_id
                FROM failed_ingestion_attempts
                ORDER BY source_path ASC, failed_at ASC, id ASC
                """
            )
        )
        .mappings()
        .all()
    )

    rows_by_source_path: dict[str, list[object]] = {}
    for row in rows:
        rows_by_source_path.setdefault(row["source_path"], []).append(row)

    for source_rows in rows_by_source_path.values():
        if not source_rows:
            continue

        keep_row = source_rows[-1]
        duplicate_ids = [row["id"] for row in source_rows[:-1]]
        attempt_count = sum(row["attempt_count"] or 1 for row in source_rows)
        first_failed_at = (
            source_rows[0]["first_failed_at"] or source_rows[0]["failed_at"]
        )

        connection.execute(
            sa.text(
                """
                UPDATE failed_ingestion_attempts
                SET filename = :filename,
                    fingerprint = :fingerprint,
                    failure_reason = :failure_reason,
                    failed_at = :failed_at,
                    first_failed_at = :first_failed_at,
                    attempt_count = :attempt_count,
                    local_track_id = :local_track_id
                WHERE id = :id
                """
            ),
            {
                "id": keep_row["id"],
                "filename": keep_row["filename"],
                "fingerprint": keep_row["fingerprint"],
                "failure_reason": keep_row["failure_reason"],
                "failed_at": keep_row["failed_at"],
                "first_failed_at": first_failed_at,
                "attempt_count": attempt_count,
                "local_track_id": keep_row["local_track_id"],
            },
        )

        for duplicate_id in duplicate_ids:
            connection.execute(
                sa.text("DELETE FROM failed_ingestion_attempts WHERE id = :id"),
                {"id": duplicate_id},
            )
