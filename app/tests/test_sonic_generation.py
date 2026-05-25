from __future__ import annotations

from sqlalchemy import create_engine

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.links.store import metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.exporter import build_m3u_export_package
from app.sonic.generation import _playlist_name, generate_playlist_tree
from app.sonic.jobs import run_playlist_generation_job
from app.sonic.models import (
    SONIC_ANALYZER_LIBROSA_V1,
    SONIC_FEATURE_STATUS_FAILED,
    SONIC_FEATURE_STATUS_PENDING,
    metadata as sonic_metadata,
)
from app.sonic.profiles import resolve_feature_profile
from app.sonic.store import SonicReadyTrack, SonicStore
from app.streaming.models import metadata as streaming_metadata
from tests.factories import TestDataFactory


def _naming_tracks(count: int = 48) -> list[SonicReadyTrack]:
    return [
        SonicReadyTrack(
            descriptors={
                "mfcc_01_mean": float((index % 5) - 2),
                "rms_mean": float(0.2 + (index % 3) * 0.2),
                "spectral_centroid_mean": float(1200 + (index % 4) * 350),
                "tempo_bpm": float(82 + (index % 6) * 12),
            },
            local_track_id=index,
            tag_values=("ambient dub",),
            vector=[float(index)],
        )
        for index in range(1, count + 1)
    ]


def _separated_dj_tracks(
    cluster_count: int,
    tracks_per_cluster: int,
) -> list[SonicReadyTrack]:
    tracks = []
    local_track_id = 1
    for cluster_index in range(cluster_count):
        tempo = 92.0 + cluster_index * 18.0
        rms = 0.12 + cluster_index * 0.08
        centroid = 1000.0 + cluster_index * 900.0
        for offset in range(tracks_per_cluster):
            tracks.append(
                SonicReadyTrack(
                    descriptors={
                        "onset_strength_mean": 0.45 + cluster_index * 0.35,
                        "rms_mean": rms + (offset % 2) * 0.01,
                        "spectral_bandwidth_mean": 1400.0 + cluster_index * 500.0,
                        "spectral_centroid_mean": centroid + (offset % 3) * 20.0,
                        "tempo_bpm": tempo + (offset % 3) * 0.5,
                    },
                    local_track_id=local_track_id,
                    tag_values=(f"style {cluster_index + 1}",),
                    vector=[tempo, rms, centroid],
                )
            )
            local_track_id += 1
    return tracks


def _dj_hierarchical_config(
    *,
    max_children: int = 4,
    min_playlist_size: int = 4,
    target_playlist_size: int = 8,
) -> dict[str, object]:
    return {
        "clustering_method": "dj_hierarchical_v1",
        "max_children": max_children,
        "max_depth": 1,
        "min_playlist_size": min_playlist_size,
        "random_seed": 7,
        "target_playlist_size": target_playlist_size,
    }


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


def test_feature_profiles_resolve_distinct_weighted_inputs() -> None:
    balanced = resolve_feature_profile("balanced_v1")
    energy = resolve_feature_profile("energy_v1")
    harmony = resolve_feature_profile("harmony_v1")

    assert balanced.descriptor_weights["tempo_bpm"] == 1.0
    assert (
        energy.descriptor_weights["tempo_bpm"]
        > energy.descriptor_weights["chroma_00_mean"]
    )
    assert (
        harmony.descriptor_weights["chroma_00_mean"]
        > harmony.descriptor_weights["tempo_bpm"]
    )


def test_dj_hierarchical_auto_k_selects_target_sized_clusters() -> None:
    for cluster_count in (2, 3, 4):
        drafts = generate_playlist_tree(
            _separated_dj_tracks(cluster_count, tracks_per_cluster=8),
            _dj_hierarchical_config(target_playlist_size=8),
        )

        assert len(drafts) == cluster_count
        assert [len(draft["track_ids"]) for draft in drafts] == [8] * cluster_count
        assert all(draft["summary"]["naming"]["discriminators"] for draft in drafts)


def test_dj_hierarchical_keeps_weak_non_forced_split_as_single_playlist() -> None:
    tracks = [
        SonicReadyTrack(
            descriptors={
                "onset_strength_mean": 0.8,
                "rms_mean": 0.2,
                "spectral_centroid_mean": 1800.0,
                "tempo_bpm": 118.0,
            },
            local_track_id=index,
            vector=[118.0, 0.2, 1800.0],
        )
        for index in range(1, 17)
    ]

    drafts = generate_playlist_tree(
        tracks,
        _dj_hierarchical_config(target_playlist_size=8),
    )

    assert len(drafts) == 1
    assert len(drafts[0]["track_ids"]) == 16


def test_dj_hierarchical_names_use_relative_sibling_discriminators() -> None:
    drafts = generate_playlist_tree(
        _separated_dj_tracks(4, tracks_per_cluster=8),
        _dj_hierarchical_config(target_playlist_size=8),
    )
    names = [draft["name"] for draft in drafts]
    leading_labels = [name.split(" / ", maxsplit=1)[0] for name in names]

    assert len(names) == len({name.casefold() for name in names})
    assert len(leading_labels) == len(set(leading_labels))
    assert all(
        draft["summary"]["naming"]["discriminators"]
        == draft["summary"]["name_components"]["differentiators"]
        for draft in drafts
    )
    assert any(
        "Slowest" in leading_label or "Fastest" in leading_label
        for leading_label in leading_labels
    )


def test_generate_playlist_tree_orders_tracks_with_metadata_diversity() -> None:
    tracks = [
        SonicReadyTrack(
            album="A",
            artist="Artist A",
            descriptors={"tempo_bpm": 120.0},
            local_track_id=1,
            title="A1",
            vector=[120.0],
        ),
        SonicReadyTrack(
            album="A",
            artist="Artist A",
            descriptors={"tempo_bpm": 120.0},
            local_track_id=2,
            title="A2",
            vector=[120.0],
        ),
        SonicReadyTrack(
            album="B",
            artist="Artist B",
            descriptors={"tempo_bpm": 120.0},
            local_track_id=3,
            title="B1",
            vector=[120.0],
        ),
        SonicReadyTrack(
            album="B",
            artist="Artist B",
            descriptors={"tempo_bpm": 120.0},
            local_track_id=4,
            title="B2",
            vector=[120.0],
        ),
    ]

    drafts = generate_playlist_tree(
        tracks,
        {
            "clustering_method": "kmeans",
            "max_depth": 1,
            "target_playlist_size": 25,
            "min_playlist_size": 2,
            "max_children": 2,
            "random_seed": 7,
        },
    )

    ordered_artists = [
        next(track.artist for track in tracks if track.local_track_id == track_id)
        for track_id in drafts[0]["track_ids"]
    ]
    assert ordered_artists in (
        ["Artist A", "Artist B", "Artist A", "Artist B"],
        ["Artist B", "Artist A", "Artist B", "Artist A"],
    )
    assert (
        drafts[0]["summary"]["ordering_strategy"]
        == "profile_nearest_neighbor_rolling_v2"
    )
    assert len(drafts[0]["summary"]["representative_tracks"]) == 3


def test_generate_playlist_tree_parent_labels_use_style_and_bpm_range() -> None:
    tracks = [
        SonicReadyTrack(
            descriptors={"tempo_bpm": tempo},
            local_track_id=index,
            tag_values=("ambient dub",),
            vector=[tempo],
        )
        for index, tempo in enumerate((84.0, 90.0, 96.0, 102.0), start=1)
    ]

    drafts = generate_playlist_tree(tracks, {"max_depth": 1})

    assert drafts[0]["name"] == "Ambient Dub / 84-102 BPM"
    assert drafts[0]["summary"]["bpm"] == {
        "average": 93.0,
        "count": 4,
        "full_range_label": "84-102 BPM",
        "label": "84-102 BPM",
        "label_basis": "full_range",
        "label_max": 102,
        "label_min": 84,
        "max": 102,
        "median": 93,
        "min": 84,
    }
    assert drafts[0]["summary"]["common_tags"] == [{"count": 4, "value": "ambient dub"}]
    assert drafts[0]["summary"]["naming"]["style"] == "Ambient Dub"
    assert drafts[0]["summary"]["naming"]["tempo"] == "84-102 BPM"


def test_playlist_name_child_labels_use_dj_role_and_traits() -> None:
    name, debug = _playlist_name(
        {
            "bpm": {
                "average": 92.0,
                "count": 8,
                "label": "84-102 BPM",
                "max": 102,
                "median": 92,
                "min": 84,
            },
            "common_tags": [{"count": 8, "value": "ambient dub"}],
            "descriptor_means": {},
            "energy": {
                "band": "Low Energy",
                "delta_from_parent": -0.2,
                "score": 0.24,
            },
            "top_deltas": [
                {
                    "delta": -500.0,
                    "key": "spectral_centroid_mean",
                }
            ],
            "track_count": 8,
        },
        1,
        parent_name="Ambient Dub / 84-102 BPM",
        used_names=set(),
    )

    assert name == "Warm-up / Low Energy + Warm"
    assert debug["components"]["role"] == "Warm-up"
    assert debug["components"]["traits"] == ["Warm"]
    assert debug["components"]["energy"]["band"] == "Low Energy"


def test_generate_playlist_tree_uses_compact_bpm_label_for_wide_ranges() -> None:
    tempos = (
        66.0,
        80.0,
        90.0,
        117.0,
        123.0,
        123.0,
        129.0,
        129.0,
        136.0,
        144.0,
        161.0,
        172.0,
    )
    tracks = [
        SonicReadyTrack(
            descriptors={"tempo_bpm": tempo, "rms_mean": 0.28},
            local_track_id=index,
            vector=[tempo, 0.28],
        )
        for index, tempo in enumerate(tempos, start=1)
    ]

    drafts = generate_playlist_tree(tracks, {"max_depth": 1})

    bpm = drafts[0]["summary"]["bpm"]
    assert bpm["full_range_label"] == "66-172 BPM"
    assert bpm["label"] == "117-136 BPM"
    assert bpm["label_basis"] == "central_range"
    assert "66-172 BPM" not in drafts[0]["name"]


def test_generate_playlist_tree_names_surface_sibling_differentiators() -> None:
    low_energy_tracks = [
        SonicReadyTrack(
            descriptors={
                "onset_strength_mean": 0.5,
                "rms_mean": 0.12,
                "spectral_bandwidth_mean": 1400.0,
                "spectral_centroid_mean": 1000.0,
                "tempo_bpm": 96.0,
            },
            local_track_id=index,
            vector=[96.0, 0.12],
        )
        for index in range(1, 9)
    ]
    high_energy_tracks = [
        SonicReadyTrack(
            descriptors={
                "onset_strength_mean": 1.8,
                "rms_mean": 0.34,
                "spectral_bandwidth_mean": 3400.0,
                "spectral_centroid_mean": 3200.0,
                "tempo_bpm": 132.0,
            },
            local_track_id=index,
            vector=[132.0, 0.34],
        )
        for index in range(9, 17)
    ]

    drafts = generate_playlist_tree(
        [*low_energy_tracks, *high_energy_tracks],
        {
            "max_children": 2,
            "max_depth": 1,
            "min_playlist_size": 4,
            "random_seed": 3,
            "target_playlist_size": 8,
        },
    )
    names = [draft["name"] for draft in drafts]

    assert len(drafts) == 2
    assert all(draft["summary"]["sibling_differentiators"] for draft in drafts)
    assert any(
        "Fastest" in name or "Highest Energy" in name or "Brightest" in name
        for name in names
    )
    assert any(
        "Slowest" in name or "Lowest Energy" in name or "Warmest" in name
        for name in names
    )


def test_generate_playlist_tree_uses_unique_names_across_run() -> None:
    drafts = generate_playlist_tree(
        _naming_tracks(),
        {
            "clustering_method": "kmeans",
            "max_depth": 2,
            "target_playlist_size": 6,
            "min_playlist_size": 3,
            "max_children": 4,
            "random_seed": 11,
        },
    )

    names = [draft["name"] for draft in drafts]

    assert len(drafts) > 4
    assert len(names) == len({name.casefold() for name in names})
    assert all("name_components" in draft["summary"] for draft in drafts)
    assert all("name_strategy" in draft["summary"] for draft in drafts)
    assert all("naming" in draft["summary"] for draft in drafts)


def test_generate_playlist_tree_names_are_deterministic() -> None:
    config = {
        "clustering_method": "kmeans",
        "max_depth": 2,
        "target_playlist_size": 6,
        "min_playlist_size": 3,
        "max_children": 4,
        "random_seed": 11,
    }

    first_drafts = generate_playlist_tree(_naming_tracks(), config)
    second_drafts = generate_playlist_tree(_naming_tracks(), config)

    assert [
        (
            draft["name"],
            draft["summary"]["name_components"],
            draft["summary"]["name_strategy"],
        )
        for draft in first_drafts
    ] == [
        (
            draft["name"],
            draft["summary"]["name_components"],
            draft["summary"]["name_strategy"],
        )
        for draft in second_drafts
    ]


def test_generate_playlist_tree_names_require_dominant_tags() -> None:
    sparse_tag_tracks = [
        SonicReadyTrack(
            descriptors={"tempo_bpm": 90.0},
            local_track_id=index,
            tag_values=("ambient dub",) if index == 1 else (),
            vector=[90.0],
        )
        for index in range(1, 6)
    ]
    dominant_tag_tracks = [
        SonicReadyTrack(
            descriptors={"tempo_bpm": 90.0},
            local_track_id=index,
            tag_values=("ambient dub",) if index <= 2 else (),
            vector=[90.0],
        )
        for index in range(1, 6)
    ]

    sparse_drafts = generate_playlist_tree(sparse_tag_tracks, {"max_depth": 1})
    dominant_drafts = generate_playlist_tree(dominant_tag_tracks, {"max_depth": 1})

    assert sparse_drafts[0]["summary"]["common_tags"] == [
        {"count": 1, "value": "ambient dub"}
    ]
    assert sparse_drafts[0]["summary"]["name_components"]["style"] is None
    assert sparse_drafts[0]["name"] == "90 BPM / Low Energy"
    assert dominant_drafts[0]["summary"]["name_components"]["style"] == "Ambient Dub"
    assert dominant_drafts[0]["name"] == "Ambient Dub / 90 BPM"


def test_generate_playlist_tree_fallback_names_without_tags_are_dj_useful() -> None:
    tracks = [
        SonicReadyTrack(
            artist="Artist A" if index % 2 else "Artist B",
            descriptors={"tempo_bpm": 120.0, "rms_mean": 0.22},
            local_track_id=index,
            title=f"Track {index}",
            vector=[120.0],
        )
        for index in range(1, 5)
    ]

    drafts = generate_playlist_tree(tracks, {"max_depth": 1})

    assert drafts[0]["name"] == "120 BPM / Medium Energy"
    assert drafts[0]["summary"]["name_components"]["style"] is None
    assert drafts[0]["summary"]["name_components"]["energy"]["band"] == "Medium Energy"


def test_generate_playlist_tree_does_not_use_artist_or_title_as_primary_name() -> None:
    tracks = [
        SonicReadyTrack(
            artist="Anchor Artist",
            descriptors={"tempo_bpm": 126.0, "rms_mean": 0.5},
            local_track_id=index,
            title="Anchor Track",
            vector=[126.0, 0.5],
        )
        for index in range(1, 5)
    ]

    drafts = generate_playlist_tree(tracks, {"max_depth": 1})

    assert "Anchor Artist" not in drafts[0]["name"]
    assert "Anchor Track" not in drafts[0]["name"]
    assert drafts[0]["name"] == "126 BPM / High Energy"
    assert drafts[0]["summary"]["representative_tracks"]
    assert all(
        track["artist"] == "Anchor Artist" and track["title"] == "Anchor Track"
        for track in drafts[0]["summary"]["representative_tracks"]
    )


def test_playlist_name_uses_parent_context_before_numeric_suffix() -> None:
    name, debug = _playlist_name(
        {
            "common_tags": [],
            "top_deltas": [
                {
                    "delta": 100.0,
                    "key": "spectral_centroid_mean",
                }
            ],
        },
        1,
        parent_name="Warm Open",
        used_names={"bright", "dj utility split"},
    )

    assert name == "Bright / Warm Open"
    assert debug["strategy"] == "dj_utility_contextual_parent"


def test_generate_playlist_tree_falls_back_without_name_signals() -> None:
    tracks = [
        SonicReadyTrack(
            descriptors={},
            local_track_id=index,
            vector=[0.0],
        )
        for index in range(1, 5)
    ]

    drafts = generate_playlist_tree(tracks, {"max_depth": 1})

    assert drafts[0]["name"] == "Sonic DJ Crate"
    assert drafts[0]["summary"]["name_components"] == {
        "bpm": {},
        "differentiators": [],
        "energy": {},
        "role": None,
        "style": None,
        "tag": None,
        "tempo": None,
        "trait_sources": [],
        "texture_traits": [],
        "traits": [],
    }


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


def test_generation_preview_counts_source_feature_readiness(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'sonic-preview.db'}")
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    ready_track_id = factory.local_track(file_path="Ready.mp3")
    pending_track_id = factory.local_track(file_path="Pending.mp3")
    failed_track_id = factory.local_track(file_path="Failed.mp3")
    incompatible_track_id = factory.local_track(file_path="Old.mp3")
    factory.local_track(file_path="Missing.mp3")
    factory.sonic_track_feature(local_track_id=ready_track_id)
    factory.sonic_track_feature(
        local_track_id=pending_track_id,
        status=SONIC_FEATURE_STATUS_PENDING,
    )
    factory.sonic_track_feature(
        local_track_id=failed_track_id,
        status=SONIC_FEATURE_STATUS_FAILED,
    )
    factory.sonic_track_feature(
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="0",
        local_track_id=incompatible_track_id,
    )

    preview = SonicStore(engine=engine).generation_preview(
        {"source_type": "all_local"},
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="1",
        feature_profile="balanced_v1",
    )

    assert preview.source_track_count == 5
    assert preview.ready_track_count == 1
    assert preview.missing_feature_count == 1
    assert preview.pending_feature_count == 1
    assert preview.failed_feature_count == 1
    assert preview.skipped_track_count == 4
    assert preview.can_generate is True


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


def test_playlist_generation_job_excludes_incompatible_features(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'sonic-generation-job.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    factory = TestDataFactory(engine)
    ready_track_id = factory.local_track(beets_id=1, file_path="Ready.mp3")
    incompatible_track_id = factory.local_track(beets_id=2, file_path="Old.mp3")
    factory.beets_item(beets_id=1, title="Ready", artist="A")
    factory.beets_item(beets_id=2, title="Old", artist="B")
    factory.sonic_track_feature(
        descriptor_json={"tempo_bpm": 120.0, "rms_mean": 0.6},
        local_track_id=ready_track_id,
        vector_json=[120.0, 0.6],
    )
    factory.sonic_track_feature(
        analyzer_version="0",
        descriptor_json={"tempo_bpm": 90.0, "rms_mean": 0.2},
        local_track_id=incompatible_track_id,
        vector_json=[90.0, 0.2],
    )
    run_id = factory.playlist_generation_run(
        generation_config_json={
            "clustering_method": "kmeans",
            "feature_profile": "balanced_v1",
            "max_children": 2,
            "max_depth": 1,
            "min_playlist_size": 1,
            "random_seed": 42,
            "target_playlist_size": 25,
        },
        source_filter_json={"source_type": "all_local"},
        status="pending",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert run_playlist_generation_job(run_id) == run_id

    store = SonicStore(engine=engine)
    run = store.get_generation_run(run_id)
    playlists = store.list_generated_playlists(run_id=run_id)

    assert run is not None
    assert run.track_count == 1
    assert playlists[0].summary_json["source_summary"] == {
        "failed_feature_count": 0,
        "missing_feature_count": 0,
        "pending_feature_count": 0,
        "ready_track_count": 1,
        "skipped_track_count": 1,
        "source_track_count": 2,
    }
    assert [
        track.local_track_id
        for track in store.list_generated_playlist_tracks(playlists[0].id)
    ] == [ready_track_id]


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
        name="Ambient Dub / 84-102 BPM",
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
    assert (
        export_package.playlists[0].filename_m3u == "Ambient Dub - 84-102 BPM [gen].m3u"
    )
    assert (
        "/mnt/music/Frame Delay/Night Runner.mp3"
        in export_package.playlists[0].rendered.content
    )
