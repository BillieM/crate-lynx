"""add unique local track beets id

Revision ID: a7b9c8d6e5f4
Revises: c6d5f8a1b2c3
Create Date: 2026-05-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a7b9c8d6e5f4"
down_revision = "c6d5f8a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _deduplicate_local_tracks()

    with op.batch_alter_table("local_tracks") as batch_op:
        batch_op.create_unique_constraint(
            "uq_local_tracks_beets_id",
            ["beets_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("local_tracks") as batch_op:
        batch_op.drop_constraint(
            "uq_local_tracks_beets_id",
            type_="unique",
        )


def _deduplicate_local_tracks() -> None:
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text(
                """
                SELECT id, beets_id
                FROM local_tracks
                WHERE beets_id IS NOT NULL
                ORDER BY id
                """
            )
        )
        .mappings()
        .all()
    )
    final_link_ids = set(
        connection.execute(sa.text("SELECT local_track_id FROM final_links")).scalars()
    )

    ids_by_beets_id: dict[int, list[int]] = {}
    for row in rows:
        ids_by_beets_id.setdefault(row["beets_id"], []).append(row["id"])

    for local_track_ids in ids_by_beets_id.values():
        if len(local_track_ids) < 2:
            continue

        linked_ids = [
            track_id for track_id in local_track_ids if track_id in final_link_ids
        ]
        keep_id = min(linked_ids or local_track_ids)
        duplicate_ids = [
            track_id for track_id in local_track_ids if track_id != keep_id
        ]
        _merge_local_track_references(
            connection,
            keep_id=keep_id,
            duplicate_ids=duplicate_ids,
            final_link_ids=final_link_ids,
        )
        for duplicate_id in duplicate_ids:
            connection.execute(
                sa.text("DELETE FROM local_tracks WHERE id = :duplicate_id"),
                {"duplicate_id": duplicate_id},
            )


def _merge_local_track_references(
    connection,
    *,
    keep_id: int,
    duplicate_ids: list[int],
    final_link_ids: set[int],
) -> None:
    duplicate_final_link_ids = [
        track_id for track_id in duplicate_ids if track_id in final_link_ids
    ]
    if duplicate_final_link_ids:
        if keep_id in final_link_ids:
            promoted_id = None
        else:
            promoted_id = min(duplicate_final_link_ids)
            connection.execute(
                sa.text(
                    """
                    UPDATE final_links
                    SET local_track_id = :keep_id
                    WHERE local_track_id = :promoted_id
                    """
                ),
                {"keep_id": keep_id, "promoted_id": promoted_id},
            )
            final_link_ids.add(keep_id)

        for duplicate_id in duplicate_final_link_ids:
            if duplicate_id == promoted_id:
                continue
            connection.execute(
                sa.text("DELETE FROM final_links WHERE local_track_id = :duplicate_id"),
                {"duplicate_id": duplicate_id},
            )

    for duplicate_id in duplicate_ids:
        connection.execute(
            sa.text(
                """
                UPDATE suggested_links
                SET local_track_id = :keep_id
                WHERE local_track_id = :duplicate_id
                """
            ),
            {"keep_id": keep_id, "duplicate_id": duplicate_id},
        )
        connection.execute(
            sa.text(
                """
                UPDATE failed_ingestion_attempts
                SET local_track_id = :keep_id
                WHERE local_track_id = :duplicate_id
                """
            ),
            {"keep_id": keep_id, "duplicate_id": duplicate_id},
        )
