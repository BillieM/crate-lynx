from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    column,
    create_engine,
    delete,
    func,
    insert,
    select,
    table,
    update,
)
from ytmusicapi.exceptions import YTMusicError

from app.streaming.adapters.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicPlaylist,
    YouTubeMusicTrack,
    sync_library_playlists,
    sync_library_playlist_tracks,
)
from app.streaming.crypto import decrypt_token, encrypt_token
from app.streaming.models import (
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

PENDING_LINK_STATUS = "pending"
final_links_view = table(
    "final_links",
    column("id"),
    column("local_track_id"),
    column("streaming_track_id"),
)
suggested_links_view = table(
    "suggested_links",
    column("id"),
    column("local_track_id"),
    column("streaming_track_id"),
    column("status"),
)


class StreamingAccountStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)

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
        synced_at: datetime | None = None,
    ) -> list[StreamingPlaylistRecord]:
        playlist_rows: list[StreamingPlaylistRecord] = []
        sync_timestamp = synced_at or datetime.now(UTC)

        with self._engine.begin() as connection:
            for playlist in playlists:
                existing = (
                    connection.execute(
                        select(
                            streaming_playlists_table.c.id,
                            streaming_playlists_table.c.account_id,
                            streaming_playlists_table.c.provider_playlist_id,
                            streaming_playlists_table.c.title,
                            streaming_playlists_table.c.selected_for_sync,
                            streaming_playlists_table.c.synced_at,
                            streaming_playlists_table.c.last_sync_error,
                            streaming_playlists_table.c.last_sync_error_at,
                        ).where(
                            streaming_playlists_table.c.account_id == account_id,
                            streaming_playlists_table.c.provider_playlist_id
                            == playlist.provider_playlist_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )

                if existing is None:
                    result = connection.execute(
                        insert(streaming_playlists_table).values(
                            account_id=account_id,
                            provider_playlist_id=playlist.provider_playlist_id,
                            title=playlist.title,
                            selected_for_sync=False,
                            synced_at=sync_timestamp,
                            last_sync_error=None,
                            last_sync_error_at=None,
                        )
                    )
                    playlist_id = result.inserted_primary_key[0]
                    if not isinstance(playlist_id, int):
                        raise ValueError("Failed to persist streaming playlist")
                    playlist_rows.append(
                        StreamingPlaylistRecord(
                            id=playlist_id,
                            account_id=account_id,
                            provider_playlist_id=playlist.provider_playlist_id,
                            title=playlist.title,
                            selected_for_sync=False,
                            synced_at=sync_timestamp,
                            last_sync_error=None,
                            last_sync_error_at=None,
                        )
                    )
                    continue

                connection.execute(
                    update(streaming_playlists_table)
                    .where(streaming_playlists_table.c.id == existing["id"])
                    .values(
                        title=playlist.title,
                        synced_at=sync_timestamp,
                    )
                )
                playlist_rows.append(
                    StreamingPlaylistRecord(
                        id=existing["id"],
                        account_id=existing["account_id"],
                        provider_playlist_id=existing["provider_playlist_id"],
                        title=playlist.title,
                        selected_for_sync=existing["selected_for_sync"],
                        synced_at=sync_timestamp,
                        last_sync_error=existing["last_sync_error"],
                        last_sync_error_at=existing["last_sync_error_at"],
                    )
                )

        return playlist_rows

    def list_playlists(self) -> list[StreamingPlaylistSummary]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    streaming_playlists_table.c.id,
                    streaming_playlists_table.c.account_id,
                    streaming_playlists_table.c.provider_playlist_id,
                    streaming_playlists_table.c.title,
                    streaming_playlists_table.c.selected_for_sync,
                    streaming_playlists_table.c.synced_at,
                    streaming_playlists_table.c.last_sync_error,
                    streaming_playlists_table.c.last_sync_error_at,
                    func.count(playlist_membership_table.c.id).label("track_count"),
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
                    streaming_playlists_table.c.selected_for_sync,
                    streaming_playlists_table.c.synced_at,
                    streaming_playlists_table.c.last_sync_error,
                    streaming_playlists_table.c.last_sync_error_at,
                )
                .order_by(streaming_playlists_table.c.id.asc())
            ).mappings()

            return [
                StreamingPlaylistSummary(
                    id=row["id"],
                    account_id=row["account_id"],
                    provider_playlist_id=row["provider_playlist_id"],
                    title=row["title"],
                    selected_for_sync=row["selected_for_sync"],
                    track_count=row["track_count"],
                    synced_at=row["synced_at"],
                    last_sync_error=row["last_sync_error"],
                    last_sync_error_at=row["last_sync_error_at"],
                )
                for row in rows
            ]

    def get_playlist_detail(self, playlist_id: int) -> StreamingPlaylistDetail | None:
        playlist = self._get_playlist_summary(playlist_id)
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
            selected_for_sync=playlist.selected_for_sync,
            track_count=playlist.track_count,
            synced_at=playlist.synced_at,
            last_sync_error=playlist.last_sync_error,
            last_sync_error_at=playlist.last_sync_error_at,
            cover_art_url=None,
            linked_count=counts["linked"],
            pending_count=counts["pending"],
            unlinked_count=counts["unlinked"],
        )

    def set_playlist_selected_for_sync(
        self, *, playlist_id: int, selected_for_sync: bool
    ) -> StreamingPlaylistSummary | None:
        with self._engine.begin() as connection:
            result = connection.execute(
                update(streaming_playlists_table)
                .where(streaming_playlists_table.c.id == playlist_id)
                .values(selected_for_sync=selected_for_sync)
            )

        if result.rowcount == 0:
            return None

        return self._get_playlist_summary(playlist_id)

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
        self, playlist_id: int
    ) -> StreamingPlaylistSummary | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        streaming_playlists_table.c.id,
                        streaming_playlists_table.c.account_id,
                        streaming_playlists_table.c.provider_playlist_id,
                        streaming_playlists_table.c.title,
                        streaming_playlists_table.c.selected_for_sync,
                        streaming_playlists_table.c.synced_at,
                        streaming_playlists_table.c.last_sync_error,
                        streaming_playlists_table.c.last_sync_error_at,
                        func.count(playlist_membership_table.c.id).label("track_count"),
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
                        streaming_playlists_table.c.selected_for_sync,
                        streaming_playlists_table.c.synced_at,
                        streaming_playlists_table.c.last_sync_error,
                        streaming_playlists_table.c.last_sync_error_at,
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return StreamingPlaylistSummary(
            id=row["id"],
            account_id=row["account_id"],
            provider_playlist_id=row["provider_playlist_id"],
            title=row["title"],
            selected_for_sync=row["selected_for_sync"],
            track_count=row["track_count"],
            synced_at=row["synced_at"],
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
                existing = (
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
                        ).where(
                            streaming_tracks_table.c.provider_track_id
                            == track.provider_track_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )

                if existing is None:
                    result = connection.execute(
                        insert(streaming_tracks_table).values(
                            provider_track_id=track.provider_track_id,
                            title=track.title,
                            artist=track.artist,
                            album=track.album,
                            year=track.year,
                            isrc=track.isrc,
                            duration_ms=track.duration_ms,
                        )
                    )
                    track_id = result.inserted_primary_key[0]
                    if not isinstance(track_id, int):
                        raise ValueError("Failed to persist streaming track")
                    track_rows.append(
                        StreamingTrackRecord(
                            id=track_id,
                            provider_track_id=track.provider_track_id,
                            title=track.title,
                            artist=track.artist,
                            album=track.album,
                            year=track.year,
                            isrc=track.isrc,
                            duration_ms=track.duration_ms,
                        )
                    )
                    continue

                isrc = track.isrc if track.isrc is not None else existing["isrc"]
                connection.execute(
                    update(streaming_tracks_table)
                    .where(streaming_tracks_table.c.id == existing["id"])
                    .values(
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        year=track.year,
                        isrc=isrc,
                        duration_ms=track.duration_ms,
                    )
                )
                track_rows.append(
                    StreamingTrackRecord(
                        id=existing["id"],
                        provider_track_id=track.provider_track_id,
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        year=track.year,
                        isrc=isrc,
                        duration_ms=track.duration_ms,
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
        )

    def sync_youtube_music_account(
        self,
        *,
        account_id: int,
    ) -> list[PlaylistMembershipRecord]:
        return self.sync_youtube_music_playlist_tracks(account_id=account_id)

    def _run_youtube_music_sync(
        self,
        *,
        account_id: int,
        run_sync: Callable[[YouTubeMusicAdapter], list[Any]],
    ) -> list[Any]:
        account = self.get_account(account_id)
        try:
            adapter = YouTubeMusicAdapter.from_browser_auth(
                account.browser_headers,
            )
            synced = run_sync(adapter)
        except YTMusicError as exc:
            self.mark_account_auth_error(account_id=account_id, error=exc)
            return []

        self.clear_account_auth_error(account_id=account_id)
        return synced


def _format_auth_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "Authentication with YouTube Music failed."
    return f"YouTube Music authentication failed: {message}"
