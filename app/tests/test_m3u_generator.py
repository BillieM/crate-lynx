from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import create_engine, insert

from app.links.router import create_router
from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.matching.pipeline import SUGGESTED_LINK_STATUS_APPROVED
from app.m3u.generator import generate_m3u
from app.streaming.models import (
    metadata as streaming_metadata,
    playlist_membership_table,
    streaming_tracks_table,
)


def test_generate_m3u_returns_only_final_linked_tracks_in_playlist_order(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'm3u.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table),
            [
                {
                    "id": 1,
                    "file_path": "Artist/first.mp3",
                    "library_root_rel_path": "Artist/first.mp3",
                    "fingerprint": "fp-1",
                    "beets_id": 1,
                },
                {
                    "id": 2,
                    "file_path": "Artist/second.mp3",
                    "library_root_rel_path": "Artist/second.mp3",
                    "fingerprint": "fp-2",
                    "beets_id": 2,
                },
                {
                    "id": 3,
                    "file_path": "Artist/unlinked.mp3",
                    "library_root_rel_path": "Artist/unlinked.mp3",
                    "fingerprint": "fp-3",
                    "beets_id": 3,
                },
            ],
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "First",
                    "artist": "Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": 121000,
                },
                {
                    "id": 12,
                    "provider_track_id": "ytm-12",
                    "title": "Second",
                    "artist": "Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": None,
                },
                {
                    "id": 13,
                    "provider_track_id": "ytm-13",
                    "title": "Unlinked",
                    "artist": "Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": None,
                },
            ],
        )
        connection.execute(
            insert(playlist_membership_table),
            [
                {
                    "playlist_id": 7,
                    "streaming_track_id": 12,
                    "position": 1,
                },
                {
                    "playlist_id": 7,
                    "streaming_track_id": 13,
                    "position": 2,
                },
                {
                    "playlist_id": 7,
                    "streaming_track_id": 11,
                    "position": 3,
                },
            ],
        )
        connection.execute(
            insert(final_links_table),
            [
                {
                    "local_track_id": 1,
                    "streaming_track_id": 11,
                },
                {
                    "local_track_id": 2,
                    "streaming_track_id": 12,
                },
            ],
        )

    output = generate_m3u(7, tmp_path / "exports")

    assert output.splitlines() == [
        "#EXTM3U",
        "#EXTINF:-1,Artist - Second",
        str((tmp_path / "exports" / "Artist/second.mp3").resolve()),
        "#EXTINF:121,Artist - First",
        str((tmp_path / "exports" / "Artist/first.mp3").resolve()),
    ]


def test_generate_m3u_returns_header_only_for_playlist_without_final_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'm3u-empty.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_tracks_table).values(
                id=11,
                provider_track_id="ytm-11",
                title="Only Track",
                artist="Artist",
                album=None,
                year=None,
                isrc=None,
                duration_ms=None,
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=11,
                position=1,
            )
        )

    assert generate_m3u(7, tmp_path / "exports") == "#EXTM3U"


def test_generate_m3u_returns_header_only_for_empty_playlist(
    migrated_database,
    test_data,
    tmp_path: Path,
) -> None:
    _, engine = migrated_database
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-empty",
        title="Empty Playlist",
    )

    assert generate_m3u(playlist_id, tmp_path / "exports", engine=engine) == "#EXTM3U"


def test_generate_m3u_returns_header_only_when_all_playlist_tracks_are_unlinked(
    migrated_database,
    test_data,
    tmp_path: Path,
) -> None:
    _, engine = migrated_database
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-unlinked",
        title="Unlinked Playlist",
    )
    first_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-unlinked-1",
        title="Unlinked One",
    )
    second_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-unlinked-2",
        title="Unlinked Two",
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=1,
        streaming_track_id=first_streaming_id,
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=2,
        streaming_track_id=second_streaming_id,
    )

    assert generate_m3u(playlist_id, tmp_path / "exports", engine=engine) == "#EXTM3U"


def test_approving_proposal_regenerates_m3u_export(
    library_root: Path,
    migrated_database,
    monkeypatch,
    test_data,
    tmp_path: Path,
) -> None:
    database_url, _ = migrated_database
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("M3U_OUTPUT_DIR", str(tmp_path / "m3u"))
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-road-trip",
        title="Road Trip Mix",
    )
    local_track_id = test_data.local_track(
        beets_id=42,
        file_path="Artist/approved.mp3",
        fingerprint="fp-approved",
    )
    streaming_track_id = test_data.streaming_track(
        artist="Artist",
        duration_ms=123000,
        provider_track_id="ytm-approved",
        title="Approved Track",
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=1,
        streaming_track_id=streaming_track_id,
    )
    proposal_id = test_data.suggested_link(
        local_track_id=local_track_id,
        streaming_track_id=streaming_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/approve"
        and "POST" in getattr(route, "methods", set())
    )

    response = _call_endpoint(route.endpoint, proposal_id)

    assert response["status"] == SUGGESTED_LINK_STATUS_APPROVED
    assert (tmp_path / "m3u" / "Road-Trip-Mix.m3u").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "#EXTM3U",
        "#EXTINF:123,Artist - Approved Track",
        str((library_root / "Artist/approved.mp3").resolve()),
    ]


def _call_endpoint(endpoint, *args):
    result = endpoint(*args)
    if inspect.isawaitable(result):
        raise AssertionError("Unexpected async endpoint in m3u generator test")
    return result
