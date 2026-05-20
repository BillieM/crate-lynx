"""add streaming relationship tables

Revision ID: 3c9a1e8b7d4f
Revises: 6e2f4c8a9d13
Create Date: 2026-05-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "3c9a1e8b7d4f"
down_revision = "6e2f4c8a9d13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "streaming_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lower_track_id", sa.Integer(), nullable=False),
        sa.Column("higher_track_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lower_track_id < higher_track_id",
            name=op.f("ck_streaming_relationships_normalized_pair"),
        ),
        sa.CheckConstraint(
            "relationship_type IN ('equivalent', 'related')",
            name=op.f("ck_streaming_relationships_relationship_type"),
        ),
        sa.ForeignKeyConstraint(
            ["lower_track_id"],
            ["streaming_tracks.id"],
            name=op.f("fk_streaming_relationships_lower_track"),
        ),
        sa.ForeignKeyConstraint(
            ["higher_track_id"],
            ["streaming_tracks.id"],
            name=op.f("fk_streaming_relationships_higher_track"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_streaming_relationships")),
        sa.UniqueConstraint(
            "lower_track_id",
            "higher_track_id",
            name=op.f("uq_streaming_relationships_pair"),
        ),
    )
    op.create_index(
        "ix_streaming_relationships_lower_track_id",
        "streaming_relationships",
        ["lower_track_id"],
    )
    op.create_index(
        "ix_streaming_relationships_higher_track_id",
        "streaming_relationships",
        ["higher_track_id"],
    )

    op.create_table(
        "streaming_relationship_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lower_track_id", sa.Integer(), nullable=False),
        sa.Column("higher_track_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column("match_method", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("accepted_relationship_id", sa.Integer(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lower_track_id < higher_track_id",
            name=op.f("ck_streaming_relationship_suggestions_normalized_pair"),
        ),
        sa.CheckConstraint(
            "relationship_type IN ('equivalent', 'related')",
            name=op.f("ck_streaming_relationship_suggestions_relationship_type"),
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name=op.f("ck_streaming_relationship_suggestions_confidence"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_streaming_relationship_suggestions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["lower_track_id"],
            ["streaming_tracks.id"],
            name=op.f("fk_streaming_relationship_suggestions_lower_track"),
        ),
        sa.ForeignKeyConstraint(
            ["higher_track_id"],
            ["streaming_tracks.id"],
            name=op.f("fk_streaming_relationship_suggestions_higher_track"),
        ),
        sa.ForeignKeyConstraint(
            ["accepted_relationship_id"],
            ["streaming_relationships.id"],
            name=op.f("fk_streaming_relationship_suggestions_accepted_relationship"),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_streaming_relationship_suggestions"),
        ),
        sa.UniqueConstraint(
            "lower_track_id",
            "higher_track_id",
            name=op.f("uq_streaming_relationship_suggestions_pair"),
        ),
    )
    op.create_index(
        "ix_streaming_relationship_suggestions_status",
        "streaming_relationship_suggestions",
        ["status"],
    )
    op.create_index(
        "ix_streaming_relationship_suggestions_lower_track_id",
        "streaming_relationship_suggestions",
        ["lower_track_id"],
    )
    op.create_index(
        "ix_streaming_relationship_suggestions_higher_track_id",
        "streaming_relationship_suggestions",
        ["higher_track_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_streaming_relationship_suggestions_higher_track_id",
        table_name="streaming_relationship_suggestions",
    )
    op.drop_index(
        "ix_streaming_relationship_suggestions_lower_track_id",
        table_name="streaming_relationship_suggestions",
    )
    op.drop_index(
        "ix_streaming_relationship_suggestions_status",
        table_name="streaming_relationship_suggestions",
    )
    op.drop_table("streaming_relationship_suggestions")

    op.drop_index(
        "ix_streaming_relationships_higher_track_id",
        table_name="streaming_relationships",
    )
    op.drop_index(
        "ix_streaming_relationships_lower_track_id",
        table_name="streaming_relationships",
    )
    op.drop_table("streaming_relationships")
