from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, insert

from app.ingestion.beets_mirror import (
    beets_item_attributes_table,
    beets_items_table,
)
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_PENDING,
    suggested_links_table,
)
from app.relationships.models import (
    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    normalize_streaming_track_pair,
    streaming_relationship_suggestions_table,
    streaming_relationships_table,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_OFF,
    YOUTUBE_MUSIC_PROVIDER,
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


@dataclass(slots=True)
class TestDataFactory:
    engine: Engine

    def streaming_account(
        self,
        *,
        auth_state: str = "connected",
        auth_token_blob: str = "encrypted-token",
        display_name: str = "Main Account",
        provider: str = YOUTUBE_MUSIC_PROVIDER,
    ) -> int:
        return self._insert(
            streaming_accounts_table,
            auth_state=auth_state,
            auth_token_blob=auth_token_blob,
            display_name=display_name,
            provider=provider,
        )

    def streaming_playlist(
        self,
        *,
        account_id: int,
        last_sync_error: str | None = None,
        last_sync_error_at: datetime | None = None,
        metadata_synced_at: datetime | None = None,
        provider_playlist_id: str = "PL1",
        sync_mode: str = PLAYLIST_SYNC_MODE_OFF,
        title: str = "Morning Mix",
        tracks_synced_at: datetime | None = None,
    ) -> int:
        return self._insert(
            streaming_playlists_table,
            account_id=account_id,
            last_sync_error=last_sync_error,
            last_sync_error_at=last_sync_error_at,
            metadata_synced_at=metadata_synced_at,
            provider_playlist_id=provider_playlist_id,
            sync_mode=sync_mode,
            title=title,
            tracks_synced_at=tracks_synced_at,
        )

    def streaming_track(
        self,
        *,
        album: str | None = "Album",
        artist: str = "Artist",
        duration_ms: int | None = 123000,
        isrc: str | None = "ABC123456789",
        provider_track_id: str = "ytm-1",
        title: str = "Track",
        year: int | None = 2024,
    ) -> int:
        return self._insert(
            streaming_tracks_table,
            album=album,
            artist=artist,
            duration_ms=duration_ms,
            isrc=isrc,
            provider_track_id=provider_track_id,
            title=title,
            year=year,
        )

    def playlist_membership(
        self,
        *,
        playlist_id: int,
        position: int = 1,
        streaming_track_id: int,
    ) -> int:
        return self._insert(
            playlist_membership_table,
            playlist_id=playlist_id,
            position=position,
            streaming_track_id=streaming_track_id,
        )

    def local_track(
        self,
        *,
        beets_id: int | None = None,
        file_path: str = "Artist/Track.mp3",
        fingerprint: str | None = "fingerprint",
        library_root_rel_path: str | None = None,
    ) -> int:
        return self._insert(
            local_tracks_table,
            beets_id=beets_id,
            file_path=file_path,
            fingerprint=fingerprint,
            library_root_rel_path=library_root_rel_path or file_path,
        )

    def beets_item(
        self,
        *,
        beets_id: int,
        album_id: int | None = None,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        isrc: str | None = None,
        length: float | None = None,
        **fixed_fields: Any,
    ) -> int:
        return self._insert(
            beets_items_table,
            beets_id=beets_id,
            album_id=album_id,
            title=title,
            artist=artist,
            album=album,
            isrc=isrc,
            length=length,
            **fixed_fields,
        )

    def beets_item_attribute(self, *, beets_id: int, key: str, value: str) -> int:
        return self._insert(
            beets_item_attributes_table,
            entity_id=beets_id,
            key=key,
            value=value,
        )

    def suggested_link(
        self,
        *,
        local_track_id: int,
        match_method: str = "tags",
        rejected_at: datetime | None = None,
        score: float = 0.82,
        status: str = SUGGESTED_LINK_STATUS_PENDING,
        streaming_track_id: int,
    ) -> int:
        return self._insert(
            suggested_links_table,
            local_track_id=local_track_id,
            match_method=match_method,
            rejected_at=rejected_at,
            score=score,
            status=status,
            streaming_track_id=streaming_track_id,
        )

    def final_link(
        self,
        *,
        approved_at: datetime | None = None,
        local_track_id: int,
        streaming_track_id: int,
    ) -> int:
        return self._insert(
            final_links_table,
            approved_at=approved_at or datetime(2026, 5, 1, tzinfo=UTC),
            local_track_id=local_track_id,
            streaming_track_id=streaming_track_id,
        )

    def streaming_relationship(
        self,
        *,
        accepted_at: datetime | None = None,
        first_track_id: int,
        relationship_type: str = STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
        second_track_id: int,
    ) -> int:
        pair = normalize_streaming_track_pair(first_track_id, second_track_id)
        return self._insert(
            streaming_relationships_table,
            accepted_at=accepted_at or datetime(2026, 5, 1, tzinfo=UTC),
            lower_track_id=pair.lower_track_id,
            higher_track_id=pair.higher_track_id,
            relationship_type=relationship_type,
        )

    def streaming_relationship_suggestion(
        self,
        *,
        accepted_at: datetime | None = None,
        accepted_relationship_id: int | None = None,
        confidence: str = STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
        first_track_id: int,
        match_method: str = "isrc",
        rejected_at: datetime | None = None,
        relationship_type: str = STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
        score: float = 0.98,
        second_track_id: int,
        status: str = STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    ) -> int:
        pair = normalize_streaming_track_pair(first_track_id, second_track_id)
        timestamp = datetime(2026, 5, 1, tzinfo=UTC)
        if (
            status == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED
            and accepted_at is None
        ):
            accepted_at = timestamp
        if (
            status == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED
            and rejected_at is None
        ):
            rejected_at = timestamp

        return self._insert(
            streaming_relationship_suggestions_table,
            accepted_at=accepted_at,
            accepted_relationship_id=accepted_relationship_id,
            confidence=confidence,
            lower_track_id=pair.lower_track_id,
            higher_track_id=pair.higher_track_id,
            match_method=match_method,
            rejected_at=rejected_at,
            relationship_type=relationship_type,
            score=score,
            status=status,
        )

    def _insert(self, table: Any, **values: Any) -> int:
        with self.engine.begin() as connection:
            inserted_id = connection.execute(
                insert(table).values(**values)
            ).inserted_primary_key[0]

        if not isinstance(inserted_id, int):
            raise ValueError(f"Failed to insert test row into {table.name}")
        return inserted_id
