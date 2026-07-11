"""enforce link integrity and canonical ISRC

Revision ID: 1a2b3c4d5e7f
Revises: 7f4a9c2d8b31
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e7f"
down_revision = "7f4a9c2d8b31"
branch_labels = None
depends_on = None

_ISRC_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")


def upgrade() -> None:
    connection = op.get_bind()
    _preflight_final_links(connection)

    op.add_column(
        "streaming_tracks",
        sa.Column("canonical_isrc", sa.String(), nullable=True),
    )
    rows = connection.execute(
        sa.text("SELECT id, isrc FROM streaming_tracks WHERE isrc IS NOT NULL")
    ).mappings()
    for row in rows:
        canonical_isrc = _canonical_isrc(row["isrc"])
        if canonical_isrc is None:
            continue
        connection.execute(
            sa.text(
                "UPDATE streaming_tracks "
                "SET canonical_isrc = :canonical_isrc WHERE id = :track_id"
            ),
            {"canonical_isrc": canonical_isrc, "track_id": row["id"]},
        )
    op.create_index(
        "ix_streaming_tracks_canonical_isrc",
        "streaming_tracks",
        ["canonical_isrc"],
    )

    with op.batch_alter_table("final_links") as batch_op:
        batch_op.drop_index("ix_final_links_streaming_track_id")
        batch_op.create_unique_constraint(
            "uq_final_links_streaming_track_id",
            ["streaming_track_id"],
        )

    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.drop_constraint(
            "fk_soulseek_acquisitions_final_link_id_final_links",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_soulseek_acquisitions_final_link_id_final_links",
            "final_links",
            ["final_link_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("streaming_relationship_suggestions") as batch_op:
        batch_op.drop_constraint(
            "fk_streaming_relationship_suggestions_accepted_relationship",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_streaming_relationship_suggestions_accepted_relationship",
            "streaming_relationships",
            ["accepted_relationship_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("streaming_relationship_suggestions") as batch_op:
        batch_op.drop_constraint(
            "fk_streaming_relationship_suggestions_accepted_relationship",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_streaming_relationship_suggestions_accepted_relationship",
            "streaming_relationships",
            ["accepted_relationship_id"],
            ["id"],
        )

    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.drop_constraint(
            "fk_soulseek_acquisitions_final_link_id_final_links",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_soulseek_acquisitions_final_link_id_final_links",
            "final_links",
            ["final_link_id"],
            ["id"],
        )

    with op.batch_alter_table("final_links") as batch_op:
        batch_op.drop_constraint(
            "uq_final_links_streaming_track_id",
            type_="unique",
        )
        batch_op.create_index(
            "ix_final_links_streaming_track_id",
            ["streaming_track_id"],
        )

    op.drop_index(
        "ix_streaming_tracks_canonical_isrc",
        table_name="streaming_tracks",
    )
    op.drop_column("streaming_tracks", "canonical_isrc")


def _canonical_isrc(value: object) -> str | None:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    return normalized if _ISRC_PATTERN.fullmatch(normalized) else None


def _preflight_final_links(connection) -> None:
    link_rows = (
        connection.execute(
            sa.text(
                "SELECT id, local_track_id, streaming_track_id "
                "FROM final_links ORDER BY id"
            )
        )
        .mappings()
        .all()
    )
    if not link_rows:
        return

    parent: dict[int, int] = {}

    def find(track_id: int) -> int:
        parent.setdefault(track_id, track_id)
        while parent[track_id] != track_id:
            parent[track_id] = parent[parent[track_id]]
            track_id = parent[track_id]
        return track_id

    def union(first_track_id: int, second_track_id: int) -> None:
        first_root = find(first_track_id)
        second_root = find(second_track_id)
        if first_root != second_root:
            parent[max(first_root, second_root)] = min(first_root, second_root)

    relationship_rows = connection.execute(
        sa.text(
            "SELECT lower_track_id, higher_track_id "
            "FROM streaming_relationships WHERE relationship_type = 'equivalent'"
        )
    ).mappings()
    for row in relationship_rows:
        union(int(row["lower_track_id"]), int(row["higher_track_id"]))

    links_by_component: dict[int, list[object]] = {}
    for row in link_rows:
        component_id = find(int(row["streaming_track_id"]))
        links_by_component.setdefault(component_id, []).append(row)

    conflicts = [
        rows
        for rows in links_by_component.values()
        if len({int(row["local_track_id"]) for row in rows}) > 1
    ]
    if not conflicts:
        return

    report = "; ".join(
        ", ".join(
            f"final_link={row['id']} local={row['local_track_id']} "
            f"streaming={row['streaming_track_id']}"
            for row in rows
        )
        for rows in conflicts
    )
    raise RuntimeError(
        "Final-link integrity preflight found exact/equivalence conflicts. "
        "No rows were changed; resolve explicitly before retrying migration: "
        f"{report}"
    )
