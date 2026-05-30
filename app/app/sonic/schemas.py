from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.sonic.generation import DEFAULT_GENERATION_CONFIG, normalize_generation_config
from app.sonic.models import (
    DEFAULT_SONIC_BACKFILL_LIMIT,
    MAX_SONIC_BACKFILL_LIMIT,
    PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
    PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL,
    PLAYLIST_GENERATION_METHOD_KMEANS,
    SONIC_SOURCE_ALL_LOCAL,
    SONIC_SOURCE_STREAMING_PLAYLISTS,
    SONIC_TAG_FILTER_ITEM_ATTRIBUTE,
    SONIC_TAG_FILTER_ITEM_FIELD,
    SONIC_TAG_FILTER_MATCH_CONTAINS,
    SONIC_TAG_FILTER_MATCH_EQUALS,
)
from app.sonic.profiles import SONIC_FEATURE_PROFILE_KEYS


class SonicFeatureSummaryResponse(BaseModel):
    total_tracks: int
    ready_tracks: int
    pending_tracks: int
    failed_tracks: int
    missing_tracks: int


class SonicBackfillRequest(BaseModel):
    limit: int = Field(
        default=DEFAULT_SONIC_BACKFILL_LIMIT,
        ge=1,
        le=MAX_SONIC_BACKFILL_LIMIT,
    )


class SonicBackfillResponse(BaseModel):
    job_id: str
    limit: int


class SonicTagFilterRequest(BaseModel):
    scope: Literal["item_field", "item_attribute"] = SONIC_TAG_FILTER_ITEM_ATTRIBUTE
    key: str
    value: str
    match: Literal["equals", "contains"] = SONIC_TAG_FILTER_MATCH_CONTAINS

    @model_validator(mode="after")
    def normalize_filter(self) -> "SonicTagFilterRequest":
        self.key = self.key.strip()
        self.value = self.value.strip()
        if not self.key:
            raise ValueError("Filter key cannot be empty")
        if not self.value:
            raise ValueError("Filter value cannot be empty")
        return self


class SonicSourceFilterRequest(BaseModel):
    source_type: Literal["all_local", "streaming_playlists"] = SONIC_SOURCE_ALL_LOCAL
    streaming_playlist_ids: list[int] = Field(default_factory=list)
    tag_filters: list[SonicTagFilterRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_source(self) -> "SonicSourceFilterRequest":
        if self.source_type == SONIC_SOURCE_STREAMING_PLAYLISTS:
            seen_ids = set()
            self.streaming_playlist_ids = [
                playlist_id
                for playlist_id in self.streaming_playlist_ids
                if playlist_id > 0
                and not (playlist_id in seen_ids or seen_ids.add(playlist_id))
            ]
        else:
            self.streaming_playlist_ids = []
        return self


class PlaylistGenerationConfigRequest(BaseModel):
    clustering_method: Literal["dj_hierarchical_v1", "kmeans", "agglomerative"] = (
        PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL
    )
    max_depth: int = Field(default=DEFAULT_GENERATION_CONFIG["max_depth"], ge=1, le=5)
    target_playlist_size: int = Field(
        default=DEFAULT_GENERATION_CONFIG["target_playlist_size"],
        ge=2,
        le=500,
    )
    min_playlist_size: int = Field(
        default=DEFAULT_GENERATION_CONFIG["min_playlist_size"],
        ge=1,
        le=250,
    )
    max_children: int = Field(
        default=DEFAULT_GENERATION_CONFIG["max_children"],
        ge=2,
        le=10,
    )
    feature_profile: Literal[
        "balanced_v1",
        "energy_v1",
        "texture_v1",
        "harmony_v1",
    ] = DEFAULT_GENERATION_CONFIG["feature_profile"]
    random_seed: int = DEFAULT_GENERATION_CONFIG["random_seed"]

    @model_validator(mode="after")
    def normalize_config(self) -> "PlaylistGenerationConfigRequest":
        normalized = normalize_generation_config(self.model_dump())
        self.clustering_method = normalized["clustering_method"]
        self.max_depth = normalized["max_depth"]
        self.target_playlist_size = normalized["target_playlist_size"]
        self.min_playlist_size = normalized["min_playlist_size"]
        self.max_children = normalized["max_children"]
        self.feature_profile = normalized["feature_profile"]
        self.random_seed = normalized["random_seed"]
        return self


class CreatePlaylistGenerationRunRequest(BaseModel):
    source_filter: SonicSourceFilterRequest = Field(
        default_factory=SonicSourceFilterRequest
    )
    generation_config: PlaylistGenerationConfigRequest = Field(
        default_factory=PlaylistGenerationConfigRequest
    )


class SonicGenerationPreviewResponse(BaseModel):
    analyzer_key: str
    analyzer_version: str
    can_generate: bool
    failed_feature_count: int
    feature_profile: str
    missing_feature_count: int
    pending_feature_count: int
    ready_track_count: int
    skipped_track_count: int
    source_track_count: int


class PlaylistGenerationRunResponse(BaseModel):
    id: int
    generation_number: int
    status: str
    source_filter: dict[str, Any]
    generation_config: dict[str, Any]
    playlist_count: int
    track_count: int
    error_detail: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlaylistGenerationRunListResponse(BaseModel):
    runs: list[PlaylistGenerationRunResponse]


class CreatePlaylistGenerationRunResponse(BaseModel):
    run: PlaylistGenerationRunResponse
    job_id: str


class GeneratedPlaylistResponse(BaseModel):
    id: int
    run_id: int
    parent_playlist_id: int | None
    depth: int
    position: int
    name: str
    summary: dict[str, Any]
    track_count: int
    created_at: datetime


class GeneratedPlaylistListResponse(BaseModel):
    playlists: list[GeneratedPlaylistResponse]


class PlaylistGenerationRunDetailResponse(BaseModel):
    run: PlaylistGenerationRunResponse
    playlists: list[GeneratedPlaylistResponse]


class GeneratedPlaylistTrackResponse(BaseModel):
    id: int
    local_track_id: int
    position: int
    title: str
    artist: str | None
    album: str | None
    duration_ms: int | None
    file_path: str
    library_root_rel_path: str


class GeneratedPlaylistTracksResponse(BaseModel):
    tracks: list[GeneratedPlaylistTrackResponse]


SONIC_TAG_FILTER_SCOPE_VALUES = (
    SONIC_TAG_FILTER_ITEM_FIELD,
    SONIC_TAG_FILTER_ITEM_ATTRIBUTE,
)
SONIC_TAG_FILTER_MATCH_VALUES = (
    SONIC_TAG_FILTER_MATCH_EQUALS,
    SONIC_TAG_FILTER_MATCH_CONTAINS,
)
PLAYLIST_GENERATION_METHOD_VALUES = (
    PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL,
    PLAYLIST_GENERATION_METHOD_KMEANS,
    PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
)
SONIC_FEATURE_PROFILE_VALUES = SONIC_FEATURE_PROFILE_KEYS
