"""add soulseek acquisitions

Revision ID: 9e8f7a6b5c4d
Revises: 0b7c9d2e4f6a
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9e8f7a6b5c4d"
down_revision = "0b7c9d2e4f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soulseek_acquisitions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("streaming_track_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("search_text", sa.String(), nullable=True),
        sa.Column("fallback_search_text", sa.String(), nullable=True),
        sa.Column("slskd_search_id", sa.String(), nullable=True),
        sa.Column("slskd_fallback_search_id", sa.String(), nullable=True),
        sa.Column(
            "candidate_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("selected_candidate_id", sa.String(), nullable=True),
        sa.Column("slskd_batch_id", sa.String(), nullable=True),
        sa.Column("destination", sa.String(), nullable=True),
        sa.Column("local_track_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("enqueue_job_id", sa.String(), nullable=True),
        sa.Column("refresh_job_id", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("searched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proposal_available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_soulseek_acquisitions")),
        sa.ForeignKeyConstraint(
            ["streaming_track_id"],
            ["streaming_tracks.id"],
            name="fk_soulseek_acquisitions_streaming_track_id_streaming_tracks",
        ),
        sa.ForeignKeyConstraint(
            ["local_track_id"],
            ["local_tracks.id"],
            name="fk_soulseek_acquisitions_local_track_id_local_tracks",
        ),
    )
    op.create_index(
        "ix_soulseek_acquisitions_streaming_track_id",
        "soulseek_acquisitions",
        ["streaming_track_id"],
    )
    op.create_index(
        "ix_soulseek_acquisitions_status",
        "soulseek_acquisitions",
        ["status"],
    )
    op.create_index(
        "ix_soulseek_acquisitions_local_track_id",
        "soulseek_acquisitions",
        ["local_track_id"],
    )

    op.create_table(
        "soulseek_candidates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("acquisition_id", sa.String(), nullable=False),
        sa.Column("slskd_search_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("extension", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("bit_rate", sa.Integer(), nullable=True),
        sa.Column("bit_depth", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("is_variable_bit_rate", sa.Boolean(), nullable=True),
        sa.Column("has_free_upload_slot", sa.Boolean(), nullable=False),
        sa.Column("queue_length", sa.BigInteger(), nullable=True),
        sa.Column("upload_speed", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_soulseek_candidates")),
        sa.ForeignKeyConstraint(
            ["acquisition_id"],
            ["soulseek_acquisitions.id"],
            name="fk_soulseek_candidates_acquisition_id_soulseek_acquisitions",
        ),
    )
    op.create_index(
        "ix_soulseek_candidates_acquisition_id",
        "soulseek_candidates",
        ["acquisition_id"],
    )
    op.create_index(
        "ix_soulseek_candidates_acquisition_score",
        "soulseek_candidates",
        ["acquisition_id", "score"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_soulseek_candidates_acquisition_score",
        table_name="soulseek_candidates",
    )
    op.drop_index(
        "ix_soulseek_candidates_acquisition_id",
        table_name="soulseek_candidates",
    )
    op.drop_table("soulseek_candidates")
    op.drop_index(
        "ix_soulseek_acquisitions_local_track_id",
        table_name="soulseek_acquisitions",
    )
    op.drop_index(
        "ix_soulseek_acquisitions_status",
        table_name="soulseek_acquisitions",
    )
    op.drop_index(
        "ix_soulseek_acquisitions_streaming_track_id",
        table_name="soulseek_acquisitions",
    )
    op.drop_table("soulseek_acquisitions")
