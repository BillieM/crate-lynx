from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, insert

from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
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
                    "duration_ms": None,
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
        str((tmp_path / "exports" / "Artist/second.mp3").resolve()),
        str((tmp_path / "exports" / "Artist/first.mp3").resolve()),
    ]


def test_generate_m3u_returns_empty_string_for_playlist_without_final_links(
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

    assert generate_m3u(7, tmp_path / "exports") == ""
