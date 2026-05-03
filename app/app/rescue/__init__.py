"""Metadata rescue helpers for linked local tracks."""

from app.rescue.metadata import (
    ArtworkPayload,
    MetadataRescueError,
    RescueMetadata,
    rescue_metadata,
    write_id3_tags,
)

__all__ = [
    "ArtworkPayload",
    "MetadataRescueError",
    "RescueMetadata",
    "rescue_metadata",
    "write_id3_tags",
]
