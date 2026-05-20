from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from ytmusicapi.exceptions import YTMusicError

from app.core.db import create_database_engine
from app.core.tables import final_links_view, suggested_links_view
from app.streaming.adapters.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicAuthenticationError,
    YouTubeMusicPlaylist,
    YouTubeMusicTrack,
    sync_library_playlists,
    sync_library_playlist_tracks,
    sync_single_library_playlist_tracks,
)
from app.streaming.crypto import decrypt_token, encrypt_token
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_OFF,
    PLAYLIST_SYNC_MODES,
    PlaylistMembershipRecord,
    PersistedStreamingAccount,
    StoredStreamingAccount,
    StreamingAccountRecord,
    StreamingPlaylistDetail,
    StreamingPlaylistRecord,
    StreamingPlaylistSummary,
    StreamingPlaylistTrack,
    StreamingTrackRecord,
    STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
    STREAMING_ACCOUNT_AUTH_STATE_ERROR,
    YOUTUBE_MUSIC_PROVIDER,
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)

if TYPE_CHECKING:
    from app.relationships.suggestions import (
        StreamingRelationshipSuggestionGenerationResult,
    )

PENDING_LINK_STATUS = "pending"


def _conflict_insert(target_table: Any, dialect_name: str) -> Any:
    if dialect_name == "postgresql":
        return postgresql_insert(target_table)
    if dialect_name == "sqlite":
        return sqlite_insert(target_table)
    raise ValueError(
        f"Unsupported database dialect for streaming upsert: {dialect_name}"
    )


class StreamingAccountStore:
    def __init__(
        self, database_url: str | None = None, *, engine: Engine | None = None
    ) -> None:
        self._engine = engine or create_database_engine(database_url)

    def create_youtube_music_account(
        self,
        *,
        display_name: str,
        browser_headers: dict[str, Any],
    ) -> PersistedStreamingAccount:
        encrypted_token = encrypt_token(json.dumps(browser_headers, sort_keys=True))

        with self._engine.begin() as connection:
            result = connection.execute(
                insert(streaming_accounts_table).values(
                    provider=YOUTUBE_MUSIC_PROVIDER,
                    display_name=display_name,
                    auth_token_blob=encrypted_token,
                    auth_state=STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
                    auth_error=None,
                    auth_error_at=None,
                )
            )

        inserted_id = result.inserted_primary_key[0]
        if not isinstance(inserted_id, int):
            raise ValueError("Failed to persist streaming account")

        return PersistedStreamingAccount(
            id=inserted_id,
            provider=YOUTUBE_MUSIC_PROVIDER,
            display_name=display_name,
        )

    def list_accounts(self) -> list[StreamingAccountRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    streaming_accounts_table.c.id,
                    streaming_accounts_table.c.provider,
                    streaming_accounts_table.c.display_name,
                    streaming_accounts_table.c.auth_state,
                    streaming_accounts_table.c.auth_error,
                    streaming_accounts_table.c.auth_error_at,
                    streaming_accounts_table.c.created_at,
                    streaming_accounts_table.c.updated_at,
                ).order_by(streaming_accounts_table.c.id.asc())
            ).mappings()

            return [
                StreamingAccountRecord(
                    id=row["id"],
                    provider=row["provider"],
                    display_name=row["display_name"],
                    auth_state=row["auth_state"],
                    auth_error=row["auth_error"],
                    auth_error_at=row["auth_error_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]

    def update_youtube_music_account_auth(
        self,
        *,
        account_id: int,
        browser_headers: dict[str, Any],
    ) -> StreamingAccountRecord | None:
        encrypted_token = encrypt_token(json.dumps(browser_headers, sort_keys=True))
        updated_at = datetime.now(UTC)

        with self._engine.begin() as connection:
            result = connection.execute(
                update(streaming_accounts_table)
                .where(streaming_accounts_table.c.id == account_id)
                .values(
                    auth_token_blob=encrypted_token,
                    auth_state=STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
                    auth_error=None,
                    auth_error_at=None,
                    updated_at=updated_at,
                )
            )
            if result.rowcount == 0:
                return None

            row = (
                connection.execute(
                    select(
                        streaming_accounts_table.c.id,
                        streaming_accounts_table.c.provider,
                        streaming_accounts_table.c.display_name,
                        streaming_accounts_table.c.auth_state,
                        streaming_accounts_table.c.auth_error,
                        streaming_accounts_table.c.auth_error_at,
                        streaming_accounts_table.c.created_at,
                        streaming_accounts_table.c.updated_at,
                    ).where(streaming_accounts_table.c.id == account_id)
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return StreamingAccountRecord(
            id=row["id"],
            provider=row["provider"],
            display_name=row["display_name"],
            auth_state=row["auth_state"],
            auth_error=row["auth_error"],
            auth_error_at=row["auth_error_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_account(self, account_id: int) -> StoredStreamingAccount:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        streaming_accounts_table.c.id,
                        streaming_accounts_table.c.provider,
                        streaming_accounts_table.c.display_name,
                        streaming_accounts_table.c.auth_state,
                        streaming_accounts_table.c.auth_error,
                        streaming_accounts_table.c.auth_error_at,
                        streaming_accounts_table.c.auth_token_blob,
                    ).where(streaming_accounts_table.c.id == account_id)
                )
                .mappings()
                .one()
            )

        return StoredStreamingAccount(
            id=row["id"],
            provider=row["provider"],
            display_name=row["display_name"],
            auth_state=row["auth_state"],
            auth_error=row["auth_error"],
            auth_error_at=row["auth_error_at"],
            browser_headers=json.loads(decrypt_token(row["auth_token_blob"])),
        )

    def clear_account_auth_error(self, *, account_id: int) -> None:
        self._set_account_auth_state(
            account_id=account_id,
            auth_state=STREAMING_ACCOUNT_AUTH_STATE_CONNECTED,
            auth_error=None,
        )

    def mark_account_auth_error(self, *, account_id: int, error: Exception) -> None:
        self._set_account_auth_state(
            account_id=account_id,
            auth_state=STREAMING_ACCOUNT_AUTH_STATE_ERROR,
            auth_error=_format_auth_error(error),
        )

    def _set_account_auth_state(
        self,
        *,
        account_id: int,
        auth_state: str,
        auth_error: str | None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(streaming_accounts_table)
                .where(streaming_accounts_table.c.id == account_id)
                .values(
                    auth_state=auth_state,
                    auth_error=auth_error,
                    auth_error_at=(None if auth_error is None else datetime.now(UTC)),
                    updated_at=datetime.now(UTC),
                )
            )

    def upsert_playlists(
        self,
        *,
        account_id: int,
        playlists: list[YouTubeMusicPlaylist],
        metadata_synced_at: datetime | None = None,
    ) -> list[StreamingPlaylistRecord]:
        playlist_rows: list[StreamingPlaylistRecord] = []
        sync_timestamp = metadata_synced_at or datetime.now(UTC)

        with self._engine.begin() as connection:
            for playlist in playlists:
                statement = _conflict_insert(
                    streaming_playlists_table,
                    connection.dialect.name,
                ).values(
                    account_id=account_id,
                    provider_playlist_id=playlist.provider_playlist_id,
                    title=playlist.title,
                    sync_mode=PLAYLIST_SYNC_MODE_OFF,
                    provider_track_count=playlist.provider_track_count,
                    metadata_synced_at=sync_timestamp,
                    tracks_synced_at=None,
                    last_sync_error=None,
                    last_sync_error_at=None,
                )
                row = (
                    connection.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                streaming_playlists_table.c.account_id,
                                streaming_playlists_table.c.provider_playlist_id,
                            ],
                            set_={
                                "title": statement.excluded.title,
                                "provider_track_count": (
                                    statement.excluded.provider_track_count
                                ),
                                "metadata_synced_at": (
                                    statement.excluded.metadata_synced_at
                                ),
                            },
                        ).returning(
                            streaming_playlists_table.c.id,
                            streaming_playlists_table.c.account_id,
                            streaming_playlists_table.c.provider_playlist_id,
                            streaming_playlists_table.c.title,
                            streaming_playlists_table.c.sync_mode,
                            streaming_playlists_table.c.provider_track_count,
                            streaming_playlists_table.c.metadata_synced_at,
                            streaming_playlists_table.c.tracks_synced_at,
                            streaming_playlists_table.c.last_sync_error,
                            streaming_playlists_table.c.last_sync_error_at,
                        )
                    )
                    .mappings()
                    .one()
                )

                playlist_rows.append(
                    StreamingPlaylistRecord(
                        id=row["id"],
                        account_id=row["account_id"],
                        provider_playlist_id=row["provider_playlist_id"],
                        title=row["title"],
                        sync_mode=row["sync_mode"],
                        provider_track_count=row["provider_track_count"],
                        metadata_synced_at=row["metadata_synced_at"],
                        tracks_synced_at=row["tracks_synced_at"],
                        last_sync_error=row["last_sync_error"],
                        last_sync_error_at=row["last_sync_error_at"],
                    )
                )

        return playlist_rows

    def list_playlists(
        self, *, sync_mode: str | None = None
    ) -> list[StreamingPlaylistSummary]:
        query = (
            select(
                streaming_playlists_table.c.id,
                streaming_playlists_table.c.account_id,
                streaming_playlists_table.c.provider_playlist_id,
                streaming_playlists_table.c.title,
                streaming_playlists_table.c.sync_mode,
                streaming_playlists_table.c.provider_track_count,
                streaming_playlists_table.c.metadata_synced_at,
                streaming_playlists_table.c.tracks_synced_at,
                streaming_playlists_table.c.last_sync_error,
                streaming_playlists_table.c.last_sync_error_at,
                func.count(playlist_membership_table.c.id).label(
                    "imported_track_count"
                ),
            )
            .select_from(
                streaming_playlists_table.outerjoin(
                    playlist_membership_table,
                    playlist_membership_table.c.playlist_id
                    == streaming_playlists_table.c.id,
                )
            )
            .group_by(
                streaming_playlists_table.c.id,
                streaming_playlists_table.c.account_id,
                streaming_playlists_table.c.provider_playlist_id,
                streaming_playlists_table.c.title,
                streaming_playlists_table.c.sync_mode,
                streaming_playlists_table.c.provider_track_count,
                streaming_playlists_table.c.metadata_synced_at,
                streaming_playlists_table.c.tracks_synced_at,
                streaming_playlists_table.c.last_sync_error,
                streaming_playlists_table.c.last_sync_error_at,
            )
            .order_by(streaming_playlists_table.c.id.asc())
        )
        if sync_mode is not None:
            query = query.where(streaming_playlists_table.c.sync_mode == sync_mode)

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings()

            return [
                StreamingPlaylistSummary(
                    id=row["id"],
                    account_id=row["account_id"],
                    provider_playlist_id=row["provider_playlist_id"],
                    title=row["title"],
                    sync_mode=row["sync_mode"],
                    provider_track_count=row["provider_track_count"],
                    imported_track_count=row["imported_track_count"],
                    metadata_synced_at=row["metadata_synced_at"],
                    tracks_synced_at=row["tracks_synced_at"],
                    last_sync_error=row["last_sync_error"],
                    last_sync_error_at=row["last_sync_error_at"],
                )
                for row in rows
            ]

    def get_playlist_detail(
        self, playlist_id: int, *, sync_mode: str | None = None
    ) -> StreamingPlaylistDetail | None:
        playlist = self._get_playlist_summary(playlist_id, sync_mode=sync_mode)
        if playlist is None:
            return None

        counts = {"linked": 0, "pending": 0, "unlinked": 0}
        for track in self.list_playlist_tracks(playlist_id):
            counts[track.status] += 1

        return StreamingPlaylistDetail(
            id=playlist.id,
            account_id=playlist.account_id,
            provider_playlist_id=playlist.provider_playlist_id,
            title=playlist.title,
            sync_mode=playlist.sync_mode,
            provider_track_count=playlist.provider_track_count,
            imported_track_count=playlist.imported_track_count,
            metadata_synced_at=playlist.metadata_synced_at,
            tracks_synced_at=playlist.tracks_synced_at,
            last_sync_error=playlist.last_sync_error,
            last_sync_error_at=playlist.last_sync_error_at,
            cover_art_url=None,
            linked_count=counts["linked"],
            pending_count=counts["pending"],
            unlinked_count=counts["unlinked"],
        )

    def set_playlist_sync_mode(
        self, *, playlist_id: int, sync_mode: str
    ) -> StreamingPlaylistSummary | None:
        if sync_mode not in PLAYLIST_SYNC_MODES:
            raise ValueError(f"Unsupported playlist sync mode: {sync_mode}")

        with self._engine.begin() as connection:
            result = connection.execute(
                update(streaming_playlists_table)
                .where(streaming_playlists_table.c.id == playlist_id)
                .values(sync_mode=sync_mode)
            )

        if result.rowcount == 0:
            return None

        return self._get_playlist_summary(playlist_id)

    def playlist_exists(
        self, playlist_id: int, *, sync_mode: str | None = None
    ) -> bool:
        query = select(streaming_playlists_table.c.id).where(
            streaming_playlists_table.c.id == playlist_id
        )
        if sync_mode is not None:
            query = query.where(streaming_playlists_table.c.sync_mode == sync_mode)

        with self._engine.connect() as connection:
            return connection.execute(query).scalar_one_or_none() is not None

    def list_playlist_tracks(self, playlist_id: int) -> list[StreamingPlaylistTrack]:
        pending_link_ids = (
            select(
                suggested_links_view.c.streaming_track_id,
                func.min(suggested_links_view.c.id).label("proposal_id"),
            )
            .where(suggested_links_view.c.status == PENDING_LINK_STATUS)
            .group_by(suggested_links_view.c.streaming_track_id)
            .subquery()
        )
        pending_links = suggested_links_view.alias("pending_links")

        query = (
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.provider_track_id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.duration_ms,
                playlist_membership_table.c.position,
                final_links_view.c.id.label("final_link_id"),
                final_links_view.c.local_track_id.label("final_local_track_id"),
                pending_links.c.id.label("proposal_id"),
                pending_links.c.local_track_id.label("proposal_local_track_id"),
            )
            .select_from(
                playlist_membership_table.join(
                    streaming_tracks_table,
                    streaming_tracks_table.c.id
                    == playlist_membership_table.c.streaming_track_id,
                )
                .outerjoin(
                    final_links_view,
                    final_links_view.c.streaming_track_id
                    == streaming_tracks_table.c.id,
                )
                .outerjoin(
                    pending_link_ids,
                    pending_link_ids.c.streaming_track_id
                    == streaming_tracks_table.c.id,
                )
                .outerjoin(
                    pending_links,
                    pending_links.c.id == pending_link_ids.c.proposal_id,
                )
            )
            .where(playlist_membership_table.c.playlist_id == playlist_id)
            .order_by(playlist_membership_table.c.position.asc())
        )

        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings()
            return [self._playlist_track_from_row(row) for row in rows]

    def _get_playlist_summary(
        self, playlist_id: int, *, sync_mode: str | None = None
    ) -> StreamingPlaylistSummary | None:
        query = (
            select(
                streaming_playlists_table.c.id,
                streaming_playlists_table.c.account_id,
                streaming_playlists_table.c.provider_playlist_id,
                streaming_playlists_table.c.title,
                streaming_playlists_table.c.sync_mode,
                streaming_playlists_table.c.provider_track_count,
                streaming_playlists_table.c.metadata_synced_at,
                streaming_playlists_table.c.tracks_synced_at,
                streaming_playlists_table.c.last_sync_error,
                streaming_playlists_table.c.last_sync_error_at,
                func.count(playlist_membership_table.c.id).label(
                    "imported_track_count"
                ),
            )
            .select_from(
                streaming_playlists_table.outerjoin(
                    playlist_membership_table,
                    playlist_membership_table.c.playlist_id
                    == streaming_playlists_table.c.id,
                )
            )
            .where(streaming_playlists_table.c.id == playlist_id)
            .group_by(
                streaming_playlists_table.c.id,
                streaming_playlists_table.c.account_id,
                streaming_playlists_table.c.provider_playlist_id,
                streaming_playlists_table.c.title,
                streaming_playlists_table.c.sync_mode,
                streaming_playlists_table.c.provider_track_count,
                streaming_playlists_table.c.metadata_synced_at,
                streaming_playlists_table.c.tracks_synced_at,
                streaming_playlists_table.c.last_sync_error,
                streaming_playlists_table.c.last_sync_error_at,
            )
        )
        if sync_mode is not None:
            query = query.where(streaming_playlists_table.c.sync_mode == sync_mode)

        with self._engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()

        if row is None:
            return None

        return StreamingPlaylistSummary(
            id=row["id"],
            account_id=row["account_id"],
            provider_playlist_id=row["provider_playlist_id"],
            title=row["title"],
            sync_mode=row["sync_mode"],
            provider_track_count=row["provider_track_count"],
            imported_track_count=row["imported_track_count"],
            metadata_synced_at=row["metadata_synced_at"],
            tracks_synced_at=row["tracks_synced_at"],
            last_sync_error=row["last_sync_error"],
            last_sync_error_at=row["last_sync_error_at"],
        )

    def _playlist_track_from_row(
        self, row: Mapping[str, Any]
    ) -> StreamingPlaylistTrack:
        if row["final_link_id"] is not None:
            status = "linked"
            local_track_id = row["final_local_track_id"]
            proposal_id = None
        elif row["proposal_id"] is not None:
            status = "pending"
            local_track_id = row["proposal_local_track_id"]
            proposal_id = row["proposal_id"]
        else:
            status = "unlinked"
            local_track_id = None
            proposal_id = None

        return StreamingPlaylistTrack(
            id=row["id"],
            provider_track_id=row["provider_track_id"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            duration_ms=row["duration_ms"],
            position=row["position"],
            status=status,
            final_link_id=row["final_link_id"],
            local_track_id=local_track_id,
            proposal_id=proposal_id,
        )

    def upsert_tracks(
        self,
        *,
        tracks: list[YouTubeMusicTrack],
    ) -> list[StreamingTrackRecord]:
        track_rows: list[StreamingTrackRecord] = []

        with self._engine.begin() as connection:
            for track in tracks:
                statement = _conflict_insert(
                    streaming_tracks_table,
                    connection.dialect.name,
                ).values(
                    provider_track_id=track.provider_track_id,
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    year=track.year,
                    isrc=track.isrc,
                    duration_ms=track.duration_ms,
                )

                row = (
                    connection.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                streaming_tracks_table.c.provider_track_id,
                            ],
                            set_={
                                "title": statement.excluded.title,
                                "artist": statement.excluded.artist,
                                "album": statement.excluded.album,
                                "year": statement.excluded.year,
                                "isrc": func.coalesce(
                                    statement.excluded.isrc,
                                    streaming_tracks_table.c.isrc,
                                ),
                                "duration_ms": statement.excluded.duration_ms,
                            },
                        ).returning(
                            streaming_tracks_table.c.id,
                            streaming_tracks_table.c.provider_track_id,
                            streaming_tracks_table.c.title,
                            streaming_tracks_table.c.artist,
                            streaming_tracks_table.c.album,
                            streaming_tracks_table.c.year,
                            streaming_tracks_table.c.isrc,
                            streaming_tracks_table.c.duration_ms,
                        )
                    )
                    .mappings()
                    .one()
                )

                track_rows.append(
                    StreamingTrackRecord(
                        id=row["id"],
                        provider_track_id=row["provider_track_id"],
                        title=row["title"],
                        artist=row["artist"],
                        album=row["album"],
                        year=row["year"],
                        isrc=row["isrc"],
                        duration_ms=row["duration_ms"],
                    )
                )

        return track_rows

    def replace_playlist_membership(
        self,
        *,
        playlist_id: int,
        tracks: list[YouTubeMusicTrack],
    ) -> list[PlaylistMembershipRecord]:
        track_rows = self.upsert_tracks(tracks=tracks)
        membership_rows: list[PlaylistMembershipRecord] = []

        with self._engine.begin() as connection:
            connection.execute(
                delete(playlist_membership_table).where(
                    playlist_membership_table.c.playlist_id == playlist_id
                )
            )

            for position, track in enumerate(track_rows, start=1):
                result = connection.execute(
                    insert(playlist_membership_table).values(
                        playlist_id=playlist_id,
                        streaming_track_id=track.id,
                        position=position,
                    )
                )
                membership_id = result.inserted_primary_key[0]
                if not isinstance(membership_id, int):
                    raise ValueError("Failed to persist playlist membership")
                membership_rows.append(
                    PlaylistMembershipRecord(
                        id=membership_id,
                        playlist_id=playlist_id,
                        streaming_track_id=track.id,
                        position=position,
                    )
                )

        return membership_rows

    def mark_playlist_sync_failure(
        self,
        *,
        playlist_id: int,
        error: str,
        failed_at: datetime | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(streaming_playlists_table)
                .where(streaming_playlists_table.c.id == playlist_id)
                .values(
                    last_sync_error=error,
                    last_sync_error_at=failed_at or datetime.now(UTC),
                )
            )

    def clear_playlist_sync_failure(self, *, playlist_id: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(streaming_playlists_table)
                .where(streaming_playlists_table.c.id == playlist_id)
                .values(
                    last_sync_error=None,
                    last_sync_error_at=None,
                )
            )

    def mark_playlist_sync_success(
        self,
        *,
        playlist_id: int,
        tracks_synced_at: datetime | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(streaming_playlists_table)
                .where(streaming_playlists_table.c.id == playlist_id)
                .values(
                    tracks_synced_at=tracks_synced_at or datetime.now(UTC),
                    last_sync_error=None,
                    last_sync_error_at=None,
                )
            )

    def sync_youtube_music_playlists(
        self,
        *,
        account_id: int,
    ) -> list[StreamingPlaylistRecord]:
        return self._run_youtube_music_sync(
            account_id=account_id,
            run_sync=lambda adapter: sync_library_playlists(
                account_id=account_id,
                adapter=adapter,
                playlist_store=self,
            ),
            after_success=self.generate_streaming_relationship_suggestions,
        )

    def sync_youtube_music_playlist_tracks(
        self,
        *,
        account_id: int,
    ) -> list[PlaylistMembershipRecord]:
        return self._run_youtube_music_sync(
            account_id=account_id,
            run_sync=lambda adapter: sync_library_playlist_tracks(
                account_id=account_id,
                adapter=adapter,
                playlist_store=self,
            ),
            after_success=self.generate_streaming_relationship_suggestions,
        )

    def sync_youtube_music_playlist(
        self,
        *,
        playlist_id: int,
    ) -> list[PlaylistMembershipRecord]:
        playlist = self._get_playlist_summary(playlist_id)
        if playlist is None:
            return []

        def run_single_playlist_sync(
            adapter: YouTubeMusicAdapter,
        ) -> list[PlaylistMembershipRecord]:
            try:
                return sync_single_library_playlist_tracks(
                    playlist=playlist,
                    adapter=adapter,
                    playlist_store=self,
                )
            except YouTubeMusicAuthenticationError:
                self.clear_playlist_sync_failure(playlist_id=playlist_id)
                raise

        return self._run_youtube_music_sync(
            account_id=playlist.account_id,
            run_sync=run_single_playlist_sync,
            after_success=self.generate_streaming_relationship_suggestions,
        )

    def sync_youtube_music_account(
        self,
        *,
        account_id: int,
    ) -> list[PlaylistMembershipRecord]:
        return self.sync_youtube_music_playlist_tracks(account_id=account_id)

    def generate_streaming_relationship_suggestions(
        self,
    ) -> "StreamingRelationshipSuggestionGenerationResult":
        from app.relationships.suggestions import (
            StreamingRelationshipSuggestionGenerator,
        )

        return StreamingRelationshipSuggestionGenerator(engine=self._engine).generate()

    def _run_youtube_music_sync(
        self,
        *,
        account_id: int,
        run_sync: Callable[[YouTubeMusicAdapter], list[Any]],
        after_success: Callable[[], object] | None = None,
    ) -> list[Any]:
        account = self.get_account(account_id)
        try:
            adapter = YouTubeMusicAdapter.from_browser_auth(
                account.browser_headers,
            )
            synced = run_sync(adapter)
        except (YTMusicError, YouTubeMusicAuthenticationError) as exc:
            self.mark_account_auth_error(account_id=account_id, error=exc)
            return []

        self.clear_account_auth_error(account_id=account_id)
        if after_success is not None:
            after_success()
        return synced


def _format_auth_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "Authentication with YouTube Music failed."
    return f"YouTube Music authentication failed: {message}"
