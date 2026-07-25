from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import tracemalloc
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from app.sonic.generation import group_tracks, understand_tracks
from app.sonic.jobs import _resolve_local_audio_path
from app.sonic.semantic import (
    build_semantic_embedder_from_environment,
    semantic_cache_payload,
)
from app.sonic.store import SonicReadyTrack, SonicStore


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only descriptor vs hybrid Sonic generator benchmark."
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--sample-limit", type=int, default=72, choices=range(48, 97))
    parser.add_argument("--compute-missing-semantic", action="store_true")
    parser.add_argument(
        "--semantic-weights",
        type=float,
        nargs="+",
        default=(0.15, 0.25, 0.35, 0.5),
        help="Hybrid semantic weights to compare against descriptor-only grouping.",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    report = run_benchmark(
        database_url=arguments.database_url,
        sample_limit=arguments.sample_limit,
        compute_missing_semantic=arguments.compute_missing_semantic,
        semantic_weights=tuple(arguments.semantic_weights),
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output is not None:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def run_benchmark(
    *,
    database_url: str,
    sample_limit: int,
    compute_missing_semantic: bool,
    semantic_weights: tuple[float, ...] = (0.15, 0.25, 0.35, 0.5),
) -> dict[str, Any]:
    store = SonicStore(database_url)
    tracks = store.ready_tracks_for_source({"source_type": "all_local"})
    sampled = _stratified_sample(tracks, sample_limit)
    semantic_timings: list[float] = []
    semantic_failures: Counter[str] = Counter()
    if compute_missing_semantic:
        embedder = build_semantic_embedder_from_environment()
        if embedder is None:
            raise RuntimeError(
                "SONIC_SEMANTIC_ENABLED must be true to compute missing embeddings"
            )
        updated = []
        for track in sampled:
            if isinstance(track.descriptors.get("semantic_embedding"), list):
                updated.append(track)
                continue
            started = perf_counter()
            try:
                result = embedder.embed(
                    _resolve_local_audio_path(store, track.local_track_id)
                )
            except Exception as exc:  # noqa: BLE001 - benchmark records all failures
                semantic_failures[type(exc).__name__] += 1
                updated.append(track)
            else:
                semantic_timings.append(perf_counter() - started)
                updated.append(
                    replace(
                        track,
                        descriptors={
                            **track.descriptors,
                            **semantic_cache_payload(result),
                        },
                    )
                )
        sampled = updated

    base_config = {
        "max_depth": 2,
        "max_children": 4,
        "min_playlist_size": 6,
        "target_playlist_size": 18,
        "output_scope": "leaf_only_v1",
    }
    variants = {
        "descriptor_only": _measure_variant(
            sampled, {**base_config, "semantic_mode": "off"}
        )
    }
    for semantic_weight in sorted(set(semantic_weights)):
        if not 0 < semantic_weight <= 0.75:
            raise ValueError(
                "semantic benchmark weights must be greater than 0 and <= 0.75"
            )
        name = f"hybrid_{semantic_weight:.2f}".replace(".", "_")
        variants[name] = _measure_variant(
            sampled,
            {
                **base_config,
                "semantic_mode": "auto",
                "semantic_weight": semantic_weight,
            },
        )

    fallback_tracks = [
        replace(
            track,
            descriptors={
                key: value
                for key, value in track.descriptors.items()
                if not key.startswith("semantic_")
            },
        )
        for track in sampled
    ]
    fallback = group_tracks(
        understand_tracks(fallback_tracks, {**base_config, "semantic_mode": "auto"}),
        {**base_config, "semantic_mode": "auto"},
    )
    return {
        "benchmark_version": "sonic-generator-v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "privacy": {
            "identifiers_emitted": False,
            "paths_emitted": False,
            "titles_emitted": False,
        },
        "sample": {
            "available_ready_tracks": len(tracks),
            "sample_count": len(sampled),
            "sample_limit": sample_limit,
            "strata": _strata_counts(sampled),
        },
        "semantic_inference": {
            "computed_count": len(semantic_timings),
            "cold_seconds": (
                round(semantic_timings[0], 4) if semantic_timings else None
            ),
            "warm_mean_seconds": (
                round(sum(semantic_timings[1:]) / len(semantic_timings[1:]), 4)
                if len(semantic_timings) > 1
                else None
            ),
            "failure_counts": dict(sorted(semantic_failures.items())),
        },
        "variants": variants,
        "missing_model_fallback": {
            "mode_used": fallback.evidence.get("semantic_mode_used"),
            "passed": fallback.evidence.get("semantic_mode_used") == "descriptor_only",
        },
        "selection_gate": _selection_gate(
            variants,
            sample_count=len(sampled),
        ),
    }


def _measure_variant(
    tracks: list[SonicReadyTrack],
    config: dict[str, Any],
) -> dict[str, Any]:
    tracemalloc.start()
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = perf_counter()
    understanding = understand_tracks(tracks, config)
    grouped = group_tracks(understanding, config)
    elapsed = perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    metrics = _cluster_metrics(grouped.matrix, grouped.clusters, tracks)
    return {
        "clustering": metrics,
        "evidence": grouped.evidence,
        "runtime_seconds": round(elapsed, 4),
        "python_peak_memory_mb": round(peak_bytes / (1024 * 1024), 3),
        "rss_growth_mb": round(max(0, rss_after - rss_before) / 1024, 3),
        "boundary_stability": _boundary_stability(tracks, config),
    }


def _cluster_metrics(
    matrix: list[list[float]],
    clusters: list[list[int]],
    tracks: list[SonicReadyTrack],
) -> dict[str, Any]:
    centroids = [
        _centroid([matrix[index] for index in cluster]) for cluster in clusters
    ]
    intra = [
        _distance(matrix[index], centroid)
        for cluster, centroid in zip(clusters, centroids, strict=True)
        for index in cluster
    ]
    inter = [
        _distance(left, right)
        for left_index, left in enumerate(centroids)
        for right_index, right in enumerate(centroids)
        if left_index < right_index
    ]
    cohesion = sum(intra) / max(1, len(intra))
    separation = min(inter) if inter else 0.0
    tag_scores = []
    for cluster in clusters:
        tags = [_specific_tags(tracks[index]) for index in cluster]
        for left_index, left in enumerate(tags):
            for right in tags[left_index + 1 :]:
                if left or right:
                    tag_scores.append(bool(left & right))
    return {
        "cluster_count": len(clusters),
        "cohesion_mean_distance": round(cohesion, 4),
        "separation_min_distance": round(separation, 4),
        "separation_to_cohesion_ratio": round(
            separation / max(cohesion, 1e-9),
            4,
        ),
        "specific_tag_pair_agreement": (
            round(sum(tag_scores) / len(tag_scores), 4) if tag_scores else None
        ),
    }


def _boundary_stability(
    tracks: list[SonicReadyTrack],
    config: dict[str, Any],
) -> float:
    boundary_sets = []
    for seed in (11, 42, 97):
        grouped = group_tracks(
            understand_tracks(tracks, {**config, "random_seed": seed}),
            {**config, "random_seed": seed},
        )
        boundary = set()
        for cluster in grouped.clusters:
            centroid = _centroid([grouped.matrix[index] for index in cluster])
            ranked = sorted(
                cluster,
                key=lambda index: (
                    -_distance(grouped.matrix[index], centroid),
                    tracks[index].local_track_id,
                ),
            )
            boundary.update(tracks[index].local_track_id for index in ranked[:2])
        boundary_sets.append(boundary)
    scores = [
        len(left & right) / max(1, len(left | right))
        for left_index, left in enumerate(boundary_sets)
        for right_index, right in enumerate(boundary_sets)
        if left_index < right_index
    ]
    return round(sum(scores) / max(1, len(scores)), 4)


def _stratified_sample(
    tracks: list[SonicReadyTrack],
    limit: int,
) -> list[SonicReadyTrack]:
    strata: dict[str, list[SonicReadyTrack]] = defaultdict(list)
    for track in tracks:
        strata[_stratum(track)].append(track)
    for values in strata.values():
        values.sort(key=lambda track: _stable_track_key(track.local_track_id))
    selected = []
    keys = sorted(strata)
    while len(selected) < min(limit, len(tracks)):
        progressed = False
        for key in keys:
            if strata[key]:
                selected.append(strata[key].pop(0))
                progressed = True
                if len(selected) == min(limit, len(tracks)):
                    break
        if not progressed:
            break
    return sorted(selected, key=lambda track: track.local_track_id)


def _strata_counts(tracks: list[SonicReadyTrack]) -> dict[str, int]:
    return dict(sorted(Counter(_stratum(track) for track in tracks).items()))


def _stratum(track: SonicReadyTrack) -> str:
    tempo = track.descriptors.get("tempo_bpm")
    if not isinstance(tempo, int | float):
        return "tempo_unknown"
    if tempo < 100:
        return "tempo_under_100"
    if tempo < 125:
        return "tempo_100_124"
    if tempo < 145:
        return "tempo_125_144"
    return "tempo_145_plus"


def _specific_tags(track: SonicReadyTrack) -> set[str]:
    generic = {"electronic", "dance", "pop", "music", "various"}
    return {
        part.strip().casefold()
        for value in track.tag_values
        for part in value.replace(";", ",").split(",")
        if part.strip() and part.strip().casefold() not in generic
    }


def _selection_gate(
    variants: dict[str, Any],
    *,
    sample_count: int,
) -> dict[str, Any]:
    descriptor = variants["descriptor_only"]
    descriptor_metrics = descriptor["clustering"]
    sufficient_sample = sample_count >= 48
    descriptor_tag_agreement = descriptor_metrics["specific_tag_pair_agreement"]
    candidates = []
    for name, hybrid in variants.items():
        if not name.startswith("hybrid"):
            continue
        hybrid_metrics = hybrid["clustering"]
        hybrid_used = hybrid["evidence"].get("semantic_mode_used") == "hybrid"
        relative_cluster_quality_not_worse = (
            hybrid_metrics["separation_to_cohesion_ratio"]
            >= descriptor_metrics["separation_to_cohesion_ratio"] * 0.9
        )
        boundary_stability_not_worse = (
            hybrid["boundary_stability"] >= descriptor["boundary_stability"] - 0.1
        )
        hybrid_tag_agreement = hybrid_metrics["specific_tag_pair_agreement"]
        tag_agreement_not_worse = (
            descriptor_tag_agreement is None
            or hybrid_tag_agreement is None
            or hybrid_tag_agreement >= descriptor_tag_agreement - 0.05
        )
        reasons = {
            "hybrid_evidence_available": hybrid_used,
            "representative_sample_available": sufficient_sample,
            "relative_cluster_quality_not_materially_worse": (
                relative_cluster_quality_not_worse
            ),
            "boundary_stability_not_materially_worse": (boundary_stability_not_worse),
            "specific_tag_agreement_not_materially_worse": (tag_agreement_not_worse),
        }
        candidates.append(
            (
                all(reasons.values()),
                hybrid_metrics["separation_to_cohesion_ratio"],
                name,
                hybrid,
                reasons,
            )
        )
    selected = max(candidates, default=None)
    selected_passed = bool(selected and selected[0])
    selected_name = selected[2] if selected_passed and selected is not None else None
    selected_variant = variants[selected_name] if selected_name is not None else None
    return {
        "hybrid_selected": selected_passed,
        "selected_variant": selected_name,
        "selected_semantic_weight": (
            selected_variant["evidence"].get("semantic_weight")
            if selected_variant is not None
            else None
        ),
        "reasons": selected[4] if selected is not None else {},
        "candidate_reasons": {
            candidate[2]: candidate[4] for candidate in sorted(candidates)
        },
    }


def _centroid(rows: list[list[float]]) -> list[float]:
    return (
        [sum(column) / len(column) for column in zip(*rows, strict=True)]
        if rows
        else []
    )


def _distance(left: list[float], right: list[float]) -> float:
    return (
        sum(
            (left_value - right_value) ** 2
            for left_value, right_value in zip(left, right, strict=True)
        )
        ** 0.5
    )


def _stable_track_key(local_track_id: int) -> tuple[int, int]:
    return (
        (local_track_id * 1103515245 + 42 * 12345) & 0xFFFFFFFF,
        local_track_id,
    )


if __name__ == "__main__":
    sys.exit(main())
