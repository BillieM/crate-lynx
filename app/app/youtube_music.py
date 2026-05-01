from __future__ import annotations

from dataclasses import dataclass
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
