from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.streaming.adapters.youtube_music import (
    MalformedPlaylistPayloadError,
    YouTubeMusicAdapter,
    YouTubeMusicPlaylist,
    YouTubeMusicTrackMetadata,
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

    monkeypatch.setattr("app.streaming.adapters.youtube_music.YTMusic", FakeYTMusic)

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


def test_from_browser_auth_accepts_raw_header_mapping(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeYTMusic:
        def __init__(
            self,
            *,
            auth: dict[str, str],
            user: str | None,
            language: str,
            location: str,
        ) -> None:
            seen["auth"] = auth
            seen["user"] = user
            seen["language"] = language
            seen["location"] = location

    monkeypatch.setattr("app.streaming.adapters.youtube_music.YTMusic", FakeYTMusic)

    adapter = YouTubeMusicAdapter.from_browser_auth(
        {
            "Authorization": "Bearer token-123",
            "X-Goog-AuthUser": "0",
        },
        user="listener@example.com",
        location="US",
    )

    assert isinstance(adapter, YouTubeMusicAdapter)
    assert seen == {
        "auth": {
            "Authorization": "Bearer token-123",
            "X-Goog-AuthUser": "0",
        },
        "user": "listener@example.com",
        "language": "en",
        "location": "US",
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


def test_get_track_metadata_prefers_watch_playlist_fields_and_highest_res_art() -> None:
    class FakeYTMusic:
        def get_song(
            self,
            *,
            videoId: str,
            signatureTimestamp: int | None,
        ) -> dict[str, object]:
            assert videoId == "track-9"
            assert signatureTimestamp is None
            return {
                "videoDetails": {
                    "title": "Fallback Title",
                    "author": "Fallback Artist",
                    "thumbnails": [
                        {
                            "url": "https://img.example/320.jpg",
                            "width": 320,
                            "height": 320,
                        },
                    ],
                },
                "album": {"name": "Fallback Album"},
                "year": 2018,
            }

        def get_watch_playlist(
            self,
            *,
            videoId: str | None,
            playlistId: str | None,
            limit: int,
            radio: bool,
            shuffle: bool,
        ) -> dict[str, object]:
            assert videoId == "track-9"
            assert playlistId is None
            assert limit == 1
            assert radio is False
            assert shuffle is False
            return {
                "tracks": [
                    {
                        "title": "Rescue Title",
                        "artists": [{"name": "Rescue Artist"}],
                        "album": {"name": "Rescue Album"},
                        "year": 2022,
                        "thumbnails": [
                            {
                                "url": "https://img.example/640.jpg",
                                "width": 640,
                                "height": 640,
                            },
                            {
                                "url": "https://img.example/1280.jpg",
                                "width": 1280,
                                "height": 1280,
                            },
                        ],
                    }
                ]
            }

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.get_track_metadata("track-9") == YouTubeMusicTrackMetadata(
        title="Rescue Title",
        artist="Rescue Artist",
        album="Rescue Album",
        year=2022,
        album_art_url="https://img.example/1280.jpg",
    )


def test_list_playlist_tracks_only_fetches_song_for_missing_isrc() -> None:
    seen: dict[str, object] = {"song_ids": []}

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
            return {
                "tracks": [
                    {
                        "videoId": "track-1",
                        "title": "Has ISRC",
                        "artist": "Artist 1",
                        "isrc": "GBUM72105976",
                    },
                    {
                        "videoId": "track-2",
                        "title": "Needs Lookup",
                        "artist": "Artist 2",
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
            cast_song_ids = seen["song_ids"]
            assert isinstance(cast_song_ids, list)
            cast_song_ids.append(videoId)
            return {
                "playabilityStatus": {
                    "musicDetail": {
                        "internationalStandardRecordingCode": "USQX92200001"
                    }
                }
            }

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.list_playlist_tracks("PL1") == [
        YouTubeMusicTrack(
            provider_track_id="track-1",
            title="Has ISRC",
            artist="Artist 1",
            album=None,
            year=None,
            isrc="GBUM72105976",
            duration_ms=None,
        ),
        YouTubeMusicTrack(
            provider_track_id="track-2",
            title="Needs Lookup",
            artist="Artist 2",
            album=None,
            year=None,
            isrc="USQX92200001",
            duration_ms=None,
        ),
    ]
    assert seen["song_ids"] == ["track-2"]


def test_list_playlist_tracks_fetches_missing_isrc_once_per_unique_track_id() -> None:
    seen: dict[str, object] = {"song_ids": []}

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
            return {
                "tracks": [
                    {
                        "videoId": "track-2",
                        "title": "Needs Lookup",
                        "artist": "Artist 2",
                    },
                    {
                        "videoId": "track-2",
                        "title": "Needs Lookup",
                        "artist": "Artist 2",
                    },
                    {
                        "videoId": "track-3",
                        "title": "Also Needs Lookup",
                        "artist": "Artist 3",
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
            cast_song_ids = seen["song_ids"]
            assert isinstance(cast_song_ids, list)
            cast_song_ids.append(videoId)
            return {
                "playabilityStatus": {
                    "musicDetail": {
                        "internationalStandardRecordingCode": f"ISRC-{videoId}"
                    }
                }
            }

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.list_playlist_tracks("PL1") == [
        YouTubeMusicTrack(
            provider_track_id="track-2",
            title="Needs Lookup",
            artist="Artist 2",
            album=None,
            year=None,
            isrc="ISRC-track-2",
            duration_ms=None,
        ),
        YouTubeMusicTrack(
            provider_track_id="track-2",
            title="Needs Lookup",
            artist="Artist 2",
            album=None,
            year=None,
            isrc="ISRC-track-2",
            duration_ms=None,
        ),
        YouTubeMusicTrack(
            provider_track_id="track-3",
            title="Also Needs Lookup",
            artist="Artist 3",
            album=None,
            year=None,
            isrc="ISRC-track-3",
            duration_ms=None,
        ),
    ]
    assert sorted(seen["song_ids"]) == ["track-2", "track-3"]


def test_list_playlist_tracks_isolates_missing_isrc_lookup_failures() -> None:
    seen: dict[str, object] = {"song_ids": []}

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
            return {
                "tracks": [
                    {
                        "videoId": "track-2",
                        "title": "Bad Lookup",
                        "artist": "Artist 2",
                    },
                    {
                        "videoId": "track-3",
                        "title": "Good Lookup",
                        "artist": "Artist 3",
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
            cast_song_ids = seen["song_ids"]
            assert isinstance(cast_song_ids, list)
            cast_song_ids.append(videoId)
            if videoId == "track-2":
                raise RuntimeError("upstream lookup failed")
            return {
                "playabilityStatus": {
                    "musicDetail": {
                        "internationalStandardRecordingCode": "ISRC-track-3"
                    }
                }
            }

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.list_playlist_tracks("PL1") == [
        YouTubeMusicTrack(
            provider_track_id="track-2",
            title="Bad Lookup",
            artist="Artist 2",
            album=None,
            year=None,
            isrc=None,
            duration_ms=None,
        ),
        YouTubeMusicTrack(
            provider_track_id="track-3",
            title="Good Lookup",
            artist="Artist 3",
            album=None,
            year=None,
            isrc="ISRC-track-3",
            duration_ms=None,
        ),
    ]
    assert sorted(seen["song_ids"]) == ["track-2", "track-3"]


def test_list_playlist_tracks_raises_for_non_list_tracks_payload() -> None:
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
            return {"tracks": None}

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    with pytest.raises(MalformedPlaylistPayloadError):
        adapter.list_playlist_tracks("PL1")


def test_list_playlist_tracks_returns_empty_for_empty_playlist() -> None:
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
            return {"tracks": []}

    adapter = YouTubeMusicAdapter(FakeYTMusic())  # type: ignore[arg-type]

    assert adapter.list_playlist_tracks("PL1") == []


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
                SimpleNamespace(
                    id=11, provider_playlist_id="PL1", selected_for_sync=True
                ),
                SimpleNamespace(
                    id=12, provider_playlist_id="PL2", selected_for_sync=True
                ),
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


def test_sync_library_playlist_tracks_skips_malformed_playlist_payload() -> None:
    seen: dict[str, object] = {"replaced_playlist_ids": []}

    class FakePlaylistStore:
        def upsert_playlists(self, *, account_id, playlists, synced_at):
            return [
                SimpleNamespace(
                    id=11, provider_playlist_id="PL1", selected_for_sync=True
                ),
                SimpleNamespace(
                    id=12, provider_playlist_id="PL2", selected_for_sync=True
                ),
            ]

        def replace_playlist_membership(self, *, playlist_id, tracks):
            seen["replaced_playlist_ids"].append(playlist_id)
            return [f"membership-{playlist_id}"]

        def mark_playlist_sync_failure(self, *, playlist_id, error, failed_at):
            seen["failed_playlist_id"] = playlist_id
            seen["failure_error"] = error
            seen["failed_at"] = failed_at

    class FakeAdapter:
        def list_library_playlists(self):
            return [
                YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip"),
                YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Focus"),
            ]

        def list_playlist_tracks(self, playlist_id):
            if playlist_id == "PL1":
                raise MalformedPlaylistPayloadError("invalid tracks payload")
            return [
                YouTubeMusicTrack(
                    provider_track_id="PL2-track-1",
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

    assert result == ["membership-12"]
    assert seen["replaced_playlist_ids"] == [12]
    assert seen["failed_playlist_id"] == 11
    assert seen["failure_error"] == "invalid tracks payload"
    assert isinstance(seen["failed_at"], datetime)


def test_sync_library_playlist_tracks_isolates_playlist_failures() -> None:
    seen: dict[str, object] = {"replaced_playlist_ids": []}

    class FakePlaylistStore:
        def upsert_playlists(self, *, account_id, playlists, synced_at):
            return [
                SimpleNamespace(
                    id=11, provider_playlist_id="PL1", selected_for_sync=True
                ),
                SimpleNamespace(
                    id=12, provider_playlist_id="PL2", selected_for_sync=True
                ),
            ]

        def replace_playlist_membership(self, *, playlist_id, tracks):
            seen["replaced_playlist_ids"].append(playlist_id)
            return [f"membership-{playlist_id}"]

        def mark_playlist_sync_failure(self, *, playlist_id, error, failed_at):
            seen["failed_playlist_id"] = playlist_id
            seen["failure_error"] = error
            seen["failed_at"] = failed_at

    class FakeAdapter:
        def list_library_playlists(self):
            return [
                YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Road Trip"),
                YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Focus"),
            ]

        def list_playlist_tracks(self, playlist_id):
            if playlist_id == "PL1":
                raise RuntimeError("upstream request failed")
            return [
                YouTubeMusicTrack(
                    provider_track_id="PL2-track-1",
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

    assert result == ["membership-12"]
    assert seen["failed_playlist_id"] == 11
    assert seen["failure_error"] == "upstream request failed"
    assert isinstance(seen["failed_at"], datetime)
    assert seen["replaced_playlist_ids"] == [12]
