from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import ceil, isfinite, sqrt
from statistics import mean, median
from typing import Any

from app.sonic.models import (
    PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
    PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL,
    PLAYLIST_GENERATION_METHOD_KMEANS,
)
from app.sonic.profiles import (
    DEFAULT_SONIC_FEATURE_PROFILE,
    resolve_feature_profile,
    resolve_feature_profile_from_config,
)
from app.sonic.store import SonicReadyTrack


DEFAULT_GENERATION_CONFIG = {
    "clustering_method": PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL,
    "max_depth": 2,
    "target_playlist_size": 25,
    "min_playlist_size": 8,
    "max_children": 4,
    "feature_profile": DEFAULT_SONIC_FEATURE_PROFILE,
    "random_seed": 42,
}

STYLE_TAG_DOMINANCE_RATIO = 0.4
DJ_HIERARCHICAL_WEAK_SPLIT_SILHOUETTE = 0.08
DJ_HIERARCHICAL_FORCE_SPLIT_TARGET_RATIO = 2.5
DJ_HIERARCHICAL_GROUP_WEIGHTS = {
    "attack": 1.0,
    "brightness": 0.95,
    "density": 0.9,
    "energy": 1.25,
    "harmony": 0.75,
    "tempo": 1.15,
    "texture": 0.85,
}


@dataclass(frozen=True, slots=True)
class GeneratedPlaylistDraft:
    client_key: str
    parent_key: str | None
    depth: int
    position: int
    name: str
    summary: dict[str, Any]
    track_ids: list[int]


@dataclass(frozen=True, slots=True)
class SplitCandidate:
    labels: list[int]
    score: float
    silhouette: float
    separation: float
    size_balance: float
    target_fit: float
    cluster_sizes: list[int]


def normalize_generation_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = {**DEFAULT_GENERATION_CONFIG, **config}
    normalized["max_depth"] = max(1, min(int(normalized["max_depth"]), 5))
    normalized["target_playlist_size"] = max(
        2,
        min(int(normalized["target_playlist_size"]), 500),
    )
    normalized["min_playlist_size"] = max(
        1, min(int(normalized["min_playlist_size"]), 250)
    )
    normalized["max_children"] = max(2, min(int(normalized["max_children"]), 10))
    normalized["random_seed"] = int(normalized["random_seed"])
    if normalized["clustering_method"] not in (
        PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL,
        PLAYLIST_GENERATION_METHOD_KMEANS,
        PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
    ):
        normalized["clustering_method"] = PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL
    profile = resolve_feature_profile(str(normalized["feature_profile"]))
    normalized["feature_profile"] = profile.key
    normalized["resolved_feature_profile"] = profile.to_config()
    return normalized


def generate_playlist_tree(
    tracks: list[SonicReadyTrack],
    generation_config: dict[str, Any],
) -> list[dict[str, Any]]:
    config = normalize_generation_config(generation_config)
    if not tracks:
        return []

    profile = resolve_feature_profile_from_config(config)
    ordered_tracks = sorted(tracks, key=lambda track: track.local_track_id)
    matrix = _generation_matrix(
        ordered_tracks,
        profile.descriptor_weights,
        method=str(config["clustering_method"]),
    )
    cluster_indexes = _split_indexes(
        list(range(len(ordered_tracks))),
        matrix,
        config=config,
    )
    if not cluster_indexes:
        cluster_indexes = [list(range(len(ordered_tracks)))]

    drafts: list[GeneratedPlaylistDraft] = []
    used_names: set[str] = set()
    _append_nodes(
        all_tracks=ordered_tracks,
        drafts=drafts,
        indexes_by_parent=list(range(len(ordered_tracks))),
        matrix=matrix,
        profile_weights=profile.descriptor_weights,
        clusters=cluster_indexes,
        config=config,
        depth=0,
        parent_key=None,
        parent_name=None,
        used_names=used_names,
    )
    return [
        {
            "client_key": draft.client_key,
            "parent_key": draft.parent_key,
            "depth": draft.depth,
            "position": draft.position,
            "name": draft.name,
            "summary": draft.summary,
            "track_ids": draft.track_ids,
        }
        for draft in drafts
    ]


def _append_nodes(
    *,
    all_tracks: list[SonicReadyTrack],
    clusters: list[list[int]],
    config: dict[str, Any],
    depth: int,
    drafts: list[GeneratedPlaylistDraft],
    indexes_by_parent: list[int],
    matrix: list[list[float]],
    parent_key: str | None,
    parent_name: str | None,
    profile_weights: dict[str, float],
    used_names: set[str],
) -> None:
    parent_descriptors = _descriptor_means(
        [all_tracks[index] for index in indexes_by_parent]
    )
    sibling_entries: list[dict[str, Any]] = []
    for position, cluster in enumerate(clusters, start=1):
        client_key = f"{parent_key or 'root'}-{depth}-{position}"
        ordered_cluster_indexes = _order_cluster_indexes(
            cluster,
            all_tracks,
            matrix,
            random_seed=int(config["random_seed"]),
        )
        cluster_tracks = [all_tracks[index] for index in ordered_cluster_indexes]
        cluster_descriptors = _descriptor_means(cluster_tracks)
        summary = _cluster_summary(
            parent_descriptors,
            cluster_descriptors,
            cluster_tracks,
            [matrix[index] for index in ordered_cluster_indexes],
            profile_weights=profile_weights,
        )
        sibling_entries.append(
            {
                "client_key": client_key,
                "cluster": cluster,
                "cluster_tracks": cluster_tracks,
                "position": position,
                "summary": summary,
            }
        )

    _add_sibling_differentiators(
        [entry["summary"] for entry in sibling_entries],
        depth=depth,
    )

    for entry in sibling_entries:
        cluster = entry["cluster"]
        client_key = entry["client_key"]
        cluster_tracks = entry["cluster_tracks"]
        position = entry["position"]
        summary = entry["summary"]
        name, name_debug = _playlist_name(
            summary,
            depth,
            parent_name=parent_name,
            used_names=used_names,
        )
        summary = {
            **summary,
            "name_components": name_debug["components"],
            "name_strategy": name_debug["strategy"],
            "naming": {
                **name_debug["components"],
                "discriminators": name_debug["components"]["differentiators"],
                "strategy": name_debug["strategy"],
                "strategy_version": "dj_utility_v1",
            },
        }
        used_names.add(_name_key(name))
        drafts.append(
            GeneratedPlaylistDraft(
                client_key=client_key,
                parent_key=parent_key,
                depth=depth,
                position=position,
                name=name,
                summary=summary,
                track_ids=[track.local_track_id for track in cluster_tracks],
            )
        )

        if not _can_split(len(cluster), depth=depth, config=config):
            continue

        child_clusters = _split_indexes(cluster, matrix, config=config)
        if len(child_clusters) < 2:
            continue
        _append_nodes(
            all_tracks=all_tracks,
            clusters=child_clusters,
            config=config,
            depth=depth + 1,
            drafts=drafts,
            indexes_by_parent=cluster,
            matrix=matrix,
            parent_key=client_key,
            parent_name=name,
            profile_weights=profile_weights,
            used_names=used_names,
        )


def _split_indexes(
    indexes: list[int],
    matrix: list[list[float]],
    *,
    config: dict[str, Any],
) -> list[list[int]]:
    if not _can_split(len(indexes), depth=-1, config={**config, "max_depth": 2}):
        return [indexes]

    subset = [matrix[index] for index in indexes]
    method = str(config["clustering_method"])
    if method == PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL:
        candidate = _dj_hierarchical_split_candidate(subset, config=config)
        if candidate is None:
            return [indexes]
        labels = candidate.labels
    else:
        n_clusters = _cluster_count(len(indexes), config)
        if n_clusters < 2:
            return [indexes]
        labels = _cluster_labels(
            subset,
            method=method,
            n_clusters=n_clusters,
            random_seed=config["random_seed"],
        )
    grouped: dict[int, list[int]] = defaultdict(list)
    for source_index, label in zip(indexes, labels, strict=True):
        grouped[int(label)].append(source_index)

    clusters = [cluster for _, cluster in sorted(grouped.items()) if cluster]
    return clusters if len(clusters) > 1 else [indexes]


def _can_split(size: int, *, depth: int, config: dict[str, Any]) -> bool:
    return (
        depth < int(config["max_depth"]) - 1
        and size > int(config["target_playlist_size"])
        and size >= int(config["min_playlist_size"]) * 2
    )


def _cluster_count(size: int, config: dict[str, Any]) -> int:
    target = int(config["target_playlist_size"])
    max_children = int(config["max_children"])
    min_size = int(config["min_playlist_size"])
    by_target = max(2, ceil(size / target))
    by_min_size = max(2, size // min_size)
    return max(2, min(max_children, by_target, by_min_size, size))


def _cluster_labels(
    matrix: list[list[float]],
    *,
    method: str,
    n_clusters: int,
    random_seed: int,
) -> list[int]:
    try:
        if method == PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE:
            from sklearn.cluster import AgglomerativeClustering

            model = AgglomerativeClustering(n_clusters=n_clusters)
            return [int(label) for label in model.fit_predict(matrix)]

        from sklearn.cluster import KMeans

        model = KMeans(n_clusters=n_clusters, n_init="auto", random_state=random_seed)
        return [int(label) for label in model.fit_predict(matrix)]
    except ImportError:
        return _fallback_cluster_labels(matrix, n_clusters=n_clusters)


def _dj_hierarchical_split_candidate(
    matrix: list[list[float]],
    *,
    config: dict[str, Any],
) -> SplitCandidate | None:
    size = len(matrix)
    min_size = int(config["min_playlist_size"])
    max_k = min(int(config["max_children"]), size // min_size, size)
    if max_k < 2:
        return None

    best_candidate: SplitCandidate | None = None
    for n_clusters in range(2, max_k + 1):
        labels = _cluster_labels(
            matrix,
            method=PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
            n_clusters=n_clusters,
            random_seed=int(config["random_seed"]),
        )
        cluster_sizes = _label_cluster_sizes(labels)
        if len(cluster_sizes) != n_clusters or min(cluster_sizes) < min_size:
            continue

        silhouette = _silhouette_score(matrix, labels)
        separation = _cluster_separation_score(matrix, labels)
        size_balance = min(cluster_sizes) / max(cluster_sizes)
        target_fit = _target_fit_score(
            cluster_sizes, int(config["target_playlist_size"])
        )
        separation_score = separation / (separation + 1.0) if separation > 0 else 0.0
        candidate = SplitCandidate(
            labels=labels,
            score=(
                max(0.0, (silhouette + 1.0) / 2.0) * 0.45
                + separation_score * 0.2
                + size_balance * 0.15
                + target_fit * 0.2
            ),
            silhouette=silhouette,
            separation=separation,
            size_balance=size_balance,
            target_fit=target_fit,
            cluster_sizes=cluster_sizes,
        )
        if best_candidate is None or candidate.score > best_candidate.score:
            best_candidate = candidate

    if best_candidate is None:
        return None

    force_split = (
        size
        >= int(config["target_playlist_size"])
        * DJ_HIERARCHICAL_FORCE_SPLIT_TARGET_RATIO
    )
    if (
        best_candidate.silhouette < DJ_HIERARCHICAL_WEAK_SPLIT_SILHOUETTE
        and best_candidate.separation < 1.0
        and not force_split
    ):
        return None
    return best_candidate


def _label_cluster_sizes(labels: list[int]) -> list[int]:
    return sorted(Counter(labels).values())


def _silhouette_score(matrix: list[list[float]], labels: list[int]) -> float:
    if len(set(labels)) < 2 or len(set(labels)) >= len(labels):
        return 0.0
    try:
        from sklearn.metrics import silhouette_score

        return float(silhouette_score(matrix, labels))
    except (ImportError, ValueError):
        return 0.0


def _cluster_separation_score(matrix: list[list[float]], labels: list[int]) -> float:
    rows_by_label: dict[int, list[list[float]]] = defaultdict(list)
    for row, label in zip(matrix, labels, strict=True):
        rows_by_label[int(label)].append(row)
    if len(rows_by_label) < 2:
        return 0.0

    centroids = {
        label: _centroid(rows) for label, rows in rows_by_label.items() if rows
    }
    intra_distances = [
        _mean_distance_to_centroid(rows, centroids[label])
        for label, rows in rows_by_label.items()
        if label in centroids
    ]
    mean_intra_distance = mean(intra_distances) if intra_distances else 0.0
    inter_distances = [
        _distance(left_centroid, right_centroid)
        for left_label, left_centroid in centroids.items()
        for right_label, right_centroid in centroids.items()
        if left_label < right_label
    ]
    if not inter_distances:
        return 0.0
    min_inter_distance = min(inter_distances)
    if min_inter_distance <= 1e-9:
        return 0.0
    return min_inter_distance / max(mean_intra_distance, 1e-9)


def _centroid(rows: list[list[float]]) -> list[float]:
    if not rows:
        return []
    return [mean(column) for column in zip(*rows, strict=True)]


def _mean_distance_to_centroid(rows: list[list[float]], centroid: list[float]) -> float:
    if not rows:
        return 0.0
    return mean(_distance(row, centroid) for row in rows)


def _target_fit_score(cluster_sizes: list[int], target_size: int) -> float:
    if target_size <= 0 or not cluster_sizes:
        return 0.0
    return mean(
        max(0.0, 1.0 - abs(cluster_size - target_size) / target_size)
        for cluster_size in cluster_sizes
    )


def _fallback_cluster_labels(
    matrix: list[list[float]], *, n_clusters: int
) -> list[int]:
    ordered = sorted(
        range(len(matrix)),
        key=lambda index: (matrix[index][0] if matrix[index] else 0.0, index),
    )
    labels = [0 for _ in matrix]
    chunk_size = max(1, ceil(len(matrix) / n_clusters))
    for ordered_position, source_index in enumerate(ordered):
        labels[source_index] = min(n_clusters - 1, ordered_position // chunk_size)
    return labels


def _generation_matrix(
    tracks: list[SonicReadyTrack],
    descriptor_weights: dict[str, float],
    *,
    method: str,
) -> list[list[float]]:
    if method == PLAYLIST_GENERATION_METHOD_DJ_HIERARCHICAL:
        return _dj_profile_matrix(tracks, descriptor_weights)
    return _profile_matrix(tracks, descriptor_weights)


def _standardize_vectors(vectors: list[list[float]]) -> list[list[float]]:
    if not vectors:
        return []
    width = max(len(vector) for vector in vectors)
    padded = [vector + [0.0] * (width - len(vector)) for vector in vectors]
    columns = list(zip(*padded, strict=True))
    means = [mean(column) for column in columns]
    stds = []
    for column, column_mean in zip(columns, means, strict=True):
        variance = mean([(value - column_mean) ** 2 for value in column])
        stds.append(sqrt(variance) or 1.0)
    return [
        [(value - means[index]) / stds[index] for index, value in enumerate(vector)]
        for vector in padded
    ]


def _robust_scale_optional_vectors(
    vectors: list[list[float | None]],
) -> list[list[float]]:
    if not vectors:
        return []
    width = max(len(vector) for vector in vectors)
    padded = [vector + [None] * (width - len(vector)) for vector in vectors]
    columns = list(zip(*padded, strict=True))
    centers = []
    scales = []
    for column in columns:
        values = sorted(
            value
            for value in column
            if isinstance(value, int | float) and isfinite(float(value))
        )
        if not values:
            centers.append(0.0)
            scales.append(1.0)
            continue
        center = median(values)
        q1 = _percentile(values, 0.25)
        q3 = _percentile(values, 0.75)
        scale = q3 - q1
        if scale <= 1e-9:
            scale = (values[-1] - values[0]) / 2.0
        centers.append(float(center))
        scales.append(scale if scale > 1e-9 else 1.0)

    scaled: list[list[float]] = []
    for row in padded:
        scaled.append(
            [
                (_finite_or_default(value, centers[index]) - centers[index])
                / scales[index]
                for index, value in enumerate(row)
            ]
        )
    return scaled


def _finite_or_default(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    float_value = float(value)
    return float_value if isfinite(float_value) else default


def _profile_matrix(
    tracks: list[SonicReadyTrack],
    descriptor_weights: dict[str, float],
) -> list[list[float]]:
    vector_keys = list(descriptor_weights.keys())
    raw_matrix = [
        [float(track.descriptors.get(key, 0.0)) for key in vector_keys]
        for track in tracks
    ]
    standardized = _standardize_vectors(raw_matrix)
    weights = [float(descriptor_weights[key]) for key in vector_keys]
    return [
        [value * weights[index] for index, value in enumerate(row)]
        for row in standardized
    ]


def _dj_profile_matrix(
    tracks: list[SonicReadyTrack],
    descriptor_weights: dict[str, float],
) -> list[list[float]]:
    specs = _dj_feature_specs(descriptor_weights)
    raw_matrix = [
        [_dj_feature_value(track.descriptors, spec) for spec in specs]
        for track in tracks
    ]
    scaled = _robust_scale_optional_vectors(raw_matrix)
    group_sizes = Counter(str(spec["group"]) for spec in specs)
    weights = [
        float(spec["weight"])
        * DJ_HIERARCHICAL_GROUP_WEIGHTS.get(str(spec["group"]), 1.0)
        / sqrt(group_sizes[str(spec["group"])])
        for spec in specs
    ]
    return [
        [value * weights[index] for index, value in enumerate(row)] for row in scaled
    ]


def _dj_feature_specs(descriptor_weights: dict[str, float]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for key, weight in descriptor_weights.items():
        if key == "tempo_bpm":
            specs.append(
                {
                    "group": "tempo",
                    "key": "tempo_mix_bpm",
                    "source_key": key,
                    "weight": float(weight),
                }
            )
            specs.append(
                {
                    "group": "tempo",
                    "key": "tempo_raw_bpm",
                    "source_key": key,
                    "weight": float(weight) * 0.35,
                }
            )
            continue
        specs.append(
            {
                "group": _descriptor_group(key),
                "key": key,
                "source_key": key,
                "weight": float(weight),
            }
        )
    return specs


def _dj_feature_value(
    descriptors: dict[str, Any],
    spec: dict[str, Any],
) -> float | None:
    source_key = str(spec["source_key"])
    value = _float_or_none(descriptors.get(source_key))
    if value is None:
        return None
    if spec["key"] == "tempo_mix_bpm":
        return _mixable_tempo_bpm(value)
    return value


def _mixable_tempo_bpm(tempo_bpm: float) -> float | None:
    if tempo_bpm <= 0:
        return None
    tempo = tempo_bpm
    while tempo < 85.0:
        tempo *= 2.0
    while tempo > 170.0:
        tempo /= 2.0
    return tempo


def _descriptor_group(key: str) -> str:
    if key == "tempo_bpm":
        return "tempo"
    if key.startswith("rms_"):
        return "energy"
    if key.startswith("onset_strength_") or key.startswith("zero_crossing_rate_"):
        return "attack"
    if key.startswith("spectral_centroid_") or key.startswith("spectral_rolloff_"):
        return "brightness"
    if (
        key.startswith("spectral_bandwidth_")
        or key.startswith("spectral_contrast_")
        or key.startswith("spectral_flatness_")
    ):
        return "density"
    if key.startswith("chroma_") or key.startswith("mfcc_"):
        return "harmony"
    return "texture"


def _order_cluster_indexes(
    indexes: list[int],
    all_tracks: list[SonicReadyTrack],
    matrix: list[list[float]],
    *,
    random_seed: int,
) -> list[int]:
    if len(indexes) <= 2:
        return list(indexes)

    start_index = min(
        indexes,
        key=lambda index: (
            sum(_distance(matrix[index], matrix[other]) for other in indexes),
            _seeded_tie_break(all_tracks[index].local_track_id, random_seed),
            all_tracks[index].local_track_id,
        ),
    )
    ordered = [start_index]
    remaining = set(indexes)
    remaining.remove(start_index)
    while remaining:
        previous = ordered[-1]
        recent_tracks = [all_tracks[index] for index in ordered[-3:]]
        next_index = min(
            remaining,
            key=lambda index: (
                _distance(matrix[previous], matrix[index])
                + _metadata_repeat_penalty(recent_tracks, all_tracks[index]),
                _distance(matrix[previous], matrix[index]),
                _seeded_tie_break(all_tracks[index].local_track_id, random_seed),
                all_tracks[index].local_track_id,
            ),
        )
        ordered.append(next_index)
        remaining.remove(next_index)

    return ordered


def _distance(left: list[float], right: list[float]) -> float:
    return sqrt(
        sum(
            (left_value - right_value) ** 2
            for left_value, right_value in zip(left, right, strict=True)
        )
    )


def _metadata_repeat_penalty(
    recent_tracks: list[SonicReadyTrack],
    candidate_track: SonicReadyTrack,
) -> float:
    penalty = 0.0
    artist_weights = (0.35, 0.2, 0.1)
    album_weights = (0.2, 0.1, 0.05)
    for offset, previous_track in enumerate(reversed(recent_tracks)):
        if (
            previous_track.artist
            and candidate_track.artist
            and previous_track.artist.casefold() == candidate_track.artist.casefold()
        ):
            penalty += artist_weights[offset]
        if (
            previous_track.album
            and candidate_track.album
            and previous_track.album.casefold() == candidate_track.album.casefold()
        ):
            penalty += album_weights[offset]
    return penalty


def _seeded_tie_break(local_track_id: int, random_seed: int) -> int:
    return (local_track_id * 1103515245 + random_seed * 12345) & 0xFFFFFFFF


def _descriptor_means(tracks: list[SonicReadyTrack]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for track in tracks:
        for key, value in track.descriptors.items():
            numeric_value = _float_or_none(value)
            if numeric_value is not None:
                values[key].append(numeric_value)
    return {key: mean(entries) for key, entries in values.items() if entries}


def _cluster_summary(
    parent_descriptors: dict[str, float],
    cluster_descriptors: dict[str, float],
    tracks: list[SonicReadyTrack],
    cluster_matrix: list[list[float]],
    *,
    profile_weights: dict[str, float],
) -> dict[str, Any]:
    deltas = []
    for key, cluster_value in cluster_descriptors.items():
        parent_value = parent_descriptors.get(key)
        if parent_value is None:
            continue
        delta = cluster_value - parent_value
        if abs(delta) < 1e-9:
            continue
        deltas.append(
            {
                "key": key,
                "cluster_value": cluster_value,
                "parent_value": parent_value,
                "delta": delta,
                "abs_delta": abs(delta),
                "label": _delta_label(key, delta),
                "profile_weight": float(profile_weights.get(key, 0.0)),
            }
        )
    top_deltas = sorted(
        deltas,
        key=lambda item: (
            item["abs_delta"] * max(item["profile_weight"], 0.1),
            item["abs_delta"],
            item["key"],
        ),
        reverse=True,
    )[:5]
    return {
        "bpm": _bpm_summary(tracks),
        "common_tags": _common_tags(tracks),
        "descriptor_means": cluster_descriptors,
        "energy": _energy_summary(parent_descriptors, cluster_descriptors),
        "ordering_strategy": "profile_nearest_neighbor_rolling_v2",
        "representative_tracks": _representative_tracks(tracks, cluster_matrix),
        "track_count": len(tracks),
        "top_deltas": top_deltas,
    }


def _bpm_summary(tracks: list[SonicReadyTrack]) -> dict[str, Any]:
    values = sorted(_descriptor_values(tracks, "tempo_bpm"))
    if not values:
        return {}

    min_bpm = round(values[0])
    median_bpm = round(median(values))
    max_bpm = round(values[-1])
    lower_bpm = min_bpm
    upper_bpm = max_bpm
    label_basis = "full_range"
    if len(values) >= 12 and max_bpm - min_bpm > 36:
        lower_bpm = round(_percentile(values, 0.25))
        upper_bpm = round(_percentile(values, 0.75))
        label_basis = "central_range"

    label = (
        f"{median_bpm} BPM"
        if upper_bpm - lower_bpm <= 2
        else f"{lower_bpm}-{upper_bpm} BPM"
    )
    return {
        "average": round(mean(values), 1),
        "count": len(values),
        "full_range_label": (
            f"{median_bpm} BPM"
            if max_bpm - min_bpm <= 2
            else f"{min_bpm}-{max_bpm} BPM"
        ),
        "label": label,
        "label_basis": label_basis,
        "label_max": upper_bpm,
        "label_min": lower_bpm,
        "max": max_bpm,
        "median": median_bpm,
        "min": min_bpm,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = round((len(values) - 1) * percentile)
    return values[max(0, min(len(values) - 1, index))]


def _descriptor_values(tracks: list[SonicReadyTrack], key: str) -> list[float]:
    values = []
    for track in tracks:
        value = _float_or_none(track.descriptors.get(key))
        if value is not None and value > 0:
            values.append(value)
    return values


def _energy_summary(
    parent_descriptors: dict[str, float],
    cluster_descriptors: dict[str, float],
) -> dict[str, Any]:
    cluster_score = _energy_score(cluster_descriptors)
    if cluster_score is None:
        return {}

    parent_score = _energy_score(parent_descriptors)
    summary = {
        "band": _energy_band(cluster_score),
        "inputs": {
            key: round(value, 4)
            for key in ("tempo_bpm", "rms_mean", "onset_strength_mean")
            if isinstance((value := cluster_descriptors.get(key)), int | float)
        },
        "score": round(cluster_score, 3),
    }
    if parent_score is not None:
        summary["delta_from_parent"] = round(cluster_score - parent_score, 3)
    return summary


def _energy_score(descriptors: dict[str, float]) -> float | None:
    components = []
    tempo = _float_or_none(descriptors.get("tempo_bpm"))
    if tempo is not None:
        components.append(_clamp((tempo - 85.0) / 50.0))
    rms = _float_or_none(descriptors.get("rms_mean"))
    if rms is not None:
        components.append(_clamp((rms - 0.08) / 0.28))
    onset = _float_or_none(descriptors.get("onset_strength_mean"))
    if onset is not None:
        components.append(_clamp(onset / 2.0))
    if not components:
        return None
    return mean(components)


def _energy_band(score: float) -> str:
    if score < 0.4:
        return "Low Energy"
    if score < 0.72:
        return "Medium Energy"
    return "High Energy"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    float_value = float(value)
    return float_value if isfinite(float_value) else None


def _coerce_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _add_sibling_differentiators(
    summaries: list[dict[str, Any]],
    *,
    depth: int,
) -> None:
    if len(summaries) < 2:
        for summary in summaries:
            summary["sibling_differentiators"] = []
        return

    metric_specs = [
        {
            "high": "Fastest",
            "high_mid": "Faster",
            "key": "tempo",
            "low": "Slowest",
            "low_mid": "Slower",
            "min_spread": 8.0,
            "value": lambda summary: _float_or_none(
                _coerce_dict(summary.get("bpm")).get("median")
            ),
        },
        {
            "high": "Highest Energy",
            "high_mid": "Higher Energy",
            "key": "energy",
            "low": "Lowest Energy",
            "low_mid": "Lower Energy",
            "min_spread": 0.08,
            "value": lambda summary: _float_or_none(
                _coerce_dict(summary.get("energy")).get("score")
            ),
        },
        {
            "high": "Brightest",
            "high_mid": "Bright",
            "key": "brightness",
            "low": "Warmest",
            "low_mid": "Warm",
            "min_spread": 350.0,
            "value": lambda summary: _descriptor_mean_value(
                summary,
                "spectral_centroid_mean",
            ),
        },
        {
            "high": "Densest",
            "high_mid": "Dense",
            "key": "density",
            "low": "Sparsest",
            "low_mid": "Sparse",
            "min_spread": 350.0,
            "value": lambda summary: _descriptor_mean_value(
                summary,
                "spectral_bandwidth_mean",
            ),
        },
        {
            "high": "Punchiest",
            "high_mid": "Punchy",
            "key": "attack",
            "low": "Smoothest",
            "low_mid": "Smooth",
            "min_spread": 0.35,
            "value": lambda summary: _descriptor_mean_value(
                summary,
                "onset_strength_mean",
            ),
        },
        {
            "high": "Most Percussive",
            "high_mid": "Percussive",
            "key": "percussion",
            "low": "Smoothest",
            "low_mid": "Smooth",
            "min_spread": 0.02,
            "value": lambda summary: _descriptor_mean_value(
                summary,
                "zero_crossing_rate_mean",
            ),
        },
        {
            "high": "Most Tonal",
            "high_mid": "Tonal",
            "key": "tone",
            "low": "Most Open",
            "low_mid": "Open",
            "min_spread": 3.0,
            "value": lambda summary: _descriptor_mean_value(summary, "mfcc_01_mean"),
        },
    ]

    differentiators_by_index: list[list[dict[str, Any]]] = [[] for _ in summaries]
    style_counts = Counter(
        style
        for summary in summaries
        if (style := _dominant_style_label(summary)) is not None
    )
    for index, summary in enumerate(summaries):
        style = _dominant_style_label(summary)
        track_count = summary.get("track_count")
        first_tag = (
            summary.get("common_tags", [None])[0]
            if isinstance(summary.get("common_tags"), list)
            and summary.get("common_tags")
            else None
        )
        tag_count = first_tag.get("count") if isinstance(first_tag, dict) else None
        if (
            style is not None
            and style_counts[style] == 1
            and isinstance(track_count, int)
            and track_count > 0
            and isinstance(tag_count, int)
        ):
            differentiators_by_index[index].append(
                {
                    "key": "style",
                    "label": style,
                    "score": round(tag_count / track_count, 3),
                    "sibling_count": len(summaries),
                    "source": "sibling_style",
                    "value": style,
                }
            )

    for spec in metric_specs:
        values = [spec["value"](summary) for summary in summaries]
        ranked_values = sorted(
            (value, index) for index, value in enumerate(values) if value is not None
        )
        if len(ranked_values) < 2:
            continue
        min_value = ranked_values[0][0]
        max_value = ranked_values[-1][0]
        spread = max_value - min_value
        if spread < float(spec["min_spread"]):
            continue
        center = mean(value for value, _ in ranked_values)
        positions_by_index = {
            index: position for position, (_, index) in enumerate(ranked_values)
        }
        for index, value in enumerate(values):
            position = positions_by_index.get(index)
            if value is None or position is None:
                continue
            if position == 0:
                label = spec["low"]
                rank_score = 1.0
            elif position == len(ranked_values) - 1:
                label = spec["high"]
                rank_score = 1.0
            elif len(ranked_values) >= 4 and value < center:
                label = spec["low_mid"]
                rank_score = abs(value - center) / spread
            elif len(ranked_values) >= 4 and value > center:
                label = spec["high_mid"]
                rank_score = abs(value - center) / spread
            else:
                continue
            if rank_score < 0.12:
                continue
            differentiators_by_index[index].append(
                {
                    "key": spec["key"],
                    "label": label,
                    "score": round(rank_score, 3),
                    "sibling_count": len(summaries),
                    "source": "sibling_relative",
                    "value": round(value, 4),
                }
            )

    for summary, differentiators in zip(
        summaries,
        differentiators_by_index,
        strict=True,
    ):
        summary["sibling_differentiators"] = _rank_sibling_differentiators(
            differentiators,
            depth=depth,
        )


def _descriptor_mean_value(summary: dict[str, Any], key: str) -> float | None:
    return _float_or_none(_coerce_dict(summary.get("descriptor_means")).get(key))


def _rank_sibling_differentiators(
    differentiators: list[dict[str, Any]],
    *,
    depth: int,
) -> list[dict[str, Any]]:
    priority_by_key = {
        "tempo": 0 if depth == 0 else 2,
        "energy": 1,
        "brightness": 3,
        "density": 4,
        "attack": 5,
        "percussion": 6,
        "tone": 7,
        "style": 8,
    }
    ranked = sorted(
        differentiators,
        key=lambda item: (
            -float(item.get("score", 0.0)),
            priority_by_key.get(str(item.get("key")), 99),
            str(item.get("label", "")),
        ),
    )
    selected = []
    seen_labels: set[str] = set()
    for differentiator in ranked:
        label = differentiator.get("label")
        if not isinstance(label, str) or label in seen_labels:
            continue
        selected.append(differentiator)
        seen_labels.add(label)
        if len(selected) == 3:
            break
    return selected


def _texture_trait_sources(summary: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    descriptor_means = _coerce_dict(summary.get("descriptor_means"))

    for delta in summary.get("top_deltas", []):
        if not isinstance(delta, dict):
            continue
        key = delta.get("key")
        raw_delta = delta.get("delta")
        if not isinstance(key, str) or not isinstance(raw_delta, int | float):
            continue
        label = _texture_label_for_delta(key, float(raw_delta))
        if label is not None:
            _append_trait_source(
                sources,
                {
                    "key": key,
                    "label": label,
                    "source": "relative_delta",
                },
            )
        if len(sources) >= 3:
            return sources

    for source in _absolute_texture_sources(descriptor_means):
        _append_trait_source(sources, source)
        if len(sources) >= 3:
            break
    return sources


def _append_trait_source(
    sources: list[dict[str, Any]],
    source: dict[str, Any],
) -> None:
    label = source.get("label")
    if not isinstance(label, str) or not label:
        return
    if any(existing.get("label") == label for existing in sources):
        return
    sources.append(source)


def _texture_label_for_delta(key: str, delta: float) -> str | None:
    high = delta >= 0
    if key.startswith("spectral_centroid") or key.startswith("spectral_rolloff"):
        return "Bright" if high else "Warm"
    if key.startswith("spectral_bandwidth"):
        return "Dense" if high else "Sparse"
    if key.startswith("mfcc"):
        return "Dense" if high else "Open"
    if key.startswith("onset_strength"):
        return "Punchy" if high else "Smooth"
    if key.startswith("zero_crossing"):
        return "Percussive" if high else "Smooth"
    if key.startswith("spectral_flatness"):
        return "Textured" if high else "Smooth"
    if key.startswith("spectral_contrast"):
        return "Punchy" if high else "Smooth"
    if key.startswith("chroma"):
        return "Tonal" if high else "Open"
    return None


def _absolute_texture_sources(descriptors: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        _threshold_trait(
            descriptors,
            "spectral_centroid_mean",
            low_label="Warm",
            low_max=1500.0,
            high_label="Bright",
            high_min=2600.0,
        ),
        _threshold_trait(
            descriptors,
            "spectral_rolloff_mean",
            low_label="Warm",
            low_max=3000.0,
            high_label="Bright",
            high_min=6000.0,
        ),
        _threshold_trait(
            descriptors,
            "spectral_bandwidth_mean",
            low_label="Sparse",
            low_max=1600.0,
            high_label="Dense",
            high_min=3000.0,
        ),
        _threshold_trait(
            descriptors,
            "onset_strength_mean",
            low_label="Smooth",
            low_max=0.4,
            high_label="Punchy",
            high_min=1.2,
        ),
        _threshold_trait(
            descriptors,
            "zero_crossing_rate_mean",
            low_label="Smooth",
            low_max=0.035,
            high_label="Percussive",
            high_min=0.08,
        ),
        _threshold_trait(
            descriptors,
            "mfcc_01_mean",
            low_label="Open",
            low_max=-2.0,
            high_label="Dense",
            high_min=2.0,
        ),
    ]
    return [candidate for candidate in candidates if candidate is not None]


def _threshold_trait(
    descriptors: dict[str, Any],
    key: str,
    *,
    high_label: str,
    high_min: float,
    low_label: str,
    low_max: float,
) -> dict[str, Any] | None:
    value = _float_or_none(descriptors.get(key))
    if value is None:
        return None
    if value <= low_max:
        return {
            "key": key,
            "label": low_label,
            "source": "absolute_threshold",
            "value": round(value, 4),
        }
    if value >= high_min:
        return {
            "key": key,
            "label": high_label,
            "source": "absolute_threshold",
            "value": round(value, 4),
        }
    return None


def _playlist_name(
    summary: dict[str, Any],
    depth: int,
    *,
    parent_name: str | None,
    used_names: set[str],
) -> tuple[str, dict[str, Any]]:
    components = _name_components(summary)
    candidates = _name_candidates(components, depth)
    for candidate in candidates:
        if _name_key(candidate) not in used_names:
            return candidate, {
                "components": components,
                "strategy": "dj_utility_candidate",
            }

    if parent_name:
        for candidate in candidates:
            contextual_candidate = _clean_name(f"{candidate} / {parent_name}")
            if _name_key(contextual_candidate) not in used_names:
                return contextual_candidate, {
                    "components": components,
                    "strategy": "dj_utility_contextual_parent",
                }

    fallback = candidates[0]
    suffix = 2
    while _name_key(f"{fallback} {suffix}") in used_names:
        suffix += 1
    return f"{fallback} {suffix}", {
        "components": components,
        "strategy": "dj_utility_numeric_suffix",
    }


def _name_components(summary: dict[str, Any]) -> dict[str, Any]:
    bpm = _coerce_dict(summary.get("bpm"))
    energy = _coerce_dict(summary.get("energy"))
    style = _dominant_style_label(summary)
    differentiators = _sibling_differentiator_sources(summary)
    trait_sources = _texture_trait_sources(summary)
    traits = [
        source["label"]
        for source in trait_sources
        if isinstance(source.get("label"), str)
    ]
    role = _role_label(bpm=bpm, energy=energy, traits=traits)

    return {
        "bpm": bpm,
        "differentiators": differentiators,
        "energy": energy,
        "role": role,
        "style": style,
        "tag": style,
        "tempo": bpm.get("label") if bpm else None,
        "trait_sources": trait_sources,
        "texture_traits": traits,
        "traits": traits,
    }


def _name_candidates(components: dict[str, Any], depth: int) -> list[str]:
    style_label = components.get("style")
    style = style_label if isinstance(style_label, str) and style_label else None
    raw_traits = components.get("traits")
    traits = raw_traits if isinstance(raw_traits, list) else []
    trait_labels = [trait for trait in traits if isinstance(trait, str) and trait]
    raw_differentiators = components.get("differentiators")
    differentiators = (
        raw_differentiators if isinstance(raw_differentiators, list) else []
    )
    differentiator_labels = [
        differentiator.get("label")
        for differentiator in differentiators
        if isinstance(differentiator, dict)
        and isinstance(differentiator.get("label"), str)
    ]
    bpm_label = components.get("tempo")
    bpm = bpm_label if isinstance(bpm_label, str) and bpm_label else None
    energy = _coerce_dict(components.get("energy"))
    energy_band_value = energy.get("band") if energy else None
    energy_band = (
        energy_band_value
        if isinstance(energy_band_value, str) and energy_band_value
        else None
    )
    role_value = components.get("role")
    role = role_value if isinstance(role_value, str) and role_value else None
    trait_phrase = _trait_phrase(trait_labels)
    relative_phrase = _distinctive_phrase(differentiator_labels, [])
    distinctive_phrase = _distinctive_phrase(differentiator_labels, trait_labels)

    candidates = []
    if depth == 0:
        if relative_phrase and bpm:
            candidates.append(f"{relative_phrase} / {bpm}")
        if relative_phrase and style:
            candidates.append(f"{relative_phrase} / {style}")
        if relative_phrase and energy_band:
            candidates.append(f"{relative_phrase} / {energy_band}")
        if relative_phrase:
            candidates.append(relative_phrase)
        if style and bpm:
            candidates.append(f"{style} / {bpm}")
        if bpm and style and trait_phrase:
            candidates.append(f"{bpm} / {style} / {trait_phrase}")
        if role and distinctive_phrase:
            candidates.append(f"{role} / {distinctive_phrase}")
        if role and bpm and distinctive_phrase:
            candidates.append(f"{role} / {bpm} / {distinctive_phrase}")
        if bpm and distinctive_phrase:
            candidates.append(f"{bpm} / {distinctive_phrase}")
        if bpm and energy_band:
            candidates.append(f"{bpm} / {energy_band}")
        if bpm and trait_phrase:
            candidates.append(f"{bpm} / {trait_phrase}")
        if style and energy_band:
            candidates.append(f"{style} / {energy_band}")
        if style:
            candidates.append(style)
        if bpm:
            candidates.append(bpm)
        if energy_band and trait_phrase:
            candidates.append(f"{energy_band} / {trait_phrase}")
        if energy_band:
            candidates.append(energy_band)
        candidates.append("Sonic DJ Crate")
        return _unique_clean_names(candidates)

    utility_phrase = _child_utility_phrase(
        bpm=bpm,
        differentiators=differentiator_labels,
        energy_band=energy_band,
        traits=trait_labels,
    )
    if relative_phrase and role:
        candidates.append(f"{relative_phrase} / {role}")
    if relative_phrase and bpm:
        candidates.append(f"{relative_phrase} / {bpm}")
    if relative_phrase:
        candidates.append(relative_phrase)
    if role and utility_phrase:
        candidates.append(f"{role} / {utility_phrase}")
    if role and bpm and utility_phrase:
        candidates.append(f"{role} / {bpm} / {utility_phrase}")
    if role and style and utility_phrase:
        candidates.append(f"{role} / {style} + {utility_phrase}")
    if bpm and style and trait_phrase:
        candidates.append(f"{bpm} / {style} / {trait_phrase}")
    if bpm and energy_band:
        candidates.append(f"{bpm} / {energy_band}")
    if trait_phrase:
        candidates.append(trait_phrase)
    if role:
        candidates.append(role)
    candidates.append("DJ Utility Split")
    return _unique_clean_names(candidates)


def _trait_phrase(traits: list[str]) -> str | None:
    if not traits:
        return None
    return " + ".join(traits[:2])


def _distinctive_phrase(
    differentiators: list[str],
    traits: list[str],
) -> str | None:
    parts = []
    for label in [*differentiators, *traits]:
        if label and label not in parts and not _trait_redundant(label, parts):
            parts.append(label)
        if len(parts) == 2:
            break
    if not parts:
        return None
    return " + ".join(parts)


def _child_utility_phrase(
    *,
    bpm: str | None,
    differentiators: list[str],
    energy_band: str | None,
    traits: list[str],
) -> str | None:
    if differentiators:
        distinctive_phrase = _distinctive_phrase(differentiators, traits)
        if distinctive_phrase:
            return distinctive_phrase
    trait_phrase = _trait_phrase(traits)
    if trait_phrase and len(traits) >= 2:
        return trait_phrase
    if trait_phrase and energy_band:
        return f"{energy_band} + {trait_phrase}"
    if trait_phrase:
        return trait_phrase
    if energy_band:
        return energy_band
    return bpm


def _trait_redundant(label: str, existing_labels: list[str]) -> bool:
    label_key = _trait_family(label)
    return any(_trait_family(existing) == label_key for existing in existing_labels)


def _trait_family(label: str) -> str:
    normalized = label.casefold()
    if "energy" in normalized:
        return "energy"
    if normalized in {"bright", "brightest", "warm", "warmest"}:
        return "brightness"
    if normalized in {"dense", "densest", "sparse", "sparsest", "open", "most open"}:
        return "density"
    if normalized in {"punchy", "punchiest", "percussive", "most percussive"}:
        return "attack"
    if normalized in {"smooth", "smoothest"}:
        return "smoothness"
    if normalized in {"fastest", "slowest"}:
        return "tempo"
    return normalized


def _sibling_differentiator_sources(summary: dict[str, Any]) -> list[dict[str, Any]]:
    raw_differentiators = summary.get("sibling_differentiators", [])
    if not isinstance(raw_differentiators, list):
        return []
    return [
        differentiator
        for differentiator in raw_differentiators
        if isinstance(differentiator, dict)
        and isinstance(differentiator.get("label"), str)
    ]


def _dominant_style_label(summary: dict[str, Any]) -> str | None:
    common_tags = summary.get("common_tags", [])
    if not common_tags:
        return None

    first_tag = common_tags[0]
    if not isinstance(first_tag, dict):
        return None
    tag_value = first_tag.get("value")
    count = first_tag.get("count")
    track_count = summary.get("track_count")
    if not isinstance(tag_value, str) or not isinstance(count, int):
        return None
    if not isinstance(track_count, int) or track_count <= 0:
        return None

    threshold = (
        track_count
        if track_count <= 2
        else max(2, ceil(float(track_count) * STYLE_TAG_DOMINANCE_RATIO))
    )
    if count < threshold:
        return None
    return _titlecase_tag(tag_value)


def _role_label(
    *,
    bpm: dict[str, Any],
    energy: dict[str, Any],
    traits: list[str],
) -> str | None:
    median_bpm = _float_or_none(bpm.get("median")) if bpm else None
    score = _float_or_none(energy.get("score")) if energy else None
    delta = _float_or_none(energy.get("delta_from_parent")) if energy else None
    band_value = energy.get("band") if energy else None
    band = band_value if isinstance(band_value, str) and band_value else None
    trait_set = set(traits)

    # "Tools" needs stronger evidence than a generic energy role: sparse enough
    # to leave mix room and percussive/punchy enough to function as a DJ layer.
    if (
        {"Sparse", "Percussive"}.issubset(trait_set)
        or {"Sparse", "Punchy"}.issubset(trait_set)
    ) and (median_bpm is None or median_bpm >= 105):
        return "Tools"

    if (score is not None and score >= 0.72) or (
        median_bpm is not None and median_bpm >= 128
    ):
        return "Peak"

    if score is not None and score <= 0.38:
        if trait_set.intersection({"Open", "Sparse", "Smooth"}):
            return "Afterhours"
        return "Warm-up"

    if (
        score is not None
        and 0.42 <= score < 0.72
        and median_bpm is not None
        and median_bpm >= 108
        and trait_set.intersection({"Smooth", "Warm"})
    ):
        return "Rolling"

    if (delta is not None and delta >= 0.12) or (score is not None and score >= 0.55):
        return "Build"

    if median_bpm is not None and median_bpm >= 108:
        return "Rolling"

    if band == "Low Energy":
        return "Warm-up"
    if band == "High Energy":
        return "Peak"
    return band


def _unique_clean_names(names: list[str]) -> list[str]:
    cleaned_names = []
    seen: set[str] = set()
    for name in names:
        cleaned = _clean_name(name)
        key = _name_key(cleaned)
        if cleaned and key not in seen:
            cleaned_names.append(cleaned)
            seen.add(key)
    return cleaned_names


def _clean_name(name: str) -> str:
    return " ".join(name.strip(" -").split())


def _name_key(name: str) -> str:
    return _clean_name(name).casefold()


def _delta_label(key: str, delta: float) -> str:
    texture_label = _texture_label_for_delta(key, delta)
    if texture_label is not None:
        return texture_label
    high = delta >= 0
    if key == "tempo_bpm":
        return "Faster" if high else "Slower"
    if key.startswith("onset_strength_"):
        return "Punchy" if high else "Smooth"
    if key.startswith("rms_"):
        return "High Energy" if high else "Low Energy"
    return "Higher" if high else "Lower"


def _common_tags(tracks: list[SonicReadyTrack]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    display_values: dict[str, str] = {}
    for track in tracks:
        for tag_value in track.tag_values:
            for part in _split_tag_value(tag_value):
                normalized = part.casefold()
                if not normalized:
                    continue
                counter[normalized] += 1
                display_values.setdefault(normalized, part)

    threshold = max(1, ceil(len(tracks) * 0.2))
    return [
        {
            "value": display_values[tag],
            "count": count,
        }
        for tag, count in sorted(
            counter.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if count >= threshold
    ][:5]


def _split_tag_value(value: str) -> list[str]:
    parts = [value]
    for delimiter in (";", ","):
        parts = [piece for part in parts for piece in part.split(delimiter)]
    return [part.strip() for part in parts if part.strip()]


def _representative_tracks(
    tracks: list[SonicReadyTrack],
    matrix_rows: list[list[float]],
) -> list[dict[str, Any]]:
    if matrix_rows and len(matrix_rows) == len(tracks):
        centroid = _centroid(matrix_rows)
        ordered_tracks = [
            track
            for _, _, track in sorted(
                (
                    (_distance(row, centroid), track.local_track_id, track)
                    for track, row in zip(tracks, matrix_rows, strict=True)
                ),
                key=lambda item: (item[0], item[1]),
            )
        ]
    else:
        ordered_tracks = tracks

    representatives = []
    for track in ordered_tracks[:3]:
        representatives.append(
            {
                "artist": track.artist,
                "local_track_id": track.local_track_id,
                "title": track.title,
            }
        )
    return representatives


def _titlecase_tag(value: str) -> str:
    return " ".join(part.capitalize() for part in value.strip().split())
