from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.streaming.adapters.youtube_music import (
        YouTubeMusicPlaylist,
        YouTubeMusicTrack,
    )


class StreamingAdapter(Protocol):
    def list_library_playlists(
        self,
        *,
        limit: int | None = None,
    ) -> list[YouTubeMusicPlaylist]: ...

    def list_playlist_tracks(
        self,
        playlist_id: str,
        *,
        limit: int | None = 100,
    ) -> list[YouTubeMusicTrack]: ...
