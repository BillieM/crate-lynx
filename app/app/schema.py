from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import ForeignKeyConstraint, MetaData, Table

from app.ingestion.failures import metadata as failed_ingestion_attempts_metadata
from app.ingestion.beets_mirror import metadata as beets_mirror_metadata
from app.links.store import metadata as links_metadata
from app.local_dedupe.models import metadata as local_dedupe_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.models import metadata as m3u_metadata
from app.matching.pipeline import metadata as suggested_links_metadata
from app.relationships.models import metadata as relationships_metadata
from app.settings.models import metadata as settings_metadata
from app.sonic.models import metadata as sonic_metadata
from app.soulseek.models import metadata as soulseek_metadata
from app.streaming.models import metadata as streaming_metadata


def build_app_metadata() -> MetaData:
    combined = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

    for table in _app_tables():
        table.to_metadata(combined)

    _add_foreign_keys(combined)

    return combined


def _app_tables() -> Iterable[Table]:
    metadatas = (
        local_tracks_metadata,
        beets_mirror_metadata,
        streaming_metadata,
        links_metadata,
        suggested_links_metadata,
        relationships_metadata,
        settings_metadata,
        sonic_metadata,
        soulseek_metadata,
        local_dedupe_metadata,
        m3u_metadata,
        failed_ingestion_attempts_metadata,
    )
    for metadata in metadatas:
        yield from metadata.tables.values()


def _add_foreign_keys(metadata: MetaData) -> None:
    foreign_keys = {
        "failed_ingestion_attempts": (("local_track_id", "local_tracks.id"),),
        "final_links": (
            ("local_track_id", "local_tracks.id"),
            ("streaming_track_id", "streaming_tracks.id"),
        ),
        "playlist_membership": (
            ("playlist_id", "streaming_playlists.id"),
            ("streaming_track_id", "streaming_tracks.id"),
        ),
        "streaming_playlists": (("account_id", "streaming_accounts.id"),),
        "suggested_links": (
            ("local_track_id", "local_tracks.id"),
            ("streaming_track_id", "streaming_tracks.id"),
        ),
        "streaming_relationships": (
            (
                "lower_track_id",
                "streaming_tracks.id",
                "fk_streaming_relationships_lower_track",
            ),
            (
                "higher_track_id",
                "streaming_tracks.id",
                "fk_streaming_relationships_higher_track",
            ),
        ),
        "streaming_relationship_suggestions": (
            (
                "lower_track_id",
                "streaming_tracks.id",
                "fk_streaming_relationship_suggestions_lower_track",
            ),
            (
                "higher_track_id",
                "streaming_tracks.id",
                "fk_streaming_relationship_suggestions_higher_track",
            ),
            (
                "accepted_relationship_id",
                "streaming_relationships.id",
                "fk_streaming_relationship_suggestions_accepted_relationship",
            ),
        ),
        "sonic_track_features": (("local_track_id", "local_tracks.id"),),
        "soulseek_acquisitions": (
            ("streaming_track_id", "streaming_tracks.id"),
            ("local_track_id", "local_tracks.id"),
            ("final_link_id", "final_links.id"),
        ),
        "soulseek_candidates": (("acquisition_id", "soulseek_acquisitions.id"),),
        "generated_playlists": (
            ("run_id", "playlist_generation_runs.id"),
            (
                "parent_playlist_id",
                "generated_playlists.id",
                "fk_generated_playlists_parent_playlist_id_generated_playlists",
            ),
        ),
        "generated_playlist_tracks": (
            (
                "generated_playlist_id",
                "generated_playlists.id",
                "fk_generated_playlist_tracks_generated_playlist_id_generated_playlists",
            ),
            ("local_track_id", "local_tracks.id"),
        ),
    }
    for table_name, constraints in foreign_keys.items():
        table = metadata.tables[table_name]
        for constraint in constraints:
            column_name = constraint[0]
            reference = constraint[1]
            name = (
                constraint[2]
                if len(constraint) == 3
                else f"fk_{table_name}_{column_name}_{reference.rsplit('.', 1)[0]}"
            )
            table.append_constraint(
                ForeignKeyConstraint(
                    [column_name],
                    [reference],
                    name=name,
                )
            )
