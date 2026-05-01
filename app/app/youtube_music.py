from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ytmusicapi import OAuthCredentials, YTMusic, setup_oauth


JsonMapping = dict[str, Any]


@dataclass(frozen=True, slots=True)
class YouTubeMusicOAuthCredentials:
    client_id: str
    client_secret: str

    def to_ytmusicapi(self) -> OAuthCredentials:
        return OAuthCredentials(
            client_id=self.client_id,
            client_secret=self.client_secret,
        )


@dataclass(frozen=True, slots=True)
class YouTubeMusicPlaylist:
    provider_playlist_id: str
    title: str


@dataclass(frozen=True, slots=True)
class YouTubeMusicTrack:
    provider_track_id: str
    title: str
    artist: str
    album: str | None
    year: int | None
    isrc: str | None
    duration_ms: int | None


class YouTubeMusicAdapter:
    def __init__(self, client: YTMusic) -> None:
        self._client = client

    @classmethod
    def from_browser_auth(
        cls,
        auth: str | JsonMapping,
        *,
        user: str | None = None,
        language: str = "en",
        location: str = "",
    ) -> YouTubeMusicAdapter:
        return cls(
            YTMusic(
                auth=auth,
                user=user,
                language=language,
                location=location,
            )
        )

    @classmethod
    def from_oauth_token(
        cls,
        oauth_token: str | JsonMapping,
        *,
        credentials: YouTubeMusicOAuthCredentials,
        user: str | None = None,
        language: str = "en",
        location: str = "",
    ) -> YouTubeMusicAdapter:
        return cls(
            YTMusic(
                auth=oauth_token,
                oauth_credentials=credentials.to_ytmusicapi(),
                user=user,
                language=language,
                location=location,
            )
        )

    @staticmethod
    def setup_oauth(
        credentials: YouTubeMusicOAuthCredentials,
        *,
        filepath: str | Path | None = None,
        open_browser: bool = False,
    ) -> JsonMapping:
        token = setup_oauth(
            credentials.client_id,
            credentials.client_secret,
            filepath=None if filepath is None else str(filepath),
            open_browser=open_browser,
        )
        return dict(token.as_dict())

    def get_library_playlists(self, *, limit: int | None = None) -> list[JsonMapping]:
        return self._client.get_library_playlists(limit=limit)

    def list_library_playlists(
        self,
        *,
        limit: int | None = None,
    ) -> list[YouTubeMusicPlaylist]:
        playlists: list[YouTubeMusicPlaylist] = []

        for playlist in self.get_library_playlists(limit=limit):
            playlist_id = playlist.get("playlistId")
            title = playlist.get("title")
            if not isinstance(playlist_id, str) or not playlist_id:
                continue
            if not isinstance(title, str) or not title:
                continue

            playlists.append(
                YouTubeMusicPlaylist(
                    provider_playlist_id=playlist_id,
                    title=title,
                )
            )

        return playlists

    def list_playlist_tracks(
        self,
        playlist_id: str,
        *,
        limit: int | None = 100,
    ) -> list[YouTubeMusicTrack]:
        playlist = self.get_playlist(playlist_id, limit=limit)
        raw_tracks = playlist.get("tracks")
        if not isinstance(raw_tracks, list):
            return []

        tracks: list[YouTubeMusicTrack] = []
        for track in raw_tracks:
            if not isinstance(track, dict):
                continue

            provider_track_id = track.get("videoId")
            title = track.get("title")
            artist = _normalize_artist(track)

            if not isinstance(provider_track_id, str) or not provider_track_id:
                continue
            if not isinstance(title, str) or not title:
                continue
            if not artist:
                continue

            album = _normalize_album(track)
            year = track.get("year")
            duration_seconds = track.get("duration_seconds")
            isrc = _extract_isrc(track)
            if isrc is None:
                isrc = _extract_isrc(self.get_song(provider_track_id))

            tracks.append(
                YouTubeMusicTrack(
                    provider_track_id=provider_track_id,
                    title=title,
                    artist=artist,
                    album=album,
                    year=year if isinstance(year, int) else None,
                    isrc=isrc,
                    duration_ms=(
                        duration_seconds * 1000
                        if isinstance(duration_seconds, int)
                        else None
                    ),
                )
            )

        return tracks

    def get_playlist(
        self,
        playlist_id: str,
        *,
        limit: int | None = 100,
        related: bool = False,
        suggestions_limit: int = 0,
    ) -> JsonMapping:
        return self._client.get_playlist(
            playlistId=playlist_id,
            limit=limit,
            related=related,
            suggestions_limit=suggestions_limit,
        )

    def get_song(
        self,
        video_id: str,
        *,
        signature_timestamp: int | None = None,
    ) -> JsonMapping:
        return self._client.get_song(
            videoId=video_id,
            signatureTimestamp=signature_timestamp,
        )

    def get_watch_playlist(
        self,
        *,
        video_id: str | None = None,
        playlist_id: str | None = None,
        limit: int = 25,
        radio: bool = False,
        shuffle: bool = False,
    ) -> JsonMapping:
        return self._client.get_watch_playlist(
            videoId=video_id,
            playlistId=playlist_id,
            limit=limit,
            radio=radio,
            shuffle=shuffle,
        )


def sync_library_playlists(
    *,
    account_id: int,
    adapter: YouTubeMusicAdapter,
    playlist_store: Any,
    synced_at: datetime | None = None,
) -> list[Any]:
    playlists = adapter.list_library_playlists()
    return playlist_store.upsert_playlists(
        account_id=account_id,
        playlists=playlists,
        synced_at=synced_at or datetime.now(UTC),
    )


def sync_library_playlist_tracks(
    *,
    account_id: int,
    adapter: YouTubeMusicAdapter,
    playlist_store: Any,
    synced_at: datetime | None = None,
) -> list[Any]:
    sync_timestamp = synced_at or datetime.now(UTC)
    playlists = adapter.list_library_playlists()
    stored_playlists = playlist_store.upsert_playlists(
        account_id=account_id,
        playlists=playlists,
        synced_at=sync_timestamp,
    )

    synced_memberships: list[Any] = []
    for playlist in stored_playlists:
        synced_memberships.extend(
            playlist_store.replace_playlist_membership(
                playlist_id=playlist.id,
                tracks=adapter.list_playlist_tracks(playlist.provider_playlist_id),
            )
        )

    return synced_memberships


def _normalize_artist(track: JsonMapping) -> str | None:
    artists = track.get("artists")
    if isinstance(artists, list):
        names = [
            artist_name
            for artist in artists
            if isinstance(artist, dict)
            for artist_name in [artist.get("name") or artist.get("title")]
            if isinstance(artist_name, str) and artist_name
        ]
        if names:
            return ", ".join(names)

    artist = track.get("artist")
    if isinstance(artist, str) and artist:
        return artist

    return None


def _normalize_album(track: JsonMapping) -> str | None:
    album = track.get("album")
    if isinstance(album, str) and album:
        return album

    if isinstance(album, dict):
        title = album.get("name") or album.get("title")
        if isinstance(title, str) and title:
            return title

    return None


def _extract_isrc(value: object) -> str | None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if key.lower() in {"isrc", "internationalstandardrecordingcode"}:
                if isinstance(nested_value, str) and nested_value:
                    return nested_value
            extracted = _extract_isrc(nested_value)
            if extracted is not None:
                return extracted

    if isinstance(value, list):
        for item in value:
            extracted = _extract_isrc(item)
            if extracted is not None:
                return extracted

    return None
