from __future__ import annotations

from types import SimpleNamespace

from app.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicOAuthCredentials,
)


def test_from_browser_auth_builds_client(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeYTMusic:
        def __init__(
            self,
            *,
            auth: str,
            user: str | None,
            language: str,
            location: str,
        ) -> None:
            seen["auth"] = auth
            seen["user"] = user
            seen["language"] = language
            seen["location"] = location

    monkeypatch.setattr("app.youtube_music.YTMusic", FakeYTMusic)

    adapter = YouTubeMusicAdapter.from_browser_auth(
        "browser-auth.json",
        user="user@example.com",
        language="en-GB",
        location="GB",
    )

    assert isinstance(adapter, YouTubeMusicAdapter)
    assert seen == {
        "auth": "browser-auth.json",
        "user": "user@example.com",
        "language": "en-GB",
        "location": "GB",
    }


def test_from_oauth_token_builds_client_with_oauth_credentials(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeOAuthCredentials:
        def __init__(self, client_id: str, client_secret: str) -> None:
            seen["client_id"] = client_id
            seen["client_secret"] = client_secret

    class FakeYTMusic:
        def __init__(
            self,
            *,
            auth: dict[str, str],
            oauth_credentials: object,
            user: str | None,
            language: str,
            location: str,
        ) -> None:
            seen["auth"] = auth
            seen["oauth_credentials"] = oauth_credentials
            seen["user"] = user
            seen["language"] = language
            seen["location"] = location

    monkeypatch.setattr("app.youtube_music.OAuthCredentials", FakeOAuthCredentials)
    monkeypatch.setattr("app.youtube_music.YTMusic", FakeYTMusic)

    adapter = YouTubeMusicAdapter.from_oauth_token(
        {"refresh_token": "token-123"},
        credentials=YouTubeMusicOAuthCredentials(
            client_id="client-id",
            client_secret="client-secret",
        ),
        user="listener@example.com",
        location="US",
    )

    assert isinstance(adapter, YouTubeMusicAdapter)
    assert seen == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "auth": {"refresh_token": "token-123"},
        "oauth_credentials": seen["oauth_credentials"],
        "user": "listener@example.com",
        "language": "en",
        "location": "US",
    }


def test_setup_oauth_returns_serializable_token(monkeypatch, tmp_path) -> None:
    seen: dict[str, object] = {}

    def fake_setup_oauth(
        client_id: str,
        client_secret: str,
        *,
        filepath: str | None,
        open_browser: bool,
    ) -> SimpleNamespace:
        seen["client_id"] = client_id
        seen["client_secret"] = client_secret
        seen["filepath"] = filepath
        seen["open_browser"] = open_browser
        return SimpleNamespace(as_dict=lambda: {"refresh_token": "token-123"})

    monkeypatch.setattr("app.youtube_music.setup_oauth", fake_setup_oauth)

    token = YouTubeMusicAdapter.setup_oauth(
        YouTubeMusicOAuthCredentials(
            client_id="client-id",
            client_secret="client-secret",
        ),
        filepath=tmp_path / "oauth.json",
        open_browser=True,
    )

    assert token == {"refresh_token": "token-123"}
    assert seen == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "filepath": str(tmp_path / "oauth.json"),
        "open_browser": True,
    }


def test_adapter_methods_delegate_to_wrapped_client() -> None:
    seen: dict[str, object] = {}

    class FakeYTMusic:
        def get_library_playlists(
            self, *, limit: int | None
        ) -> list[dict[str, object]]:
            seen["get_library_playlists"] = {"limit": limit}
            return [{"playlistId": "PL1"}]

        def get_playlist(
            self,
            *,
            playlistId: str,
            limit: int | None,
            related: bool,
            suggestions_limit: int,
        ) -> dict[str, object]:
            seen["get_playlist"] = {
                "playlistId": playlistId,
                "limit": limit,
                "related": related,
                "suggestions_limit": suggestions_limit,
            }
            return {"id": playlistId}

        def get_song(
            self,
            *,
            videoId: str,
            signatureTimestamp: int | None,
        ) -> dict[str, object]:
            seen["get_song"] = {
                "videoId": videoId,
                "signatureTimestamp": signatureTimestamp,
            }
            return {"videoId": videoId}

        def get_watch_playlist(
            self,
            *,
            videoId: str | None,
            playlistId: str | None,
            limit: int,
            radio: bool,
            shuffle: bool,
        ) -> dict[str, object]:
            seen["get_watch_playlist"] = {
                "videoId": videoId,
                "playlistId": playlistId,
                "limit": limit,
                "radio": radio,
                "shuffle": shuffle,
            }
            return {"tracks": []}

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.get_library_playlists(limit=50) == [{"playlistId": "PL1"}]
    assert adapter.get_playlist(
        "PL1",
        limit=200,
        related=True,
        suggestions_limit=5,
    ) == {"id": "PL1"}
    assert adapter.get_song("video-1", signature_timestamp=1234) == {
        "videoId": "video-1"
    }
    assert adapter.get_watch_playlist(
        video_id="video-1",
        playlist_id="playlist-1",
        limit=99,
        radio=True,
        shuffle=True,
    ) == {"tracks": []}

    assert seen == {
        "get_library_playlists": {"limit": 50},
        "get_playlist": {
            "playlistId": "PL1",
            "limit": 200,
            "related": True,
            "suggestions_limit": 5,
        },
        "get_song": {
            "videoId": "video-1",
            "signatureTimestamp": 1234,
        },
        "get_watch_playlist": {
            "videoId": "video-1",
            "playlistId": "playlist-1",
            "limit": 99,
            "radio": True,
            "shuffle": True,
        },
    }
