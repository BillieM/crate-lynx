from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from app.autopilot.models import metadata as autopilot_metadata
from app.autopilot.store import AutopilotStore
from app.sonic.benchmark import _selection_gate
from app.sonic.generation import (
    build_generation_preview,
    group_tracks,
    understand_tracks,
)
from app.sonic.models import metadata as sonic_metadata
from app.sonic.naming import select_intrinsic_style_label
from app.sonic.semantic import (
    _clap_onnx_inputs,
    deterministic_audio_windows,
    verify_model_asset,
)
from app.sonic.sequencing import sequence_track_indexes
from app.sonic.store import SonicReadyTrack, SonicStore
from sqlalchemy import create_engine


def _track(
    track_id: int,
    *,
    energy: float,
    semantic: list[float] | None = None,
    tag: str | None = None,
    tempo: float = 120.0,
) -> SonicReadyTrack:
    descriptors: dict[str, object] = {
        "onset_strength_mean": energy * 2,
        "rms_mean": 0.08 + energy * 0.28,
        "spectral_centroid_mean": 1000 + energy * 2000,
        "tempo_bpm": tempo,
    }
    if semantic is not None:
        descriptors.update(
            {
                "semantic_embedding": semantic,
                "semantic_model_key": "clap_onnx_v1",
                "semantic_model_revision": "test",
                "semantic_status": "ready",
            }
        )
    return SonicReadyTrack(
        local_track_id=track_id,
        descriptors=descriptors,
        tag_values=(tag,) if tag else (),
        vector=[tempo, energy],
        analyzer_version="2",
    )


def test_grouping_uses_hybrid_only_above_coverage_gate_and_never_genre() -> None:
    tracks = [
        _track(
            index,
            energy=0.2 if index <= 4 else 0.8,
            semantic=[1.0, 0.0] if index <= 4 else [0.0, 1.0],
            tag="Techno" if index % 2 else "Ambient",
        )
        for index in range(1, 9)
    ]
    config = {
        "max_depth": 1,
        "min_playlist_size": 2,
        "target_playlist_size": 4,
        "semantic_mode": "auto",
        "semantic_weight": 0.15,
    }
    hybrid = group_tracks(understand_tracks(tracks, config), config)
    retagged = [
        SonicReadyTrack(
            **{
                **{
                    field: getattr(track, field)
                    for field in (
                        "album",
                        "analyzer_version",
                        "artist",
                        "descriptors",
                        "local_track_id",
                        "title",
                        "vector",
                    )
                },
                "tag_values": ("Electronic",),
            }
        )
        for track in tracks
    ]
    retagged_result = group_tracks(
        understand_tracks(retagged, config),
        config,
    )

    assert hybrid.evidence["semantic_mode_used"] == "hybrid"
    assert hybrid.evidence["genre_metadata_used_for_grouping"] is False
    assert hybrid.clusters == retagged_result.clusters

    low_coverage = [
        track
        if index < 5
        else SonicReadyTrack(
            local_track_id=track.local_track_id,
            descriptors={
                key: value
                for key, value in track.descriptors.items()
                if not key.startswith("semantic_")
            },
            vector=track.vector,
            analyzer_version="1",
        )
        for index, track in enumerate(tracks)
    ]
    degraded = group_tracks(understand_tracks(low_coverage, config), config)
    assert degraded.evidence["semantic_mode_used"] == "descriptor_only"


def test_sequencing_intents_are_deterministic_and_energy_aware() -> None:
    tracks = [
        _track(index, energy=index / 10, tempo=105 + index * 3) for index in range(1, 7)
    ]
    matrix = [[float(index), float(index % 2)] for index in range(6)]
    indexes = list(range(6))

    rising, evidence = sequence_track_indexes(
        indexes,
        tracks,
        matrix,
        diversity_mode="balanced_v1",
        intent="rising_energy",
        random_seed=42,
    )
    varied, _ = sequence_track_indexes(
        indexes,
        tracks,
        matrix,
        diversity_mode="balanced_v1",
        intent="varied_listening",
        random_seed=42,
    )

    assert rising == indexes
    assert evidence["energy_end"] > evidence["energy_start"]
    assert varied != rising
    assert sorted(varied) == indexes


def test_style_naming_requires_specific_strong_acoustically_compatible_tags() -> None:
    base = {
        "bpm": {"median": 132},
        "track_count": 10,
    }
    assert (
        select_intrinsic_style_label(
            {**base, "common_tags": [{"value": "Electronic", "count": 10}]}
        )
        is None
    )
    assert (
        select_intrinsic_style_label(
            {**base, "common_tags": [{"value": "UK garage", "count": 7}]}
        )
        == "UK Garage"
    )
    assert (
        select_intrinsic_style_label(
            {
                **base,
                "common_tags": [
                    {"value": "UK garage", "count": 7},
                    {"value": "Techno", "count": 6},
                ],
            }
        )
        is None
    )


def test_actual_preview_contains_candidate_and_readiness_evidence() -> None:
    tracks = [
        _track(
            index,
            energy=0.2 if index <= 4 else 0.8,
            semantic=[1.0, 0.0] if index <= 4 else [0.0, 1.0],
            tag="UK Garage",
            tempo=130 + index % 3,
        )
        for index in range(1, 9)
    ]
    preview = build_generation_preview(
        tracks,
        {
            "max_depth": 1,
            "min_playlist_size": 2,
            "target_playlist_size": 4,
        },
        failed_feature_count=1,
        missing_feature_count=1,
        pending_feature_count=0,
        source_track_count=10,
    )

    assert preview["coverage"] == 0.8
    assert preview["readiness"]["safe_for_automatic_regeneration"] is True
    assert preview["skipped_reasons"] == {
        "analysis_failed": 1,
        "analysis_missing": 1,
    }
    assert preview["playlists"]
    candidate = preview["playlists"][0]
    assert candidate["name"].startswith("UK Garage /")
    assert candidate["representative_tracks"]
    assert candidate["boundary_tracks"] == candidate["outlier_tracks"]
    assert candidate["sequencing_intent"] == "smooth_mix"
    assert isinstance(candidate["cohesion"], float)


def test_named_recipe_store_round_trip_and_regeneration_reference(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'recipes.db'}")
    sonic_metadata.create_all(engine)
    store = SonicStore(engine=engine)

    recipe = store.create_generation_recipe(
        enabled=True,
        export_config=None,
        generation_config={"sequencing_intent": "smooth_mix"},
        name="Friday UKG",
        regenerate_on_change=True,
        source_filter={"source_type": "all_local"},
    )
    run = store.create_generation_run(
        generation_config=recipe.generation_config_json,
        recipe_id=recipe.id,
        run_name=recipe.name,
        source_filter=recipe.source_filter_json,
        trigger="recipe",
    )
    store.mark_generation_recipe_regenerated(recipe.id, run_id=run.id)

    refreshed = store.get_generation_recipe(recipe.id)
    assert refreshed is not None
    assert refreshed.name == "Friday UKG"
    assert refreshed.last_run_id == run.id
    assert store.get_generation_run(run.id).run_name == "Friday UKG"

    store.delete_generation_recipe(recipe.id)
    assert store.get_generation_recipe(recipe.id) is None
    assert store.get_generation_run(run.id).recipe_id is None


def test_deleting_recipe_cancels_pending_debounce_and_finishes_origin_run(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'recipe-debounce-delete.db'}")
    sonic_metadata.create_all(engine)
    autopilot_metadata.create_all(engine)
    sonic_store = SonicStore(engine=engine)
    autopilot_store = AutopilotStore(engine=engine)
    recipe = sonic_store.create_generation_recipe(
        enabled=True,
        export_config=None,
        generation_config={"sequencing_intent": "smooth_mix"},
        name="Delete pending recipe",
        regenerate_on_change=True,
        source_filter={"source_type": "all_local"},
    )
    run, _ = autopilot_store.get_or_create_run(
        dry_run=False,
        idempotency_key="scheduled:60:deleted-recipe",
        trigger="scheduled",
    )
    autopilot_store.update_run(run.id, status="running")
    pending, _ = autopilot_store.upsert_recipe_debounce(
        run_id=run.id,
        recipe_id=recipe.id,
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        detail="Pending recipe regeneration",
    )

    sonic_store.delete_generation_recipe(recipe.id)

    cancelled = autopilot_store.get_run_item(pending.id)
    finished = autopilot_store.get_run(run.id)
    assert cancelled is not None
    assert cancelled.status == "skipped"
    assert cancelled.recipe_id is None
    assert cancelled.reason_code == "recipe_deleted"
    assert cancelled.next_attempt_at is None
    assert finished is not None
    assert finished.status == "succeeded"
    assert finished.finished_at is not None
    assert autopilot_store.due_retry_items() == []


def test_clap_preprocessing_and_windows_are_deterministic_without_torch() -> None:
    waveform = np.linspace(-0.5, 0.5, 960_000, dtype=np.float32)
    first = deterministic_audio_windows(
        waveform,
        sample_rate=48_000,
        window_seconds=10,
    )
    second = deterministic_audio_windows(
        waveform,
        sample_rate=48_000,
        window_seconds=10,
    )

    assert len(first) == 3
    assert all(np.array_equal(left, right) for left, right in zip(first, second))
    inputs = _clap_onnx_inputs(first[0])
    assert inputs["input_features"].shape == (1, 1, 1001, 64)
    assert inputs["input_features"].dtype == np.float32


def test_model_asset_verifier_rejects_unpinned_file(tmp_path: Path) -> None:
    model_path = tmp_path / "audio_model.onnx"
    model_path.write_bytes(b"not the pinned model")

    with pytest.raises(RuntimeError, match="size mismatch"):
        verify_model_asset(model_path)


def test_benchmark_gate_requires_representative_scale_invariant_evidence() -> None:
    variants = {
        "descriptor_only": {
            "boundary_stability": 0.8,
            "clustering": {
                "separation_to_cohesion_ratio": 1.0,
                "specific_tag_pair_agreement": 0.5,
            },
            "evidence": {"semantic_mode_used": "descriptor_only"},
        },
        "hybrid": {
            "boundary_stability": 0.75,
            "clustering": {
                "separation_to_cohesion_ratio": 0.95,
                "specific_tag_pair_agreement": 0.48,
            },
            "evidence": {"semantic_mode_used": "hybrid"},
        },
    }

    assert _selection_gate(variants, sample_count=47)["hybrid_selected"] is False
    assert _selection_gate(variants, sample_count=48)["hybrid_selected"] is True
