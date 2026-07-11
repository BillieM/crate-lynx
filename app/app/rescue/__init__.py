"""Metadata rescue helpers for linked local tracks."""

from app.rescue.metadata import (
    ArtworkPayload,
    MetadataRescueConflictError,
    MetadataRescueError,
    MetadataRescueResult,
    RescueMetadata,
    RescueStageResult,
    reconcile_beets_mirror,
    rescue_metadata,
    update_beets_catalogue,
    write_id3_tags,
)
from app.rescue.router import create_router

__all__ = [
    "ArtworkPayload",
    "MetadataRescueConflictError",
    "MetadataRescueError",
    "MetadataRescueResult",
    "RescueMetadata",
    "RescueStageResult",
    "create_router",
    "reconcile_beets_mirror",
    "rescue_metadata",
    "update_beets_catalogue",
    "write_id3_tags",
]
