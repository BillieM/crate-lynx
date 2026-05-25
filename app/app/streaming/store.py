from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from ytmusicapi.exceptions import YTMusicError

from app.core.db import create_database_engine
from app.core.tables import streaming_relationships_view, suggested_links_view
from app.local_tracks.store import local_tracks_table
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
    from app.relationships.resolver import StreamingRelationshipResolver
    from app.relationships.suggestions import (
        StreamingRelationshipSuggestionGenerationResult,
    )

PENDING_LINK_STATUS = "pending"


@dataclass(frozen=True, slots=True)
class StreamingTrackLocalSummaryRecord:
    id: int
    file_path: str
    library_root_rel_path: str
    title: str | None
    artist: str | None
    album: str | None


@dataclass(frozen=True, slots=True)
class StreamingTrackLocalLinkRecord:
    final_link_id: int
    local_track_id: int
    source_streaming_track_id: int
    resolution_source: str
    approved_at: datetime
    local_track: StreamingTrackLocalSummaryRecord


@dataclass(frozen=True, slots=True)
class StreamingTrackRelationshipPeerRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class StreamingTrackRelationshipRecord:
    id: int
    relationship_type: str
    accepted_at: datetime
    peer_track: StreamingTrackRelationshipPeerRecord


@dataclass(frozen=True, slots=True)
class StreamingTrackPlaylistAppearanceRecord:
    playlist_id: int
    account_id: int
    provider_playlist_id: str
    title: str
    sync_mode: str
    position: int


@dataclass(frozen=True, slots=True)
class StreamingTrackPendingLocalSuggestionRecord:
    id: int
    local_track_id: int
    match_method: str
    score: float
    status: str
    created_at: datetime
    local_track: StreamingTrackLocalSummaryRecord


@dataclass(frozen=True, slots=True)
class StreamingTrackDetailRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None
    resolved_local_link: StreamingTrackLocalLinkRecord | None
    equivalent_tracks: list[StreamingTrackRelationshipPeerRecord]
    relationships: list[StreamingTrackRelationshipRecord]
    playlist_appearances: list[StreamingTrackPlaylistAppearanceRecord]
    pending_local_suggestions: list[StreamingTrackPendingLocalSuggestionRecord]


@dataclass(frozen=True, slots=True)
class StreamingTrackSearchResultRecord:
    id: int
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None
    link_status: str
    final_link_id: int | None
    local_track_id: int | None


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

            return [_streaming_account_record(row) for row in rows]

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

        return _streaming_account_record(row)

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

                playlist_rows.append(_streaming_playlist_record(row))

        return playlist_rows

    def list_playlists(
        self, *, sync_mode: str | None = None
    ) -> list[StreamingPlaylistSummary]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                _playlist_summary_query(sync_mode=sync_mode)
            ).mappings()

            return [_streaming_playlist_summary(row) for row in rows]

    def get_playlist_detail(
        self, playlist_id: int, *, sync_mode: str | None = None
    ) -> StreamingPlaylistDetail | None:
        playlist = self.get_playlist_summary(playlist_id, sync_mode=sync_mode)
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

    def get_playlist_summary(
        self, playlist_id: int, *, sync_mode: str | None = None
    ) -> StreamingPlaylistSummary | None:
        return self._get_playlist_summary(playlist_id, sync_mode=sync_mode)

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

    def get_track_detail(
        self,
        streaming_track_id: int,
    ) -> StreamingTrackDetailRecord | None:
        track_query = select(
            streaming_tracks_table.c.id,
            streaming_tracks_table.c.provider_track_id,
            streaming_tracks_table.c.title,
            streaming_tracks_table.c.artist,
            streaming_tracks_table.c.album,
            streaming_tracks_table.c.year,
            streaming_tracks_table.c.isrc,
            streaming_tracks_table.c.duration_ms,
        ).where(streaming_tracks_table.c.id == streaming_track_id)

        with self._engine.connect() as connection:
            track = connection.execute(track_query).mappings().one_or_none()
            if track is None:
                return None

            from app.relationships.resolver import StreamingRelationshipResolver

            resolver = StreamingRelationshipResolver(connection)
            resolved_link = resolver.resolve(streaming_track_id)
            local_link = (
                _resolved_local_link_record(connection, resolved_link)
                if resolved_link is not None
                else None
            )
            equivalent_track_ids = [
                track_id
                for track_id in resolver.equivalent_group_track_ids(streaming_track_id)
                if track_id != streaming_track_id
            ]
            equivalent_tracks = (
                _streaming_track_peers(connection, equivalent_track_ids)
                if equivalent_track_ids
                else []
            )
            relationships = _streaming_track_relationships(
                connection,
                streaming_track_id,
            )
            playlist_appearances = _streaming_track_playlist_appearances(
                connection,
                streaming_track_id,
            )
            pending_suggestions = _streaming_track_pending_local_suggestions(
                connection,
                streaming_track_id,
            )

        return StreamingTrackDetailRecord(
            id=track["id"],
            provider_track_id=track["provider_track_id"],
            title=track["title"],
            artist=track["artist"],
            album=track["album"],
            year=track["year"],
            isrc=track["isrc"],
            duration_ms=track["duration_ms"],
            resolved_local_link=local_link,
            equivalent_tracks=equivalent_tracks,
            relationships=relationships,
            playlist_appearances=playlist_appearances,
            pending_local_suggestions=pending_suggestions,
        )

    def search_tracks(
        self,
        *,
        query: str = "",
        limit: int = 20,
    ) -> list[StreamingTrackSearchResultRecord]:
        search_query = (
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.provider_track_id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.year,
                streaming_tracks_table.c.isrc,
                streaming_tracks_table.c.duration_ms,
            )
            .order_by(streaming_tracks_table.c.id.asc())
            .limit(limit)
        )
        normalized_query = query.strip()
        if normalized_query:
            like_query = f"%{normalized_query}%"
            clauses = [
                streaming_tracks_table.c.provider_track_id.ilike(like_query),
                streaming_tracks_table.c.title.ilike(like_query),
                streaming_tracks_table.c.artist.ilike(like_query),
                streaming_tracks_table.c.album.ilike(like_query),
                streaming_tracks_table.c.isrc.ilike(like_query),
            ]
            if normalized_query.isdecimal():
                clauses.append(streaming_tracks_table.c.id == int(normalized_query))
            search_query = search_query.where(or_(*clauses))

        with self._engine.connect() as connection:
            from app.relationships.resolver import StreamingRelationshipResolver

            resolver = StreamingRelationshipResolver(connection)
            rows = connection.execute(search_query).mappings().all()
            row_ids = tuple(int(row["id"]) for row in rows)
            pending_track_ids = (
                set(
                    connection.execute(
                        select(suggested_links_view.c.streaming_track_id).where(
                            suggested_links_view.c.status == PENDING_LINK_STATUS,
                            suggested_links_view.c.streaming_track_id.in_(row_ids),
                        )
                    ).scalars()
                )
                if row_ids
                else set()
            )
            results: list[StreamingTrackSearchResultRecord] = []
            for row in rows:
                resolved_link = resolver.resolve(int(row["id"]))
                link_status = "unlinked"
                if resolved_link is not None:
                    link_status = "linked"
                elif int(row["id"]) in pending_track_ids:
                    link_status = "pending"
                results.append(
                    StreamingTrackSearchResultRecord(
                        id=row["id"],
                        provider_track_id=row["provider_track_id"],
                        title=row["title"],
                        artist=row["artist"],
                        album=row["album"],
                        year=row["year"],
                        isrc=row["isrc"],
                        duration_ms=row["duration_ms"],
                        link_status=link_status,
                        final_link_id=(
                            resolved_link.final_link_id
                            if resolved_link is not None
                            else None
                        ),
                        local_track_id=(
                            resolved_link.local_track_id
                            if resolved_link is not None
                            else None
                        ),
                    )
                )

        return results

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
            from app.relationships.resolver import StreamingRelationshipResolver

            resolver = StreamingRelationshipResolver(connection)
            rows = connection.execute(query).mappings()
            return [self._playlist_track_from_row(row, resolver) for row in rows]

    def _get_playlist_summary(
        self, playlist_id: int, *, sync_mode: str | None = None
    ) -> StreamingPlaylistSummary | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    _playlist_summary_query(
                        playlist_id=playlist_id,
                        sync_mode=sync_mode,
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return _streaming_playlist_summary(row)

    def _playlist_track_from_row(
        self, row: Mapping[str, Any], resolver: StreamingRelationshipResolver
    ) -> StreamingPlaylistTrack:
        resolved_link = resolver.resolve(int(row["id"]))
        if resolved_link is not None:
            status = "linked"
            final_link_id = resolved_link.final_link_id
            local_track_id = resolved_link.local_track_id
            proposal_id = None
        elif row["proposal_id"] is not None:
            status = "pending"
            final_link_id = None
            local_track_id = row["proposal_local_track_id"]
            proposal_id = row["proposal_id"]
        else:
            status = "unlinked"
            final_link_id = None
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
            final_link_id=final_link_id,
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
        after_success: Callable[[], object] | None = None,
    ) -> list[PlaylistMembershipRecord]:
        return self._run_youtube_music_sync(
            account_id=account_id,
            run_sync=lambda adapter: sync_library_playlist_tracks(
                account_id=account_id,
                adapter=adapter,
                playlist_store=self,
            ),
            after_success=_compose_after_success(
                self.generate_streaming_relationship_suggestions,
                after_success,
            ),
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
        after_success: Callable[[], object] | None = None,
    ) -> list[PlaylistMembershipRecord]:
        return self.sync_youtube_music_playlist_tracks(
            account_id=account_id,
            after_success=after_success,
        )

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


def _compose_after_success(
    *callbacks: Callable[[], object] | None,
) -> Callable[[], None]:
    def run_callbacks() -> None:
        for callback in callbacks:
            if callback is not None:
                callback()

    return run_callbacks


def _streaming_account_record(row) -> StreamingAccountRecord:
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


def _streaming_playlist_record(row) -> StreamingPlaylistRecord:
    return StreamingPlaylistRecord(
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


def _streaming_playlist_summary(row) -> StreamingPlaylistSummary:
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


def _playlist_summary_query(
    *,
    playlist_id: int | None = None,
    sync_mode: str | None = None,
):
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
            func.count(playlist_membership_table.c.id).label("imported_track_count"),
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
    if playlist_id is not None:
        query = query.where(streaming_playlists_table.c.id == playlist_id)
    if sync_mode is not None:
        query = query.where(streaming_playlists_table.c.sync_mode == sync_mode)

    return query


def _resolved_local_link_record(
    connection,
    resolved_link,
) -> StreamingTrackLocalLinkRecord | None:
    local_track = _local_track_summary(connection, resolved_link.local_track_id)
    if local_track is None:
        return None

    return StreamingTrackLocalLinkRecord(
        final_link_id=resolved_link.final_link_id,
        local_track_id=resolved_link.local_track_id,
        source_streaming_track_id=resolved_link.source_streaming_track_id,
        resolution_source=resolved_link.resolution_source,
        approved_at=_final_link_approved_at(connection, resolved_link.final_link_id),
        local_track=local_track,
    )


def _final_link_approved_at(connection, final_link_id: int) -> datetime:
    from app.core.tables import final_links_view

    return connection.execute(
        select(final_links_view.c.approved_at).where(
            final_links_view.c.id == final_link_id
        )
    ).scalar_one()


def _local_track_summary(
    connection,
    local_track_id: int,
) -> StreamingTrackLocalSummaryRecord | None:
    beets_items_table = _beets_items_table()
    row = (
        connection.execute(
            select(
                local_tracks_table.c.id,
                local_tracks_table.c.file_path,
                local_tracks_table.c.library_root_rel_path,
                beets_items_table.c.title,
                beets_items_table.c.artist,
                beets_items_table.c.album,
            )
            .select_from(
                local_tracks_table.outerjoin(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
            )
            .where(local_tracks_table.c.id == local_track_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None

    return StreamingTrackLocalSummaryRecord(
        id=row["id"],
        file_path=row["file_path"],
        library_root_rel_path=row["library_root_rel_path"],
        title=row["title"],
        artist=row["artist"],
        album=row["album"],
    )


def _streaming_track_peers(
    connection,
    streaming_track_ids: list[int],
) -> list[StreamingTrackRelationshipPeerRecord]:
    rows = (
        connection.execute(
            select(
                streaming_tracks_table.c.id,
                streaming_tracks_table.c.provider_track_id,
                streaming_tracks_table.c.title,
                streaming_tracks_table.c.artist,
                streaming_tracks_table.c.album,
                streaming_tracks_table.c.year,
                streaming_tracks_table.c.isrc,
                streaming_tracks_table.c.duration_ms,
            )
            .where(streaming_tracks_table.c.id.in_(streaming_track_ids))
            .order_by(streaming_tracks_table.c.id.asc())
        )
        .mappings()
        .all()
    )
    return [_streaming_track_peer(row) for row in rows]


def _streaming_track_relationships(
    connection,
    streaming_track_id: int,
) -> list[StreamingTrackRelationshipRecord]:
    peer_track = streaming_tracks_table.alias("peer_track")
    rows = (
        connection.execute(
            select(
                streaming_relationships_view.c.id,
                streaming_relationships_view.c.relationship_type,
                streaming_relationships_view.c.accepted_at,
                peer_track.c.id.label("peer_id"),
                peer_track.c.provider_track_id.label("peer_provider_track_id"),
                peer_track.c.title.label("peer_title"),
                peer_track.c.artist.label("peer_artist"),
                peer_track.c.album.label("peer_album"),
                peer_track.c.year.label("peer_year"),
                peer_track.c.isrc.label("peer_isrc"),
                peer_track.c.duration_ms.label("peer_duration_ms"),
            )
            .select_from(
                streaming_relationships_view.join(
                    peer_track,
                    peer_track.c.id
                    == (
                        streaming_relationships_view.c.higher_track_id
                        + streaming_relationships_view.c.lower_track_id
                        - streaming_track_id
                    ),
                )
            )
            .where(
                or_(
                    streaming_relationships_view.c.lower_track_id == streaming_track_id,
                    streaming_relationships_view.c.higher_track_id
                    == streaming_track_id,
                )
            )
            .order_by(streaming_relationships_view.c.id.asc())
        )
        .mappings()
        .all()
    )
    return [
        StreamingTrackRelationshipRecord(
            id=row["id"],
            relationship_type=row["relationship_type"],
            accepted_at=row["accepted_at"],
            peer_track=StreamingTrackRelationshipPeerRecord(
                id=row["peer_id"],
                provider_track_id=row["peer_provider_track_id"],
                title=row["peer_title"],
                artist=row["peer_artist"],
                album=row["peer_album"],
                year=row["peer_year"],
                isrc=row["peer_isrc"],
                duration_ms=row["peer_duration_ms"],
            ),
        )
        for row in rows
    ]


def _streaming_track_playlist_appearances(
    connection,
    streaming_track_id: int,
) -> list[StreamingTrackPlaylistAppearanceRecord]:
    rows = (
        connection.execute(
            select(
                streaming_playlists_table.c.id.label("playlist_id"),
                streaming_playlists_table.c.account_id,
                streaming_playlists_table.c.provider_playlist_id,
                streaming_playlists_table.c.title,
                streaming_playlists_table.c.sync_mode,
                playlist_membership_table.c.position,
            )
            .select_from(
                playlist_membership_table.join(
                    streaming_playlists_table,
                    streaming_playlists_table.c.id
                    == playlist_membership_table.c.playlist_id,
                )
            )
            .where(playlist_membership_table.c.streaming_track_id == streaming_track_id)
            .order_by(
                streaming_playlists_table.c.title.asc(),
                playlist_membership_table.c.position.asc(),
            )
        )
        .mappings()
        .all()
    )
    return [
        StreamingTrackPlaylistAppearanceRecord(
            playlist_id=row["playlist_id"],
            account_id=row["account_id"],
            provider_playlist_id=row["provider_playlist_id"],
            title=row["title"],
            sync_mode=row["sync_mode"],
            position=row["position"],
        )
        for row in rows
    ]


def _streaming_track_pending_local_suggestions(
    connection,
    streaming_track_id: int,
) -> list[StreamingTrackPendingLocalSuggestionRecord]:
    beets_items_table = _beets_items_table()
    rows = (
        connection.execute(
            select(
                suggested_links_view.c.id,
                suggested_links_view.c.local_track_id,
                suggested_links_view.c.match_method,
                suggested_links_view.c.score,
                suggested_links_view.c.status,
                suggested_links_view.c.created_at,
                local_tracks_table.c.file_path,
                local_tracks_table.c.library_root_rel_path,
                beets_items_table.c.title,
                beets_items_table.c.artist,
                beets_items_table.c.album,
            )
            .select_from(
                suggested_links_view.join(
                    local_tracks_table,
                    local_tracks_table.c.id == suggested_links_view.c.local_track_id,
                ).outerjoin(
                    beets_items_table,
                    beets_items_table.c.beets_id == local_tracks_table.c.beets_id,
                )
            )
            .where(
                suggested_links_view.c.streaming_track_id == streaming_track_id,
                suggested_links_view.c.status == PENDING_LINK_STATUS,
            )
            .order_by(
                suggested_links_view.c.score.desc(),
                suggested_links_view.c.id.asc(),
            )
        )
        .mappings()
        .all()
    )
    return [
        StreamingTrackPendingLocalSuggestionRecord(
            id=row["id"],
            local_track_id=row["local_track_id"],
            match_method=row["match_method"],
            score=row["score"],
            status=row["status"],
            created_at=row["created_at"],
            local_track=StreamingTrackLocalSummaryRecord(
                id=row["local_track_id"],
                file_path=row["file_path"],
                library_root_rel_path=row["library_root_rel_path"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
            ),
        )
        for row in rows
    ]


def _streaming_track_peer(row) -> StreamingTrackRelationshipPeerRecord:
    return StreamingTrackRelationshipPeerRecord(
        id=row["id"],
        provider_track_id=row["provider_track_id"],
        title=row["title"],
        artist=row["artist"],
        album=row["album"],
        year=row["year"],
        isrc=row["isrc"],
        duration_ms=row["duration_ms"],
    )


def _beets_items_table():
    from app.ingestion.beets_mirror import beets_items_table

    return beets_items_table
