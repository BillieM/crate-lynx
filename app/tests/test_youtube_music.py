from __future__ import annotations

from types import SimpleNamespace

from app.youtube_music import (
    YouTubeMusicAdapter,
    YouTubeMusicOAuthCredentials,
    YouTubeMusicPlaylist,
    YouTubeMusicTrack,
    sync_library_playlists,
    sync_library_playlist_tracks,
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


def test_list_library_playlists_normalizes_valid_rows_only() -> None:
    class FakeYTMusic:
        def get_library_playlists(
            self, *, limit: int | None
        ) -> list[dict[str, object]]:
            assert limit is None
            return [
                {"playlistId": "PL1", "title": "Road Trip"},
                {"playlistId": "PL2", "title": "Focus"},
                {"playlistId": "", "title": "Missing Id"},
                {"playlistId": "PL3"},
            ]

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.list_library_playlists() == [
        YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip"),
        YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Focus"),
    ]


def test_list_playlist_tracks_normalizes_valid_rows_only() -> None:
    class FakeYTMusic:
        def get_playlist(
            self,
            *,
            playlistId: str,
            limit: int | None,
            related: bool,
            suggestions_limit: int,
        ) -> dict[str, object]:
            assert playlistId == "PL1"
            assert limit == 100
            assert related is False
            assert suggestions_limit == 0
            return {
                "tracks": [
                    {
                        "videoId": "track-1",
                        "title": "Solar Power",
                        "artists": [{"name": "Lorde"}],
                        "album": {"name": "Solar Power"},
                        "year": 2021,
                        "isrc": "GBUM72105976",
                        "duration_seconds": 193,
                    },
                    {
                        "videoId": "track-2",
                        "title": "Cuff It",
                        "artists": [{"title": "Beyonce"}],
                        "album": "RENAISSANCE",
                    },
                    {
                        "videoId": "track-3",
                        "title": "Missing Artist",
                    },
                    {
                        "title": "Missing Id",
                        "artists": [{"name": "Unknown"}],
                    },
                ]
            }

        def get_song(
            self,
            *,
            videoId: str,
            signatureTimestamp: int | None,
        ) -> dict[str, object]:
            assert signatureTimestamp is None
            if videoId == "track-2":
                return {
                    "microformat": {"microformatDataRenderer": {"isrc": "USQX92200001"}}
                }
            return {"videoDetails": {"videoId": videoId}}

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.list_playlist_tracks("PL1") == [
        YouTubeMusicTrack(
            provider_track_id="track-1",
            title="Solar Power",
            artist="Lorde",
            album="Solar Power",
            year=2021,
            isrc="GBUM72105976",
            duration_ms=193000,
        ),
        YouTubeMusicTrack(
            provider_track_id="track-2",
            title="Cuff It",
            artist="Beyonce",
            album="RENAISSANCE",
            year=None,
            isrc="USQX92200001",
            duration_ms=None,
        ),
    ]


def test_sync_library_playlists_uses_adapter_and_store() -> None:
    seen: dict[str, object] = {}

    class FakePlaylistStore:
        def upsert_playlists(self, *, account_id, playlists, synced_at):
            seen["account_id"] = account_id
            seen["playlists"] = playlists
            seen["synced_at"] = synced_at
            return ["persisted"]

    class FakeAdapter:
        def list_library_playlists(self):
            return [YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip")]

    result = sync_library_playlists(
        account_id=7,
        adapter=FakeAdapter(),  # type: ignore[arg-type]
        playlist_store=FakePlaylistStore(),
    )

    assert result == ["persisted"]
    assert seen["account_id"] == 7
    assert seen["playlists"] == [
        YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip")
    ]
    assert seen["synced_at"] is not None


def test_sync_library_playlist_tracks_uses_adapter_and_store() -> None:
    seen: dict[str, object] = {}

    class FakePlaylistStore:
        def upsert_playlists(self, *, account_id, playlists, synced_at):
            seen["account_id"] = account_id
            seen["playlists"] = playlists
            seen["synced_at"] = synced_at
            return [
                SimpleNamespace(id=11, provider_playlist_id="PL1"),
                SimpleNamespace(id=12, provider_playlist_id="PL2"),
            ]

        def replace_playlist_membership(self, *, playlist_id, tracks):
            memberships = seen.setdefault("memberships", [])
            memberships.append(
                {
                    "playlist_id": playlist_id,
                    "tracks": tracks,
                }
            )
            return [f"membership-{playlist_id}"]

    class FakeAdapter:
        def list_library_playlists(self):
            return [
                YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip"),
                YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Focus"),
            ]

        def list_playlist_tracks(self, playlist_id):
            return [
                YouTubeMusicTrack(
                    provider_track_id=f"{playlist_id}-track-1",
                    title="Track 1",
                    artist="Artist 1",
                    album=None,
                    year=None,
                    isrc=None,
                    duration_ms=None,
                )
            ]

    result = sync_library_playlist_tracks(
        account_id=7,
        adapter=FakeAdapter(),  # type: ignore[arg-type]
        playlist_store=FakePlaylistStore(),
    )

    assert result == ["membership-11", "membership-12"]
    assert seen["account_id"] == 7
    assert seen["playlists"] == [
        YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip"),
        YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Focus"),
    ]
    assert seen["synced_at"] is not None
    assert seen["memberships"] == [
        {
            "playlist_id": 11,
            "tracks": [
                YouTubeMusicTrack(
                    provider_track_id="PL1-track-1",
                    title="Track 1",
                    artist="Artist 1",
                    album=None,
                    year=None,
                    isrc=None,
                    duration_ms=None,
                )
            ],
        },
        {
            "playlist_id": 12,
            "tracks": [
                YouTubeMusicTrack(
                    provider_track_id="PL2-track-1",
                    title="Track 1",
                    artist="Artist 1",
                    album=None,
                    year=None,
                    isrc=None,
                    duration_ms=None,
                )
            ],
        },
    ]
