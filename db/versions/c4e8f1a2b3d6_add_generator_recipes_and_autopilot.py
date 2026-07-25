"""add generator recipes and autopilot

Revision ID: c4e8f1a2b3d6
Revises: 1a2b3c4d5e7f
Create Date: 2026-07-25 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4e8f1a2b3d6"
down_revision = "1a2b3c4d5e7f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.add_column(
            sa.Column(
                "automation_level",
                sa.String(),
                server_default="off",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_streaming_playlists_automation_level",
            "automation_level IN ('off', 'sync_only', 'assist', 'full')",
        )

    op.create_table(
        "playlist_generation_recipes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_filter_json", sa.JSON(), nullable=False),
        sa.Column("generation_config_json", sa.JSON(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "regenerate_on_change",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("export_config_json", sa.JSON(), nullable=True),
        sa.Column("last_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "last_regenerated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
            ["last_run_id"],
            ["playlist_generation_runs.id"],
            name=op.f("fk_generation_recipes_last_run_id_generation_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_playlist_generation_recipes"),
        ),
        sa.UniqueConstraint(
            "name",
            name=op.f("uq_playlist_generation_recipes_name"),
        ),
    )
    op.create_index(
        op.f("ix_playlist_generation_recipes_enabled"),
        "playlist_generation_recipes",
        ["enabled"],
        unique=False,
    )

    with op.batch_alter_table("playlist_generation_runs") as batch_op:
        batch_op.add_column(
            sa.Column("recipe_id", sa.Integer(), nullable=True),
        )
        batch_op.add_column(
            sa.Column(
                "run_name",
                sa.String(),
                server_default="Generated crates",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "trigger",
                sa.String(),
                server_default="manual",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("readiness_summary_json", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("analyzer_evidence_json", sa.JSON(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_generation_runs_recipe_id_generation_recipes",
            "playlist_generation_recipes",
            ["recipe_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_playlist_generation_runs_trigger",
            "trigger IN ('manual', 'recipe', 'autopilot')",
        )
        batch_op.create_index(
            "ix_playlist_generation_runs_recipe_id",
            ["recipe_id"],
        )

    op.create_table(
        "autopilot_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "paused",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "schedule_minutes",
            sa.Integer(),
            server_default="60",
            nullable=False,
        ),
        sa.Column(
            "quiet_period_seconds",
            sa.Integer(),
            server_default="900",
            nullable=False,
        ),
        sa.Column(
            "max_concurrent_downloads",
            sa.Integer(),
            server_default="2",
            nullable=False,
        ),
        sa.Column(
            "max_downloads_per_run",
            sa.Integer(),
            server_default="10",
            nullable=False,
        ),
        sa.Column(
            "max_searches_per_run",
            sa.Integer(),
            server_default="25",
            nullable=False,
        ),
        sa.Column(
            "max_storage_bytes_per_run",
            sa.BigInteger(),
            server_default="10737418240",
            nullable=False,
        ),
        sa.Column(
            "retry_max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column(
            "retry_base_seconds",
            sa.Integer(),
            server_default="60",
            nullable=False,
        ),
        sa.Column(
            "retry_max_seconds",
            sa.Integer(),
            server_default="3600",
            nullable=False,
        ),
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
        sa.CheckConstraint("id = 1", name=op.f("ck_autopilot_settings_singleton")),
        sa.CheckConstraint(
            "schedule_minutes > 0",
            name=op.f("ck_autopilot_settings_schedule_minutes_positive"),
        ),
        sa.CheckConstraint(
            "quiet_period_seconds >= 0",
            name=op.f("ck_autopilot_settings_quiet_period_nonnegative"),
        ),
        sa.CheckConstraint(
            "max_concurrent_downloads > 0",
            name=op.f("ck_autopilot_settings_max_concurrent_downloads_positive"),
        ),
        sa.CheckConstraint(
            "max_downloads_per_run >= 0",
            name=op.f("ck_autopilot_settings_max_downloads_per_run_nonnegative"),
        ),
        sa.CheckConstraint(
            "max_searches_per_run >= 0",
            name=op.f("ck_autopilot_settings_max_searches_per_run_nonnegative"),
        ),
        sa.CheckConstraint(
            "max_storage_bytes_per_run >= 0",
            name=op.f("ck_autopilot_settings_max_storage_bytes_per_run_nonnegative"),
        ),
        sa.CheckConstraint(
            "retry_max_attempts > 0",
            name=op.f("ck_autopilot_settings_retry_max_attempts_positive"),
        ),
        sa.CheckConstraint(
            "retry_base_seconds > 0",
            name=op.f("ck_autopilot_settings_retry_base_seconds_positive"),
        ),
        sa.CheckConstraint(
            "retry_max_seconds >= retry_base_seconds",
            name=op.f("ck_autopilot_settings_retry_max_not_below_base"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_autopilot_settings")),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO autopilot_settings (id)
            VALUES (1)
            """
        )
    )

    op.create_table(
        "autopilot_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "refreshed_playlists",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "searched_tracks",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "queued_downloads",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "downloaded_tracks",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "ingested_tracks",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "analyzed_tracks",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "regenerated_recipes",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "refreshed_exports",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "review_items",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "failed_items",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "trigger IN ('startup', 'scheduled', 'manual')",
            name=op.f("ck_autopilot_runs_trigger"),
        ),
        sa.CheckConstraint(
            "status IN "
            "('planning', 'running', 'succeeded', 'partial', 'failed', "
            "'paused', 'skipped')",
            name=op.f("ck_autopilot_runs_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_autopilot_runs")),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_autopilot_runs_idempotency_key"),
        ),
    )
    op.create_index(
        op.f("ix_autopilot_runs_started_at"),
        "autopilot_runs",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_autopilot_runs_status"),
        "autopilot_runs",
        ["status"],
        unique=False,
    )

    with op.batch_alter_table("soulseek_candidates") as batch_op:
        batch_op.add_column(sa.Column("identity_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("version_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("quality_score", sa.Float(), nullable=True))

    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.add_column(sa.Column("automation_run_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "unattended",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("verification_status", sa.String(), nullable=True)
        )
        batch_op.add_column(sa.Column("verification_detail", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_soulseek_acquisitions_automation_run_id_autopilot_runs",
            "autopilot_runs",
            ["automation_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_soulseek_acquisitions_verification_status",
            "verification_status IS NULL OR verification_status IN "
            "('pending', 'verified', 'review', 'failed')",
        )

    op.create_table(
        "autopilot_run_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("playlist_id", sa.Integer(), nullable=True),
        sa.Column("streaming_track_id", sa.Integer(), nullable=True),
        sa.Column("acquisition_id", sa.String(), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("candidate_id", sa.String(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("identity_confidence", sa.Float(), nullable=True),
        sa.Column("version_confidence", sa.Float(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("runner_up_margin", sa.Float(), nullable=True),
        sa.Column("expected_duration_ms", sa.Integer(), nullable=True),
        sa.Column("candidate_duration_ms", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
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
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN "
            "('planned', 'running', 'succeeded', 'skipped', 'retry_wait', "
            "'review', 'failed')",
            name=op.f("ck_autopilot_run_items_status"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_autopilot_run_items_attempt_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_id"],
            ["soulseek_acquisitions.id"],
            name=op.f("fk_autopilot_run_items_acquisition_id_soulseek_acquisitions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["soulseek_candidates.id"],
            name=op.f("fk_autopilot_run_items_candidate_id_soulseek_candidates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["playlist_id"],
            ["streaming_playlists.id"],
            name=op.f("fk_autopilot_run_items_playlist_id_streaming_playlists"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"],
            ["playlist_generation_recipes.id"],
            name=op.f("fk_autopilot_run_items_recipe_id_playlist_generation_recipes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["autopilot_runs.id"],
            name=op.f("fk_autopilot_run_items_run_id_autopilot_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["streaming_track_id"],
            ["streaming_tracks.id"],
            name=op.f("fk_autopilot_run_items_streaming_track_id_streaming_tracks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_autopilot_run_items")),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_autopilot_run_items_idempotency_key"),
        ),
    )
    for index_name, columns in (
        ("ix_autopilot_run_items_next_attempt_at", ["next_attempt_at"]),
        ("ix_autopilot_run_items_playlist_id", ["playlist_id"]),
        ("ix_autopilot_run_items_run_id", ["run_id"]),
        ("ix_autopilot_run_items_status", ["status"]),
        ("ix_autopilot_run_items_streaming_track_id", ["streaming_track_id"]),
    ):
        op.create_index(index_name, "autopilot_run_items", columns, unique=False)


def downgrade() -> None:
    for index_name in (
        "ix_autopilot_run_items_streaming_track_id",
        "ix_autopilot_run_items_status",
        "ix_autopilot_run_items_run_id",
        "ix_autopilot_run_items_playlist_id",
        "ix_autopilot_run_items_next_attempt_at",
    ):
        op.drop_index(index_name, table_name="autopilot_run_items")
    op.drop_table("autopilot_run_items")

    with op.batch_alter_table("soulseek_acquisitions") as batch_op:
        batch_op.drop_constraint(
            "ck_soulseek_acquisitions_verification_status",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_soulseek_acquisitions_automation_run_id_autopilot_runs",
            type_="foreignkey",
        )
        batch_op.drop_column("verified_at")
        batch_op.drop_column("verification_detail")
        batch_op.drop_column("verification_status")
        batch_op.drop_column("unattended")
        batch_op.drop_column("automation_run_id")

    with op.batch_alter_table("soulseek_candidates") as batch_op:
        batch_op.drop_column("quality_score")
        batch_op.drop_column("version_confidence")
        batch_op.drop_column("identity_confidence")

    op.drop_index(op.f("ix_autopilot_runs_status"), table_name="autopilot_runs")
    op.drop_index(
        op.f("ix_autopilot_runs_started_at"),
        table_name="autopilot_runs",
    )
    op.drop_table("autopilot_runs")
    op.drop_table("autopilot_settings")

    with op.batch_alter_table("playlist_generation_runs") as batch_op:
        batch_op.drop_index("ix_playlist_generation_runs_recipe_id")
        batch_op.drop_constraint(
            "ck_playlist_generation_runs_trigger",
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_generation_runs_recipe_id_generation_recipes",
            type_="foreignkey",
        )
        batch_op.drop_column("analyzer_evidence_json")
        batch_op.drop_column("readiness_summary_json")
        batch_op.drop_column("trigger")
        batch_op.drop_column("run_name")
        batch_op.drop_column("recipe_id")

    op.drop_index(
        op.f("ix_playlist_generation_recipes_enabled"),
        table_name="playlist_generation_recipes",
    )
    op.drop_table("playlist_generation_recipes")

    with op.batch_alter_table("streaming_playlists") as batch_op:
        batch_op.drop_constraint(
            "ck_streaming_playlists_automation_level",
            type_="check",
        )
        batch_op.drop_column("automation_level")
