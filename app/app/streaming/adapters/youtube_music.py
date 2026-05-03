from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ytmusicapi import YTMusic

from app.streaming.adapters.base import StreamingAdapter


JsonMapping = dict[str, Any]
logger = logging.getLogger(__name__)


class MalformedPlaylistPayloadError(RuntimeError):
    """Raised when YouTube Music returns an unparseable playlist payload."""


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


@dataclass(frozen=True, slots=True)
class YouTubeMusicTrackMetadata:
    title: str | None
    artist: str | None
    album: str | None
    year: int | None
    album_art_url: str | None


class YouTubeMusicAdapter(StreamingAdapter):
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
        if not isinstance(playlist, dict):
            raise MalformedPlaylistPayloadError(
                f"YouTube Music playlist {playlist_id} payload is not an object"
            )

        raw_tracks = playlist.get("tracks")
        if not isinstance(raw_tracks, list):
            raise MalformedPlaylistPayloadError(
                f"YouTube Music playlist {playlist_id} payload has invalid tracks"
            )

        tracks: list[YouTubeMusicTrack] = []
        missing_isrc_track_ids: set[str] = set()
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
                missing_isrc_track_ids.add(provider_track_id)

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

        if not missing_isrc_track_ids:
            return tracks

        isrc_by_track_id = self._lookup_missing_isrcs(missing_isrc_track_ids)
        return [
            track
            if track.isrc is not None
            else YouTubeMusicTrack(
                provider_track_id=track.provider_track_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                year=track.year,
                isrc=isrc_by_track_id.get(track.provider_track_id),
                duration_ms=track.duration_ms,
            )
            for track in tracks
        ]

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

    def get_track_metadata(self, provider_track_id: str) -> YouTubeMusicTrackMetadata:
        song = self.get_song(provider_track_id)
        watch_playlist = self.get_watch_playlist(video_id=provider_track_id, limit=1)
        watch_track = _extract_watch_track(watch_playlist)

        return YouTubeMusicTrackMetadata(
            title=_coalesce_str(
                _mapping_str(watch_track, "title"),
                _nested_str(song, "videoDetails", "title"),
            ),
            artist=_coalesce_str(
                _normalize_artist(watch_track) if watch_track is not None else None,
                _nested_str(song, "videoDetails", "author"),
            ),
            album=_coalesce_str(
                _normalize_album(watch_track) if watch_track is not None else None,
                _extract_album(song),
            ),
            year=_coalesce_int(
                _mapping_int(watch_track, "year"),
                _extract_year(song),
            ),
            album_art_url=_extract_best_thumbnail_url(watch_track)
            or _extract_best_thumbnail_url(song)
            or _extract_best_thumbnail_url(watch_playlist),
        )

    def _lookup_missing_isrcs(
        self,
        provider_track_ids: set[str],
    ) -> dict[str, str | None]:
        isrc_by_track_id: dict[str, str | None] = {}
        for provider_track_id in provider_track_ids:
            try:
                isrc_by_track_id[provider_track_id] = _extract_isrc(
                    self.get_song(provider_track_id)
                )
            except Exception:
                logger.exception(
                    "Skipping YouTube Music ISRC backfill for track %s after lookup failed",
                    provider_track_id,
                )

        return isrc_by_track_id


def sync_library_playlists(
    *,
    account_id: int,
    adapter: StreamingAdapter,
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
    adapter: StreamingAdapter,
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
    selected_playlists = [
        playlist
        for playlist in stored_playlists
        if getattr(playlist, "selected_for_sync", False)
    ]

    for playlist in selected_playlists:
        try:
            tracks = adapter.list_playlist_tracks(playlist.provider_playlist_id)
            synced_memberships.extend(
                playlist_store.replace_playlist_membership(
                    playlist_id=playlist.id,
                    tracks=tracks,
                )
            )
            _clear_playlist_sync_failure(playlist_store, playlist_id=playlist.id)
        except MalformedPlaylistPayloadError as exc:
            _mark_playlist_sync_failure(
                playlist_store,
                playlist_id=playlist.id,
                error=str(exc),
                failed_at=datetime.now(UTC),
            )
            logger.warning(
                "Skipping YouTube Music playlist %s because its track payload is malformed",
                playlist.provider_playlist_id,
                exc_info=True,
            )
            continue
        except Exception as exc:
            _mark_playlist_sync_failure(
                playlist_store,
                playlist_id=playlist.id,
                error=_format_sync_failure(exc),
                failed_at=datetime.now(UTC),
            )
            logger.exception(
                "Skipping YouTube Music playlist %s after sync failed",
                playlist.provider_playlist_id,
            )
            continue

    return synced_memberships


def sync_single_library_playlist_tracks(
    *,
    playlist: Any,
    adapter: StreamingAdapter,
    playlist_store: Any,
) -> list[Any]:
    try:
        tracks = adapter.list_playlist_tracks(playlist.provider_playlist_id)
        synced_memberships = playlist_store.replace_playlist_membership(
            playlist_id=playlist.id,
            tracks=tracks,
        )
        _clear_playlist_sync_failure(playlist_store, playlist_id=playlist.id)
        return synced_memberships
    except MalformedPlaylistPayloadError as exc:
        _mark_playlist_sync_failure(
            playlist_store,
            playlist_id=playlist.id,
            error=str(exc),
            failed_at=datetime.now(UTC),
        )
        logger.warning(
            "Skipping YouTube Music playlist %s because its track payload is malformed",
            playlist.provider_playlist_id,
            exc_info=True,
        )
        return []
    except Exception as exc:
        _mark_playlist_sync_failure(
            playlist_store,
            playlist_id=playlist.id,
            error=_format_sync_failure(exc),
            failed_at=datetime.now(UTC),
        )
        logger.exception(
            "Skipping YouTube Music playlist %s after sync failed",
            playlist.provider_playlist_id,
        )
        return []


def _mark_playlist_sync_failure(
    playlist_store: Any,
    *,
    playlist_id: int,
    error: str,
    failed_at: datetime,
) -> None:
    marker = getattr(playlist_store, "mark_playlist_sync_failure", None)
    if marker is not None:
        marker(playlist_id=playlist_id, error=error, failed_at=failed_at)


def _clear_playlist_sync_failure(playlist_store: Any, *, playlist_id: int) -> None:
    clearer = getattr(playlist_store, "clear_playlist_sync_failure", None)
    if clearer is not None:
        clearer(playlist_id=playlist_id)


def _format_sync_failure(exc: Exception) -> str:
    message = str(exc)
    if message:
        return message
    return exc.__class__.__name__


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


def _extract_watch_track(value: JsonMapping) -> JsonMapping | None:
    tracks = value.get("tracks")
    if not isinstance(tracks, list):
        return None

    for track in tracks:
        if isinstance(track, dict):
            return track

    return None


def _mapping_str(value: JsonMapping | None, key: str) -> str | None:
    if value is None:
        return None

    candidate = value.get(key)
    if isinstance(candidate, str) and candidate:
        return candidate

    return None


def _mapping_int(value: JsonMapping | None, key: str) -> int | None:
    if value is None:
        return None

    candidate = value.get(key)
    if isinstance(candidate, int):
        return candidate

    return None


def _nested_str(value: object, *path: str) -> str | None:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)

    if isinstance(current, str) and current:
        return current

    return None


def _coalesce_str(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _coalesce_int(*values: int | None) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def _extract_album(value: object) -> str | None:
    if isinstance(value, dict):
        album = value.get("album")
        if isinstance(album, str) and album:
            return album
        if isinstance(album, dict):
            title = album.get("name") or album.get("title")
            if isinstance(title, str) and title:
                return title
        for nested in value.values():
            extracted = _extract_album(nested)
            if extracted is not None:
                return extracted

    if isinstance(value, list):
        for item in value:
            extracted = _extract_album(item)
            if extracted is not None:
                return extracted

    return None


def _extract_year(value: object) -> int | None:
    if isinstance(value, dict):
        year = value.get("year")
        if isinstance(year, int):
            return year
        for nested in value.values():
            extracted = _extract_year(nested)
            if extracted is not None:
                return extracted

    if isinstance(value, list):
        for item in value:
            extracted = _extract_year(item)
            if extracted is not None:
                return extracted

    return None


def _extract_best_thumbnail_url(value: object) -> str | None:
    best_thumbnail = _extract_best_thumbnail(value)
    if best_thumbnail is None:
        return None
    return best_thumbnail.get("url")


def _extract_best_thumbnail(value: object) -> dict[str, object] | None:
    candidates: list[dict[str, object]] = []

    if isinstance(value, dict):
        thumbnails = value.get("thumbnails")
        if isinstance(thumbnails, list):
            for thumbnail in thumbnails:
                if (
                    isinstance(thumbnail, dict)
                    and isinstance(thumbnail.get("url"), str)
                    and thumbnail["url"]
                ):
                    candidates.append(thumbnail)

        for nested in value.values():
            nested_best = _extract_best_thumbnail(nested)
            if nested_best is not None:
                candidates.append(nested_best)

    if isinstance(value, list):
        for item in value:
            nested_best = _extract_best_thumbnail(item)
            if nested_best is not None:
                candidates.append(nested_best)

    if not candidates:
        return None

    return max(candidates, key=_thumbnail_size)


def _thumbnail_size(thumbnail: dict[str, object]) -> int:
    width = thumbnail.get("width")
    height = thumbnail.get("height")
    if isinstance(width, int) and isinstance(height, int):
        return width * height
    return 0


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
