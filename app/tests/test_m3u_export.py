from __future__ import annotations

from io import BytesIO
import inspect
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.links.store import metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.exporter import (
    InvalidM3uExportFormatError,
    build_full_rekordbox_xml_export_package,
    build_m3u_export_package,
    build_m3u_export_zip,
    build_rekordbox_xml,
    normalize_m3u_export_formats,
)
from app.m3u.models import metadata as m3u_metadata
from app.m3u.router import create_router
from app.m3u.schemas import M3uExportRequest
from app.m3u.store import (
    InvalidM3uExportLibraryPathError,
    M3uExportProfileStore,
    normalize_m3u_export_library_path,
)
from app.relationships.models import metadata as relationships_metadata
from app.sonic.models import metadata as sonic_metadata
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    metadata as streaming_metadata,
)
from tests import factories


def _call_endpoint(endpoint, *args, **kwargs):
    result = endpoint(*args, **kwargs)
    if inspect.isawaitable(result):
        raise AssertionError("Unexpected async M3U endpoint")
    return result


def _route(router, method: str, path: str):
    return next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def _create_generated_export_engine(tmp_path: Path, filename: str):
    engine = create_engine(f"sqlite:///{tmp_path / filename}")
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    m3u_metadata.create_all(engine)
    return engine


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


def test_build_m3u_export_package_expands_generated_run_hierarchy(
    tmp_path: Path,
) -> None:
    engine = _create_generated_export_engine(tmp_path, "generated-run-export.db")
    test_data = factories.TestDataFactory(engine)
    parent_track_id = test_data.local_track(
        file_path="Frame Delay/Night Runner.mp3",
        library_root_rel_path="Frame Delay/Night Runner.mp3",
    )
    child_track_id = test_data.local_track(
        file_path="Static Gate/Pending Signal.mp3",
        library_root_rel_path="Static Gate/Pending Signal.mp3",
    )
    run_id = test_data.playlist_generation_run()
    parent_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Root Mix",
        position=1,
        track_count=1,
    )
    child_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Child Mix",
        parent_playlist_id=parent_playlist_id,
        depth=1,
        position=1,
        track_count=1,
    )
    test_data.generated_playlist_track(
        generated_playlist_id=parent_playlist_id,
        local_track_id=parent_track_id,
    )
    test_data.generated_playlist_track(
        generated_playlist_id=child_playlist_id,
        local_track_id=child_track_id,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        formats=["m3u"],
        generated_run_ids=[run_id],
        library_path="/export/music",
        playlist_ids=[],
    )

    assert [playlist.generated_run_id for playlist in export_package.playlists] == [
        run_id,
        run_id,
    ]
    assert [
        playlist.generated_playlist_id for playlist in export_package.playlists
    ] == [
        parent_playlist_id,
        child_playlist_id,
    ]
    assert [playlist.archive_path_m3u for playlist in export_package.playlists] == [
        f"Generated Run {run_id}/Root Mix [gen].m3u",
        f"Generated Run {run_id}/Root Mix [gen]/Child Mix [gen].m3u",
    ]

    archive = build_m3u_export_zip(export_package)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert zip_file.namelist() == [
            f"Generated Run {run_id}/Root Mix [gen].m3u",
            f"Generated Run {run_id}/Root Mix [gen]/Child Mix [gen].m3u",
        ]
        assert "/export/music/Static Gate/Pending Signal.mp3" in zip_file.read(
            f"Generated Run {run_id}/Root Mix [gen]/Child Mix [gen].m3u"
        ).decode("utf-8")

    rekordbox_xml = ElementTree.fromstring(build_rekordbox_xml(export_package))
    collection = rekordbox_xml.find("COLLECTION")
    assert collection is not None
    assert collection.attrib["Entries"] == "2"
    assert [
        (track.attrib["Name"], track.attrib["Location"])
        for track in collection.findall("TRACK")
    ] == [
        (
            "Night Runner",
            "file://localhost/export/music/Frame%20Delay/Night%20Runner.mp3",
        ),
        (
            "Pending Signal",
            "file://localhost/export/music/Static%20Gate/Pending%20Signal.mp3",
        ),
    ]

    root_node = rekordbox_xml.find("./PLAYLISTS/NODE")
    assert root_node is not None
    generated_run_node = root_node.find(f"./NODE[@Name='Generated Run {run_id}']")
    assert generated_run_node is not None
    root_mix_folder = generated_run_node.find("./NODE[@Name='Root Mix [gen]']")
    assert root_mix_folder is not None
    root_mix_playlist = root_mix_folder.find(
        "./NODE[@Type='1'][@Name='Root Mix [gen]']"
    )
    child_mix_playlist = root_mix_folder.find(
        "./NODE[@Type='1'][@Name='Child Mix [gen]']"
    )
    assert root_mix_folder.attrib == {
        "Count": "2",
        "Name": "Root Mix [gen]",
        "Type": "0",
    }
    assert root_mix_playlist is not None
    assert root_mix_playlist.attrib["Entries"] == "1"
    assert root_mix_playlist.find("TRACK").attrib["Key"] == "1"
    assert child_mix_playlist is not None
    assert child_mix_playlist.attrib["Entries"] == "1"
    assert child_mix_playlist.find("TRACK").attrib["Key"] == "2"


def test_build_m3u_export_package_dedupes_generated_run_sibling_paths(
    tmp_path: Path,
) -> None:
    engine = _create_generated_export_engine(tmp_path, "generated-run-dedupe.db")
    test_data = factories.TestDataFactory(engine)
    run_id = test_data.playlist_generation_run()
    later_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Mood",
        position=2,
    )
    earlier_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Mood",
        position=1,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        formats=["m3u"],
        generated_run_ids=[run_id],
        library_path="/export/music",
        playlist_ids=[],
    )

    assert [
        (playlist.generated_playlist_id, playlist.archive_path_m3u)
        for playlist in export_package.playlists
    ] == [
        (earlier_playlist_id, f"Generated Run {run_id}/Mood [gen].m3u"),
        (later_playlist_id, f"Generated Run {run_id}/Mood [gen]-2.m3u"),
    ]


def test_generated_playlist_ids_remain_flat_in_m3u_export_zip(tmp_path: Path) -> None:
    engine = _create_generated_export_engine(tmp_path, "generated-flat-export.db")
    test_data = factories.TestDataFactory(engine)
    run_id = test_data.playlist_generation_run()
    parent_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Root Mix",
        position=1,
    )
    child_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Child Mix",
        parent_playlist_id=parent_playlist_id,
        depth=1,
        position=1,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        formats=["m3u"],
        generated_playlist_ids=[parent_playlist_id, child_playlist_id],
        library_path="/export/music",
        playlist_ids=[],
    )

    assert [playlist.archive_path_m3u for playlist in export_package.playlists] == [
        "Root Mix [gen].m3u",
        "Child Mix [gen].m3u",
    ]
    archive = build_m3u_export_zip(export_package)
    with ZipFile(BytesIO(archive)) as zip_file:
        assert zip_file.namelist() == [
            "Root Mix [gen].m3u",
            "Child Mix [gen].m3u",
        ]


def test_m3u_preview_endpoint_reports_missing_generated_run(tmp_path: Path) -> None:
    engine = _create_generated_export_engine(tmp_path, "missing-generated-run.db")
    router = create_router()
    payload = M3uExportRequest.model_validate(
        {"generated_run_ids": [404], "library_path": "/mnt/music"}
    )

    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint(
            _route(router, "POST", "/m3u/export/preview").endpoint,
            payload,
            engine=engine,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Generated run not found: 404"


def test_rekordbox_xml_export_endpoint_returns_download(tmp_path: Path) -> None:
    engine = _create_generated_export_engine(tmp_path, "rekordbox-xml-route.db")
    test_data = factories.TestDataFactory(engine)
    local_track_id = test_data.local_track(
        file_path="Frame Delay/Night Runner.mp3",
        library_root_rel_path="Frame Delay/Night Runner.mp3",
    )
    run_id = test_data.playlist_generation_run()
    playlist_id = test_data.generated_playlist(run_id=run_id, name="Root Mix")
    test_data.generated_playlist_track(
        generated_playlist_id=playlist_id,
        local_track_id=local_track_id,
    )
    router = create_router()
    payload = M3uExportRequest.model_validate(
        {"generated_run_ids": [run_id], "library_path": "/mnt/music"}
    )

    response = _call_endpoint(
        _route(router, "POST", "/m3u/export/rekordbox-xml").endpoint,
        payload,
        engine=engine,
    )

    assert response.media_type == "application/xml"
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="rekordbox.xml"'
    )
    assert b"<DJ_PLAYLISTS" in response.body
    assert (
        b"file://localhost/mnt/music/Frame%20Delay/Night%20Runner.mp3" in response.body
    )


def test_full_rekordbox_xml_export_groups_streaming_and_generated_runs(
    tmp_path: Path,
) -> None:
    engine = _create_generated_export_engine(tmp_path, "full-rekordbox-xml.db")
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    other_account_id = test_data.streaming_account(
        display_name="Other",
        provider="spotify",
    )
    streaming_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-road",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Road Trip",
    )
    match_only_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-match",
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
        title="Match Only",
    )
    other_provider_playlist_id = test_data.streaming_playlist(
        account_id=other_account_id,
        provider_playlist_id="SP-road",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Other Road",
    )
    local_track_id = test_data.local_track(
        file_path="Frame Delay/Night Runner.mp3",
        library_root_rel_path="Frame Delay/Night Runner.mp3",
    )
    streaming_track_id = test_data.streaming_track(
        provider_track_id="ytm-road",
        title="Night Runner",
    )
    test_data.playlist_membership(
        playlist_id=streaming_playlist_id,
        position=1,
        streaming_track_id=streaming_track_id,
    )
    test_data.playlist_membership(
        playlist_id=match_only_playlist_id,
        position=1,
        streaming_track_id=streaming_track_id,
    )
    test_data.playlist_membership(
        playlist_id=other_provider_playlist_id,
        position=1,
        streaming_track_id=streaming_track_id,
    )
    test_data.final_link(
        local_track_id=local_track_id,
        streaming_track_id=streaming_track_id,
    )
    generated_track_id = test_data.local_track(
        file_path="Static Gate/Pending Signal.mp3",
        library_root_rel_path="Static Gate/Pending Signal.mp3",
    )
    run_id = test_data.playlist_generation_run()
    generated_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        name="Root Mix",
        position=1,
    )
    test_data.generated_playlist_track(
        generated_playlist_id=generated_playlist_id,
        local_track_id=generated_track_id,
    )

    export_package = build_full_rekordbox_xml_export_package(
        engine=engine,
        library_path="/export/music",
    )

    assert [playlist.archive_path_m3u for playlist in export_package.playlists] == [
        "YouTube Music/Road Trip [yt].m3u",
        f"Generated Runs/Generated Run {run_id}/Root Mix [gen].m3u",
    ]

    rekordbox_xml = ElementTree.fromstring(build_rekordbox_xml(export_package))
    root_node = rekordbox_xml.find("./PLAYLISTS/NODE")
    assert root_node is not None
    youtube_music_node = root_node.find("./NODE[@Name='YouTube Music']")
    generated_runs_node = root_node.find("./NODE[@Name='Generated Runs']")
    assert youtube_music_node is not None
    assert generated_runs_node is not None
    assert youtube_music_node.find("./NODE[@Type='1'][@Name='Match Only [yt]']") is None
    assert (
        youtube_music_node.find("./NODE[@Type='1'][@Name='Road Trip [yt]']") is not None
    )
    assert (
        generated_runs_node.find(
            f"./NODE[@Name='Generated Run {run_id}']/NODE[@Type='1'][@Name='Root Mix [gen]']"
        )
        is not None
    )


def test_full_rekordbox_xml_export_endpoint_returns_download(tmp_path: Path) -> None:
    engine = _create_generated_export_engine(tmp_path, "full-rekordbox-xml-route.db")
    router = create_router()
    payload = M3uExportRequest.model_validate({"library_path": "/mnt/music"})

    response = _call_endpoint(
        _route(router, "POST", "/m3u/export/rekordbox-xml/full").endpoint,
        payload,
        engine=engine,
    )

    assert response.media_type == "application/xml"
    assert (
        response.headers["Content-Disposition"]
        == 'attachment; filename="crate-lynx-rekordbox.xml"'
    )
    assert b"<DJ_PLAYLISTS" in response.body


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
