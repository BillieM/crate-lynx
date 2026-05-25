from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert

from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.m3u.generator import (
    InvalidM3uExportPathFormatError,
    build_m3u_playlist_export,
    format_export_audio_path,
    format_file_url,
    format_m3u_entry_path,
    generate_m3u,
    get_m3u_output_dir,
    normalize_m3u_export_path_format,
    regenerate_m3us_for_streaming_track,
)
from app.relationships.models import (
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    metadata as relationships_metadata,
    streaming_relationships_table,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_OFF,
    metadata as streaming_metadata,
    playlist_membership_table,
    streaming_playlists_table,
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
    relationships_metadata.create_all(engine)
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
    export = build_m3u_playlist_export(7, tmp_path / "exports")
    assert export.exported_track_count == 2
    assert export.skipped_track_count == 1
    assert export.sample_path == str((tmp_path / "exports" / "Artist/second.mp3"))

    path_only_export = build_m3u_playlist_export(
        7,
        tmp_path / "exports",
        include_extinf=False,
    )
    assert path_only_export.content.splitlines() == [
        "#EXTM3U",
        str((tmp_path / "exports" / "Artist/second.mp3").resolve()),
        str((tmp_path / "exports" / "Artist/first.mp3").resolve()),
    ]

    file_url_export = build_m3u_playlist_export(
        7,
        tmp_path / "exports",
        include_extinf=False,
        path_format="file_url",
    )
    assert file_url_export.content.splitlines() == [
        "#EXTM3U",
        format_file_url(str((tmp_path / "exports" / "Artist/second.mp3").resolve())),
        format_file_url(str((tmp_path / "exports" / "Artist/first.mp3").resolve())),
    ]


def test_generate_m3u_uses_equivalent_link_with_playlist_row_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'm3u-equivalent.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=1,
                file_path="Artist/source.mp3",
                library_root_rel_path="Artist/source.mp3",
                fingerprint="fp-1",
                beets_id=1,
            )
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 11,
                    "provider_track_id": "ytm-source",
                    "title": "Source Metadata",
                    "artist": "Source Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": 121000,
                },
                {
                    "id": 12,
                    "provider_track_id": "ytm-playlist",
                    "title": "Playlist Metadata",
                    "artist": "Playlist Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": 205000,
                },
            ],
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=12,
                position=1,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=1,
                streaming_track_id=11,
            )
        )
        connection.execute(
            insert(streaming_relationships_table).values(
                lower_track_id=11,
                higher_track_id=12,
                relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            )
        )

    output = generate_m3u(7, tmp_path / "exports")

    assert output.splitlines() == [
        "#EXTM3U",
        "#EXTINF:205,Playlist Artist - Playlist Metadata",
        str((tmp_path / "exports" / "Artist/source.mp3").resolve()),
    ]


def test_get_m3u_output_dir_uses_configured_staging_base(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("M3U_OUTPUT_DIR", raising=False)
    monkeypatch.setenv("CRATE_LYNX_STAGING_DIR", str(tmp_path / "stage"))

    assert get_m3u_output_dir() == tmp_path / "stage" / "m3u"


def test_format_export_audio_path_supports_windows_roots() -> None:
    assert (
        format_export_audio_path(
            r"D:\Music",
            "Artist/Album/Track.flac",
        )
        == r"D:\Music\Artist\Album\Track.flac"
    )


def test_format_m3u_entry_path_supports_file_urls() -> None:
    assert format_m3u_entry_path(
        "/Volumes/data/media/music/Non-Album/Vengaboys/We Like to Party!.mp3",
        "file_url",
    ) == (
        "file://localhost/Volumes/data/media/music/Non-Album/Vengaboys/"
        "We%20Like%20to%20Party%21.mp3"
    )
    assert (
        format_m3u_entry_path(
            r"D:\Music\Artist\Album Track.flac",
            "file_url",
        )
        == "file:///D:/Music/Artist/Album%20Track.flac"
    )
    assert (
        format_m3u_entry_path(
            r"\\nas\music\Artist\Album Track.flac",
            "file_url",
        )
        == "file://nas/music/Artist/Album%20Track.flac"
    )
    assert normalize_m3u_export_path_format("absolute") == "absolute"

    with pytest.raises(InvalidM3uExportPathFormatError):
        normalize_m3u_export_path_format("relative")


def test_generate_m3u_returns_header_only_for_playlist_without_final_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'm3u-empty.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
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


def test_regenerate_m3us_for_streaming_track_writes_only_full_playlists(
    library_root: Path,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'regenerate-full-only.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    output_dir = tmp_path / "m3u"
    stale_match_only_path = output_dir / "Match-Only.m3u"
    stale_off_path = output_dir / "Off-Playlist.m3u"
    output_dir.mkdir(parents=True)
    stale_match_only_path.write_text("stale match-only", encoding="utf-8")
    stale_off_path.write_text("stale off", encoding="utf-8")

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/linked.mp3",
                library_root_rel_path="Artist/linked.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Linked Track",
                artist="Artist",
                album=None,
                year=None,
                isrc=None,
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(streaming_playlists_table),
            [
                {
                    "id": 7,
                    "account_id": 1,
                    "provider_playlist_id": "PL-full",
                    "title": "Full Playlist",
                    "sync_mode": PLAYLIST_SYNC_MODE_FULL,
                },
                {
                    "id": 8,
                    "account_id": 1,
                    "provider_playlist_id": "PL-match",
                    "title": "Match Only",
                    "sync_mode": PLAYLIST_SYNC_MODE_MATCH_ONLY,
                },
                {
                    "id": 9,
                    "account_id": 1,
                    "provider_playlist_id": "PL-off",
                    "title": "Off Playlist",
                    "sync_mode": PLAYLIST_SYNC_MODE_OFF,
                },
            ],
        )
        connection.execute(
            insert(playlist_membership_table),
            [
                {"playlist_id": 7, "streaming_track_id": 9, "position": 1},
                {"playlist_id": 8, "streaming_track_id": 9, "position": 1},
                {"playlist_id": 9, "streaming_track_id": 9, "position": 1},
            ],
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=4,
                streaming_track_id=9,
            )
        )

    written_paths = regenerate_m3us_for_streaming_track(
        9,
        engine=engine,
        base_path=library_root,
        output_dir=output_dir,
    )

    full_path = (output_dir / "Full-Playlist.m3u").resolve()
    assert written_paths == [full_path]
    assert full_path.read_text(encoding="utf-8").splitlines() == [
        "#EXTM3U",
        "#EXTINF:123,Artist - Linked Track",
        str((library_root / "Artist/linked.mp3").resolve()),
    ]
    assert stale_match_only_path.read_text(encoding="utf-8") == "stale match-only"
    assert stale_off_path.read_text(encoding="utf-8") == "stale off"
