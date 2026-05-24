from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine

from app.links.store import metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.exporter import (
    InvalidM3uExportFormatError,
    build_m3u_export_package,
    build_m3u_export_zip,
    normalize_m3u_export_formats,
)
from app.m3u.models import metadata as m3u_metadata
from app.m3u.store import (
    InvalidM3uExportLibraryPathError,
    M3uExportProfileStore,
    normalize_m3u_export_library_path,
)
from app.relationships.models import metadata as relationships_metadata
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    metadata as streaming_metadata,
)
from tests import factories


def test_export_profile_store_saves_first_profile_as_default(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm3u-profiles.db'}")
    m3u_metadata.create_all(engine)
    store = M3uExportProfileStore(engine=engine)

    first = store.create_profile(name="NAS", library_path="/music")
    second = store.create_profile(name="USB", library_path="/Volumes/usb/music")

    assert first.is_default is True
    assert second.is_default is False

    updated_second = store.update_profile(profile_id=second.id, is_default=True)
    profiles = store.list_profiles()

    assert updated_second.is_default is True
    assert [profile.id for profile in profiles] == [second.id, first.id]
    assert [profile.is_default for profile in profiles] == [True, False]

    store.delete_profile(second.id)

    assert store.list_profiles()[0].is_default is True


def test_export_library_path_validation_accepts_posix_and_windows() -> None:
    assert normalize_m3u_export_library_path("/mnt/music/../library") == "/mnt/library"
    assert normalize_m3u_export_library_path(r"D:\Music\Library") == r"D:\Music\Library"

    with pytest.raises(InvalidM3uExportLibraryPathError):
        normalize_m3u_export_library_path("relative/music")


def test_export_format_validation_dedupes_and_requires_supported_formats() -> None:
    assert normalize_m3u_export_formats(["m3u8", "m3u", "m3u8"]) == (
        "m3u8",
        "m3u",
    )

    with pytest.raises(InvalidM3uExportFormatError):
        normalize_m3u_export_formats([])

    with pytest.raises(InvalidM3uExportFormatError):
        normalize_m3u_export_formats(["pls"])


def test_build_m3u_export_package_uses_full_sync_playlists_and_dedupes_names(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm3u-export.db'}")
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    first_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-first",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Road Trip",
    )
    second_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-second",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Road Trip",
    )
    match_only_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-match",
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
        title="Match Only",
    )
    first_local_id = test_data.local_track(
        file_path="source-path.flac",
        library_root_rel_path="Artist/First.flac",
    )
    second_local_id = test_data.local_track(
        file_path="other-source-path.flac",
        library_root_rel_path="Artist/Second.flac",
    )
    first_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-first",
        title="First",
    )
    second_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-second",
        title="Second",
    )
    unlinked_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-unlinked",
        title="Unlinked",
    )
    test_data.playlist_membership(
        playlist_id=first_playlist_id,
        position=1,
        streaming_track_id=first_streaming_id,
    )
    test_data.playlist_membership(
        playlist_id=first_playlist_id,
        position=2,
        streaming_track_id=unlinked_streaming_id,
    )
    test_data.playlist_membership(
        playlist_id=second_playlist_id,
        position=1,
        streaming_track_id=second_streaming_id,
    )
    test_data.playlist_membership(
        playlist_id=match_only_playlist_id,
        position=1,
        streaming_track_id=first_streaming_id,
    )
    test_data.final_link(
        local_track_id=first_local_id,
        streaming_track_id=first_streaming_id,
    )
    test_data.final_link(
        local_track_id=second_local_id,
        streaming_track_id=second_streaming_id,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        library_path="/export/music",
        playlist_ids=[first_playlist_id, second_playlist_id],
    )

    assert export_package.total_exported_track_count == 2
    assert export_package.total_skipped_track_count == 1
    assert export_package.formats == ("m3u", "m3u8")
    assert export_package.path_format == "absolute"
    assert [playlist.filename_m3u for playlist in export_package.playlists] == [
        "Road Trip [yt].m3u",
        "Road Trip [yt]-2.m3u",
    ]
    assert export_package.playlists[0].filenames(export_package.formats) == [
        "Road Trip [yt].m3u",
        "Road Trip [yt].m3u8",
    ]
    assert export_package.playlists[0].rendered.sample_path == (
        "/export/music/Artist/First.flac"
    )

    archive = build_m3u_export_zip(export_package)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert zip_file.namelist() == [
            "Road Trip [yt].m3u",
            "Road Trip [yt].m3u8",
            "Road Trip [yt]-2.m3u",
            "Road Trip [yt]-2.m3u8",
        ]
        assert zip_file.read("Road Trip [yt].m3u").decode("utf-8").splitlines() == [
            "#EXTM3U",
            "/export/music/Artist/First.flac",
        ]


def test_build_m3u_export_zip_uses_selected_formats(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm3u-export-formats.db'}")
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-first",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Road Trip",
    )
    local_id = test_data.local_track(
        file_path="source-path.flac",
        library_root_rel_path="Artist/First.flac",
    )
    streaming_id = test_data.streaming_track(
        provider_track_id="ytm-first",
        title="First",
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=1,
        streaming_track_id=streaming_id,
    )
    test_data.final_link(
        local_track_id=local_id,
        streaming_track_id=streaming_id,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        formats=["m3u8"],
        library_path="/export/music",
        playlist_ids=[playlist_id],
    )

    archive = build_m3u_export_zip(export_package)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert zip_file.namelist() == ["Road Trip [yt].m3u8"]
        assert zip_file.read("Road Trip [yt].m3u8").decode("utf-8").splitlines() == [
            "#EXTM3U",
            "/export/music/Artist/First.flac",
        ]


def test_build_m3u_export_package_can_render_file_urls(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'm3u-export-path-style.db'}")
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-first",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Party",
    )
    local_id = test_data.local_track(
        file_path="source-path.mp3",
        library_root_rel_path="Non-Album/Vengaboys/We Like to Party!.mp3",
    )
    streaming_id = test_data.streaming_track(
        provider_track_id="ytm-first",
        title="We Like to Party!",
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=1,
        streaming_track_id=streaming_id,
    )
    test_data.final_link(
        local_track_id=local_id,
        streaming_track_id=streaming_id,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        formats=["m3u"],
        library_path="/Volumes/data/media/music",
        path_format="file_url",
        playlist_ids=[playlist_id],
    )

    expected_url = (
        "file://localhost/Volumes/data/media/music/Non-Album/Vengaboys/"
        "We%20Like%20to%20Party%21.mp3"
    )
    assert export_package.path_format == "file_url"
    assert export_package.playlists[0].rendered.sample_path == expected_url

    archive = build_m3u_export_zip(export_package)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert zip_file.read("Party [yt].m3u").decode("utf-8").splitlines() == [
            "#EXTM3U",
            expected_url,
        ]
