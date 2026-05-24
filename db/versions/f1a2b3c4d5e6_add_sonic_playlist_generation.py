"""add sonic playlist generation

Revision ID: f1a2b3c4d5e6
Revises: e6f7a8b9c0d1
Create Date: 2026-05-24 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sonic_track_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("local_track_id", sa.Integer(), nullable=False),
        sa.Column("analyzer_key", sa.String(), nullable=False),
        sa.Column("analyzer_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("descriptor_json", sa.JSON(), nullable=True),
        sa.Column("vector_json", sa.JSON(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["local_track_id"],
            ["local_tracks.id"],
            name=op.f("fk_sonic_track_features_local_track_id_local_tracks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sonic_track_features")),
        sa.UniqueConstraint(
            "local_track_id",
            name=op.f("uq_sonic_track_features_local_track_id"),
        ),
    )
    op.create_index(
        op.f("ix_sonic_track_features_analyzer_key"),
        "sonic_track_features",
        ["analyzer_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sonic_track_features_status"),
        "sonic_track_features",
        ["status"],
        unique=False,
    )

    op.create_table(
        "playlist_generation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_filter_json", sa.JSON(), nullable=False),
        sa.Column("generation_config_json", sa.JSON(), nullable=False),
        sa.Column("playlist_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("track_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playlist_generation_runs")),
    )
    op.create_index(
        op.f("ix_playlist_generation_runs_created_at"),
        "playlist_generation_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playlist_generation_runs_status"),
        "playlist_generation_runs",
        ["status"],
        unique=False,
    )

    op.create_table(
        "generated_playlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("parent_playlist_id", sa.Integer(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("track_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_playlist_id"],
            ["generated_playlists.id"],
            name=op.f("fk_generated_playlists_parent_playlist_id_generated_playlists"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["playlist_generation_runs.id"],
            name=op.f("fk_generated_playlists_run_id_playlist_generation_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_playlists")),
    )
    op.create_index(
        op.f("ix_generated_playlists_parent_playlist_id"),
        "generated_playlists",
        ["parent_playlist_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generated_playlists_run_id"),
        "generated_playlists",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "generated_playlist_tracks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_playlist_id", sa.Integer(), nullable=False),
        sa.Column("local_track_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["generated_playlist_id"],
            ["generated_playlists.id"],
            name=op.f(
                "fk_generated_playlist_tracks_generated_playlist_id_generated_playlists"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["local_track_id"],
            ["local_tracks.id"],
            name=op.f("fk_generated_playlist_tracks_local_track_id_local_tracks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_playlist_tracks")),
        sa.UniqueConstraint(
            "generated_playlist_id",
            "local_track_id",
            name=op.f("uq_generated_playlist_tracks_playlist_track"),
        ),
    )
    op.create_index(
        op.f("ix_generated_playlist_tracks_local_track_id"),
        "generated_playlist_tracks",
        ["local_track_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_generated_playlist_tracks_playlist_position"),
        "generated_playlist_tracks",
        ["generated_playlist_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_generated_playlist_tracks_playlist_position"),
        table_name="generated_playlist_tracks",
    )
    op.drop_index(
        op.f("ix_generated_playlist_tracks_local_track_id"),
        table_name="generated_playlist_tracks",
    )
    op.drop_table("generated_playlist_tracks")
    op.drop_index(
        op.f("ix_generated_playlists_run_id"),
        table_name="generated_playlists",
    )
    op.drop_index(
        op.f("ix_generated_playlists_parent_playlist_id"),
        table_name="generated_playlists",
    )
    op.drop_table("generated_playlists")
    op.drop_index(
        op.f("ix_playlist_generation_runs_status"),
        table_name="playlist_generation_runs",
    )
    op.drop_index(
        op.f("ix_playlist_generation_runs_created_at"),
        table_name="playlist_generation_runs",
    )
    op.drop_table("playlist_generation_runs")
    op.drop_index(
        op.f("ix_sonic_track_features_status"),
        table_name="sonic_track_features",
    )
    op.drop_index(
        op.f("ix_sonic_track_features_analyzer_key"),
        table_name="sonic_track_features",
    )
    op.drop_table("sonic_track_features")
