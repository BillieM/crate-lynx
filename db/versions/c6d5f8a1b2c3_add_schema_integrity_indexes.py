"""add schema integrity constraints and indexes

Revision ID: c6d5f8a1b2c3
Revises: b9c2f4a8e7d1
Create Date: 2026-05-08 00:00:00.000000

Production note: for large populated Postgres databases, generate SQL with
``alembic upgrade --sql`` and convert these index builds to
``CREATE INDEX CONCURRENTLY`` before rolling out.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c6d5f8a1b2c3"
down_revision = "b9c2f4a8e7d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _deduplicate_streaming_playlists()
    _deduplicate_streaming_tracks()

    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.create_unique_constraint(
            "uq_streaming_playlists_account_id_provider_playlist_id",
            ["account_id", "provider_playlist_id"],
        )
    with op.batch_alter_table("streaming_tracks") as batch_op:
        batch_op.create_unique_constraint(
            "uq_streaming_tracks_provider_track_id",
            ["provider_track_id"],
        )

    op.create_index("ix_local_tracks_fingerprint", "local_tracks", ["fingerprint"])
    op.create_index("ix_local_tracks_beets_id", "local_tracks", ["beets_id"])
    op.create_index("ix_streaming_tracks_isrc", "streaming_tracks", ["isrc"])
    op.create_index(
        "ix_playlist_membership_playlist_id",
        "playlist_membership",
        ["playlist_id"],
    )
    op.create_index(
        "ix_playlist_membership_streaming_track_id",
        "playlist_membership",
        ["streaming_track_id"],
    )
    op.create_index(
        "ix_final_links_streaming_track_id",
        "final_links",
        ["streaming_track_id"],
    )
    op.create_index(
        "ix_suggested_links_local_track_id_status",
        "suggested_links",
        ["local_track_id", "status"],
    )
    op.create_index(
        "ix_suggested_links_streaming_track_id",
        "suggested_links",
        ["streaming_track_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_suggested_links_streaming_track_id", table_name="suggested_links")
    op.drop_index(
        "ix_suggested_links_local_track_id_status",
        table_name="suggested_links",
    )
    op.drop_index("ix_final_links_streaming_track_id", table_name="final_links")
    op.drop_index(
        "ix_playlist_membership_streaming_track_id",
        table_name="playlist_membership",
    )
    op.drop_index(
        "ix_playlist_membership_playlist_id",
        table_name="playlist_membership",
    )
    op.drop_index("ix_streaming_tracks_isrc", table_name="streaming_tracks")
    op.drop_index("ix_local_tracks_beets_id", table_name="local_tracks")
    op.drop_index("ix_local_tracks_fingerprint", table_name="local_tracks")

    with op.batch_alter_table("streaming_tracks") as batch_op:
        batch_op.drop_constraint(
            "uq_streaming_tracks_provider_track_id",
            type_="unique",
        )
    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.drop_constraint(
            "uq_streaming_playlists_account_id_provider_playlist_id",
            type_="unique",
        )


def _deduplicate_streaming_playlists() -> None:
    op.execute(
        sa.text(
            """
            UPDATE playlist_membership
            SET playlist_id = (
                SELECT MIN(kept.id)
                FROM streaming_playlists AS duplicate
                JOIN streaming_playlists AS kept
                  ON kept.account_id = duplicate.account_id
                 AND kept.provider_playlist_id = duplicate.provider_playlist_id
                WHERE duplicate.id = playlist_membership.playlist_id
            )
            WHERE playlist_id IN (
                SELECT duplicate.id
                FROM streaming_playlists AS duplicate
                WHERE duplicate.id <> (
                    SELECT MIN(kept.id)
                    FROM streaming_playlists AS kept
                    WHERE kept.account_id = duplicate.account_id
                      AND kept.provider_playlist_id = duplicate.provider_playlist_id
                )
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM streaming_playlists
            WHERE id NOT IN (
                SELECT kept.id
                FROM (
                    SELECT MIN(id) AS id
                    FROM streaming_playlists
                    GROUP BY account_id, provider_playlist_id
                ) AS kept
            )
            """
        )
    )


def _deduplicate_streaming_tracks() -> None:
    _deduplicate_streaming_track_references(
        table_name="playlist_membership",
        column_name="streaming_track_id",
    )
    _deduplicate_streaming_track_references(
        table_name="final_links",
        column_name="streaming_track_id",
    )
    _deduplicate_streaming_track_references(
        table_name="suggested_links",
        column_name="streaming_track_id",
    )
    op.execute(
        sa.text(
            """
            DELETE FROM streaming_tracks
            WHERE id NOT IN (
                SELECT kept.id
                FROM (
                    SELECT MIN(id) AS id
                    FROM streaming_tracks
                    GROUP BY provider_track_id
                ) AS kept
            )
            """
        )
    )


def _deduplicate_streaming_track_references(
    *,
    table_name: str,
    column_name: str,
) -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET {column_name} = (
                SELECT MIN(kept.id)
                FROM streaming_tracks AS duplicate
                JOIN streaming_tracks AS kept
                  ON kept.provider_track_id = duplicate.provider_track_id
                WHERE duplicate.id = {table_name}.{column_name}
            )
            WHERE {column_name} IN (
                SELECT duplicate.id
                FROM streaming_tracks AS duplicate
                WHERE duplicate.id <> (
                    SELECT MIN(kept.id)
                    FROM streaming_tracks AS kept
                    WHERE kept.provider_track_id = duplicate.provider_track_id
                )
            )
            """
        )
    )
