from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil, sqrt
from statistics import mean
from typing import Any

from app.sonic.models import (
    PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
    PLAYLIST_GENERATION_METHOD_KMEANS,
)
from app.sonic.store import SonicReadyTrack


DEFAULT_GENERATION_CONFIG = {
    "clustering_method": PLAYLIST_GENERATION_METHOD_KMEANS,
    "max_depth": 2,
    "target_playlist_size": 25,
    "min_playlist_size": 8,
    "max_children": 4,
    "feature_profile": "balanced_v1",
    "random_seed": 42,
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
        PLAYLIST_GENERATION_METHOD_KMEANS,
        PLAYLIST_GENERATION_METHOD_AGGLOMERATIVE,
    ):
        normalized["clustering_method"] = PLAYLIST_GENERATION_METHOD_KMEANS
    if not str(normalized["feature_profile"]).strip():
        normalized["feature_profile"] = DEFAULT_GENERATION_CONFIG["feature_profile"]
    return normalized


def generate_playlist_tree(
    tracks: list[SonicReadyTrack],
    generation_config: dict[str, Any],
) -> list[dict[str, Any]]:
    config = normalize_generation_config(generation_config)
    if not tracks:
        return []

    ordered_tracks = sorted(tracks, key=lambda track: track.local_track_id)
    matrix = _standardize_vectors([track.vector for track in ordered_tracks])
    cluster_indexes = _split_indexes(
        list(range(len(ordered_tracks))),
        matrix,
        config=config,
    )
    if not cluster_indexes:
        cluster_indexes = [list(range(len(ordered_tracks)))]

    drafts: list[GeneratedPlaylistDraft] = []
    _append_nodes(
        all_tracks=ordered_tracks,
        drafts=drafts,
        indexes_by_parent=list(range(len(ordered_tracks))),
        matrix=matrix,
        clusters=cluster_indexes,
        config=config,
        depth=0,
        parent_key=None,
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
) -> None:
    parent_descriptors = _descriptor_means(
        [all_tracks[index] for index in indexes_by_parent]
    )
    sibling_names: set[str] = set()
    for position, cluster in enumerate(clusters, start=1):
        client_key = f"{parent_key or 'root'}-{depth}-{position}"
        cluster_tracks = [all_tracks[index] for index in cluster]
        cluster_descriptors = _descriptor_means(cluster_tracks)
        summary = _cluster_summary(parent_descriptors, cluster_descriptors)
        name = _dedupe_name(_playlist_name(summary, depth), sibling_names)
        sibling_names.add(name.lower())
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
        )


def _split_indexes(
    indexes: list[int],
    matrix: list[list[float]],
    *,
    config: dict[str, Any],
) -> list[list[int]]:
    if not _can_split(len(indexes), depth=-1, config={**config, "max_depth": 2}):
        return [indexes]

    n_clusters = _cluster_count(len(indexes), config)
    if n_clusters < 2:
        return [indexes]

    subset = [matrix[index] for index in indexes]
    labels = _cluster_labels(
        subset,
        method=config["clustering_method"],
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


def _descriptor_means(tracks: list[SonicReadyTrack]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for track in tracks:
        for key, value in track.descriptors.items():
            if isinstance(value, int | float):
                values[key].append(float(value))
    return {key: mean(entries) for key, entries in values.items() if entries}


def _cluster_summary(
    parent_descriptors: dict[str, float],
    cluster_descriptors: dict[str, float],
) -> dict[str, Any]:
    deltas = []
    for key, cluster_value in cluster_descriptors.items():
        parent_value = parent_descriptors.get(key)
        if parent_value is None:
            continue
        delta = cluster_value - parent_value
        deltas.append(
            {
                "key": key,
                "cluster_value": cluster_value,
                "parent_value": parent_value,
                "delta": delta,
                "abs_delta": abs(delta),
                "label": _delta_label(key, delta),
            }
        )
    top_deltas = sorted(
        deltas,
        key=lambda item: (item["abs_delta"], item["key"]),
        reverse=True,
    )[:5]
    return {
        "descriptor_means": cluster_descriptors,
        "top_deltas": top_deltas,
    }


def _playlist_name(summary: dict[str, Any], depth: int) -> str:
    labels = []
    for delta in summary.get("top_deltas", []):
        label = delta.get("label")
        if isinstance(label, str) and label and label not in labels:
            labels.append(label)
        if len(labels) == 2:
            break

    if labels:
        return " ".join(labels)
    return "Sonic Mix" if depth == 0 else "Sonic Branch"


def _dedupe_name(name: str, used_names: set[str]) -> str:
    if name.lower() not in used_names:
        return name
    suffix = 2
    while f"{name} {suffix}".lower() in used_names:
        suffix += 1
    return f"{name} {suffix}"


def _delta_label(key: str, delta: float) -> str:
    high = delta >= 0
    if key == "tempo_bpm":
        return "Fast" if high else "Slow"
    if key.startswith("rms_") or key.startswith("onset_strength_"):
        return "High energy" if high else "Low energy"
    if key.startswith("spectral_centroid") or key.startswith("spectral_rolloff"):
        return "Bright" if high else "Warm"
    if key.startswith("spectral_flatness"):
        return "Textured" if high else "Tonal"
    if key.startswith("zero_crossing"):
        return "Percussive" if high else "Smooth"
    if key.startswith("spectral_contrast"):
        return "Contrasty" if high else "Even"
    if key.startswith("mfcc"):
        return "Dense" if high else "Open"
    if key.startswith("chroma"):
        return "Tonal focus" if high else "Modal"
    return "Lifted" if high else "Recessed"
