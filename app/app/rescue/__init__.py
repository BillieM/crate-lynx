"""Metadata rescue helpers for linked local tracks."""

from app.rescue.metadata import (
    ArtworkPayload,
    MetadataRescueError,
    RescueMetadata,
    rescue_metadata,
    write_id3_tags,
)
from app.rescue.router import create_router

__all__ = [
    "ArtworkPayload",
    "MetadataRescueError",
    "RescueMetadata",
    "create_router",
    "rescue_metadata",
    "write_id3_tags",
]
