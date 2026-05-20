from __future__ import annotations

from sqlalchemy import column, table


final_links_view = table(
    "final_links",
    column("id"),
    column("local_track_id"),
    column("streaming_track_id"),
    column("approved_at"),
)

suggested_links_view = table(
    "suggested_links",
    column("id"),
    column("local_track_id"),
    column("streaming_track_id"),
    column("match_method"),
    column("score"),
    column("status"),
    column("rejected_at"),
    column("created_at"),
)

streaming_relationships_view = table(
    "streaming_relationships",
    column("id"),
    column("lower_track_id"),
    column("higher_track_id"),
    column("relationship_type"),
    column("accepted_at"),
)

streaming_relationship_suggestions_view = table(
    "streaming_relationship_suggestions",
    column("id"),
    column("lower_track_id"),
    column("higher_track_id"),
    column("relationship_type"),
    column("match_method"),
    column("score"),
    column("confidence"),
    column("status"),
    column("accepted_relationship_id"),
    column("accepted_at"),
    column("rejected_at"),
    column("created_at"),
)

beets_items_view = table(
    "beets_items",
    column("beets_id"),
    column("title"),
    column("artist"),
    column("album"),
    column("length"),
    column("isrc"),
)

failed_ingestion_attempts_view = table(
    "failed_ingestion_attempts",
    column("id"),
    column("source_path"),
    column("filename"),
    column("fingerprint"),
    column("failure_reason"),
    column("first_failed_at"),
    column("failed_at"),
    column("attempt_count"),
    column("source_size"),
    column("source_mtime_ns"),
    column("ignored_at"),
    column("local_track_id"),
)
