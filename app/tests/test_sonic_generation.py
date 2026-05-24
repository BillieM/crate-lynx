from __future__ import annotations

from sqlalchemy import create_engine

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.links.store import metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.exporter import build_m3u_export_package
from app.sonic.generation import generate_playlist_tree
from app.sonic.models import metadata as sonic_metadata
from app.sonic.store import SonicReadyTrack, SonicStore
from app.streaming.models import metadata as streaming_metadata
from tests.factories import TestDataFactory


def test_generate_playlist_tree_persists_parent_child_membership_in_drafts() -> None:
    tracks = [
        SonicReadyTrack(
            local_track_id=index + 1,
            descriptors={
                "tempo_bpm": float(90 + index),
                "rms_mean": float(index % 5) / 10,
            },
            vector=[float(index), float(index % 5)],
        )
        for index in range(32)
    ]

    drafts = generate_playlist_tree(
        tracks,
        {
            "clustering_method": "kmeans",
            "max_depth": 2,
            "target_playlist_size": 6,
            "min_playlist_size": 3,
            "max_children": 4,
            "random_seed": 7,
        },
    )

    top_level = [draft for draft in drafts if draft["parent_key"] is None]
    children = [draft for draft in drafts if draft["parent_key"] is not None]

    assert len(top_level) > 1
    assert children
    for parent in top_level:
        child_union = {
            track_id
            for child in children
            if child["parent_key"] == parent["client_key"]
            for track_id in child["track_ids"]
        }
        if child_union:
            assert child_union == set(parent["track_ids"])
    assert all(draft["name"] for draft in drafts)


def test_ready_tracks_for_source_filters_by_beets_item_attribute(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'sonic-source.db'}")
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    ambient_track_id = factory.local_track(beets_id=1, file_path="A/Ambient.mp3")
    techno_track_id = factory.local_track(beets_id=2, file_path="B/Techno.mp3")
    missing_feature_track_id = factory.local_track(beets_id=3, file_path="C/Other.mp3")
    factory.beets_item(beets_id=1, title="Ambient", artist="A")
    factory.beets_item(beets_id=2, title="Techno", artist="B")
    factory.beets_item(beets_id=3, title="Other", artist="C")
    factory.beets_item_attribute(beets_id=1, key="genre", value="ambient dub")
    factory.beets_item_attribute(beets_id=2, key="genre", value="techno")
    factory.beets_item_attribute(beets_id=3, key="genre", value="ambient")
    factory.sonic_track_feature(
        local_track_id=ambient_track_id,
        descriptor_json={"tempo_bpm": 92.0},
        vector_json=[92.0],
    )
    factory.sonic_track_feature(
        local_track_id=techno_track_id,
        descriptor_json={"tempo_bpm": 130.0},
        vector_json=[130.0],
    )

    tracks = SonicStore(engine=engine).ready_tracks_for_source(
        {
            "source_type": "all_local",
            "tag_filters": [
                {
                    "scope": "item_attribute",
                    "key": "genre",
                    "value": "ambient",
                    "match": "contains",
                }
            ],
        }
    )

    assert [track.local_track_id for track in tracks] == [ambient_track_id]
    assert missing_feature_track_id not in [track.local_track_id for track in tracks]


def test_replace_generated_playlists_persists_tree_and_tracks(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'sonic-run.db'}")
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    first_track_id = factory.local_track(file_path="A/One.mp3")
    second_track_id = factory.local_track(file_path="B/Two.mp3")
    run_id = factory.playlist_generation_run()

    SonicStore(engine=engine).replace_generated_playlists(
        run_id=run_id,
        track_count=2,
        playlists=[
            {
                "client_key": "root-0-1",
                "parent_key": None,
                "depth": 0,
                "position": 1,
                "name": "Fast Bright",
                "summary": {"top_deltas": []},
                "track_ids": [first_track_id, second_track_id],
            },
            {
                "client_key": "root-0-1-1-1",
                "parent_key": "root-0-1",
                "depth": 1,
                "position": 1,
                "name": "Fast",
                "summary": {"top_deltas": []},
                "track_ids": [first_track_id],
            },
        ],
    )

    store = SonicStore(engine=engine)
    run = store.get_generation_run(run_id)
    playlists = store.list_generated_playlists(run_id=run_id)
    parent = playlists[0]
    child = playlists[1]

    assert run is not None
    assert run.status == "completed"
    assert run.playlist_count == 2
    assert parent.parent_playlist_id is None
    assert child.parent_playlist_id == parent.id
    assert [
        track.local_track_id
        for track in store.list_generated_playlist_tracks(parent.id)
    ] == [first_track_id, second_track_id]


def test_generated_playlist_can_be_exported_as_m3u(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'generated-m3u.db'}")
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    local_track_id = factory.local_track(
        beets_id=1,
        file_path="Frame Delay/Night Runner.mp3",
        library_root_rel_path="Frame Delay/Night Runner.mp3",
    )
    factory.beets_item(
        beets_id=1,
        title="Night Runner",
        artist="Frame Delay",
        album="Late Night Drive",
        length=214.0,
    )
    run_id = factory.playlist_generation_run()
    generated_playlist_id = factory.generated_playlist(
        run_id=run_id,
        name="Fast Bright",
        track_count=1,
    )
    factory.generated_playlist_track(
        generated_playlist_id=generated_playlist_id,
        local_track_id=local_track_id,
    )

    export_package = build_m3u_export_package(
        engine=engine,
        formats=["m3u"],
        generated_playlist_ids=[generated_playlist_id],
        library_path="/mnt/music",
        playlist_ids=[],
    )

    assert export_package.playlists[0].source == "generated"
    assert export_package.playlists[0].filename_m3u == "Fast Bright [gen].m3u"
    assert (
        "/mnt/music/Frame Delay/Night Runner.mp3"
        in export_package.playlists[0].rendered.content
    )
