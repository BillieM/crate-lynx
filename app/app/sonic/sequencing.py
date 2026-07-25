from __future__ import annotations

from itertools import pairwise
from math import isfinite, sqrt
from statistics import mean
from typing import Any

from app.sonic.models import (
    PLAYLIST_DIVERSITY_MODE_BALANCED,
    PLAYLIST_DIVERSITY_MODE_LOOSE,
    PLAYLIST_DIVERSITY_MODE_STRICT,
    PLAYLIST_SEQUENCING_INTENT_RISING_ENERGY,
    PLAYLIST_SEQUENCING_INTENT_VARIED_LISTENING,
    PLAYLIST_SEQUENCING_INTENT_WARM_UP_TO_PEAK,
)
from app.sonic.store import SonicReadyTrack


def sequence_track_indexes(
    indexes: list[int],
    tracks: list[SonicReadyTrack],
    acoustic_matrix: list[list[float]],
    *,
    diversity_mode: str,
    intent: str,
    random_seed: int,
) -> tuple[list[int], dict[str, Any]]:
    if len(indexes) <= 1:
        return list(indexes), _sequence_evidence(indexes, tracks, intent)
    if intent == PLAYLIST_SEQUENCING_INTENT_RISING_ENERGY:
        ordered = _rising_energy(indexes, tracks, acoustic_matrix, random_seed)
    elif intent == PLAYLIST_SEQUENCING_INTENT_WARM_UP_TO_PEAK:
        ordered = _warm_up_to_peak(indexes, tracks, acoustic_matrix, random_seed)
    elif intent == PLAYLIST_SEQUENCING_INTENT_VARIED_LISTENING:
        ordered = _varied_listening(
            indexes,
            tracks,
            acoustic_matrix,
            diversity_mode=diversity_mode,
            random_seed=random_seed,
        )
    else:
        ordered = _smooth_mix(
            indexes,
            tracks,
            acoustic_matrix,
            diversity_mode=diversity_mode,
            random_seed=random_seed,
        )
    return ordered, _sequence_evidence(ordered, tracks, intent)


def _smooth_mix(
    indexes: list[int],
    tracks: list[SonicReadyTrack],
    matrix: list[list[float]],
    *,
    diversity_mode: str,
    random_seed: int,
) -> list[int]:
    start = min(
        indexes,
        key=lambda index: (
            _energy(tracks[index]),
            _seeded_tie_break(tracks[index].local_track_id, random_seed),
        ),
    )
    ordered = [start]
    remaining = set(indexes) - {start}
    while remaining:
        previous = ordered[-1]
        next_index = min(
            remaining,
            key=lambda index: (
                _transition_cost(tracks[previous], tracks[index])
                + _distance(matrix[previous], matrix[index]) * 0.35
                + _repeat_penalty(
                    [tracks[item] for item in ordered[-3:]],
                    tracks[index],
                    diversity_mode,
                ),
                tracks[index].local_track_id,
            ),
        )
        ordered.append(next_index)
        remaining.remove(next_index)
    return ordered


def _rising_energy(
    indexes: list[int],
    tracks: list[SonicReadyTrack],
    matrix: list[list[float]],
    random_seed: int,
) -> list[int]:
    del matrix
    return sorted(
        indexes,
        key=lambda index: (
            round(_energy(tracks[index]) / 0.08),
            _mixable_tempo(tracks[index]),
            _seeded_tie_break(tracks[index].local_track_id, random_seed),
            tracks[index].local_track_id,
        ),
    )


def _warm_up_to_peak(
    indexes: list[int],
    tracks: list[SonicReadyTrack],
    matrix: list[list[float]],
    random_seed: int,
) -> list[int]:
    remaining = set(indexes)
    energies = sorted(_energy(tracks[index]) for index in indexes)
    low = energies[max(0, len(energies) // 10)]
    high = energies[min(len(energies) - 1, round((len(energies) - 1) * 0.9))]
    ordered: list[int] = []
    for position in range(len(indexes)):
        progress = position / max(1, len(indexes) - 1)
        curved_progress = progress**1.45
        target = low + (high - low) * curved_progress
        previous = ordered[-1] if ordered else None
        next_index = min(
            remaining,
            key=lambda index: (
                abs(_energy(tracks[index]) - target)
                + (
                    _transition_cost(tracks[previous], tracks[index]) * 0.18
                    + _distance(matrix[previous], matrix[index]) * 0.08
                    if previous is not None
                    else 0.0
                ),
                _seeded_tie_break(tracks[index].local_track_id, random_seed),
                tracks[index].local_track_id,
            ),
        )
        ordered.append(next_index)
        remaining.remove(next_index)
    return ordered


def _varied_listening(
    indexes: list[int],
    tracks: list[SonicReadyTrack],
    matrix: list[list[float]],
    *,
    diversity_mode: str,
    random_seed: int,
) -> list[int]:
    centroid = _centroid([matrix[index] for index in indexes])
    start = min(
        indexes,
        key=lambda index: (
            _distance(matrix[index], centroid),
            tracks[index].local_track_id,
        ),
    )
    ordered = [start]
    remaining = set(indexes) - {start}
    while remaining:
        previous = ordered[-1]
        next_index = min(
            remaining,
            key=lambda index: (
                -_distance(matrix[previous], matrix[index])
                + _repeat_penalty(
                    [tracks[item] for item in ordered[-3:]],
                    tracks[index],
                    diversity_mode,
                )
                * 2.0,
                _seeded_tie_break(tracks[index].local_track_id, random_seed),
                tracks[index].local_track_id,
            ),
        )
        ordered.append(next_index)
        remaining.remove(next_index)
    return ordered


def _transition_cost(left: SonicReadyTrack, right: SonicReadyTrack) -> float:
    tempo_cost = abs(_mixable_tempo(left) - _mixable_tempo(right)) / 12.0
    energy_cost = abs(_energy(left) - _energy(right)) * 0.8
    harmonic_cost = _harmonic_cost(left, right)
    return tempo_cost + energy_cost + harmonic_cost


def _harmonic_cost(left: SonicReadyTrack, right: SonicReadyTrack) -> float:
    left_confidence = _number(left.descriptors.get("chroma_tonal_confidence"))
    right_confidence = _number(right.descriptors.get("chroma_tonal_confidence"))
    left_peak = _number(left.descriptors.get("chroma_peak"))
    right_peak = _number(right.descriptors.get("chroma_peak"))
    if (
        left_confidence is None
        or right_confidence is None
        or min(left_confidence, right_confidence) < 0.12
        or left_peak is None
        or right_peak is None
    ):
        return 0.0
    interval = abs(round(left_peak) - round(right_peak)) % 12
    circle_distance = min(interval, 12 - interval)
    if circle_distance in {0, 5, 7}:
        return 0.0
    return min(circle_distance, 3) * 0.12


def _mixable_tempo(track: SonicReadyTrack) -> float:
    tempo = _number(track.descriptors.get("tempo_bpm")) or 110.0
    while tempo < 85.0:
        tempo *= 2.0
    while tempo > 170.0:
        tempo /= 2.0
    return tempo


def _energy(track: SonicReadyTrack) -> float:
    components = []
    tempo = _number(track.descriptors.get("tempo_bpm"))
    rms = _number(track.descriptors.get("rms_mean"))
    onset = _number(track.descriptors.get("onset_strength_mean"))
    if tempo is not None:
        components.append(_clamp((tempo - 85.0) / 50.0))
    if rms is not None:
        components.append(_clamp((rms - 0.08) / 0.28))
    if onset is not None:
        components.append(_clamp(onset / 2.0))
    return mean(components) if components else 0.5


def _repeat_penalty(
    recent: list[SonicReadyTrack],
    candidate: SonicReadyTrack,
    diversity_mode: str,
) -> float:
    scale = {
        PLAYLIST_DIVERSITY_MODE_LOOSE: 0.0,
        PLAYLIST_DIVERSITY_MODE_BALANCED: 1.0,
        PLAYLIST_DIVERSITY_MODE_STRICT: 2.0,
    }.get(diversity_mode, 1.0)
    penalty = 0.0
    for offset, previous in enumerate(reversed(recent)):
        recency = (0.4, 0.2, 0.1)[offset]
        if (
            previous.artist
            and candidate.artist
            and previous.artist.casefold() == candidate.artist.casefold()
        ):
            penalty += recency * scale
        if (
            previous.album
            and candidate.album
            and previous.album.casefold() == candidate.album.casefold()
        ):
            penalty += recency * 0.5 * scale
    return penalty


def _sequence_evidence(
    ordered: list[int],
    tracks: list[SonicReadyTrack],
    intent: str,
) -> dict[str, Any]:
    pairs = list(pairwise(ordered))
    reliable_keys = sum(
        1
        for index in ordered
        if (_number(tracks[index].descriptors.get("chroma_tonal_confidence")) or 0)
        >= 0.12
    )
    tempos = [_mixable_tempo(tracks[index]) for index in ordered]
    energies = [_energy(tracks[index]) for index in ordered]
    return {
        "intent": intent,
        "tempo_evidence_count": sum(
            _number(tracks[index].descriptors.get("tempo_bpm")) is not None
            for index in ordered
        ),
        "harmonic_evidence_count": reliable_keys,
        "average_adjacent_tempo_change": (
            round(
                mean(
                    abs(tempos[left] - tempos[left + 1]) for left in range(len(pairs))
                ),
                2,
            )
            if pairs
            else 0.0
        ),
        "energy_start": round(energies[0], 3) if energies else None,
        "energy_end": round(energies[-1], 3) if energies else None,
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _distance(left: list[float], right: list[float]) -> float:
    return sqrt(
        sum(
            (left_value - right_value) ** 2
            for left_value, right_value in zip(left, right, strict=True)
        )
    )


def _centroid(rows: list[list[float]]) -> list[float]:
    return [mean(values) for values in zip(*rows, strict=True)] if rows else []


def _seeded_tie_break(local_track_id: int, random_seed: int) -> int:
    return (local_track_id * 1103515245 + random_seed * 12345) & 0xFFFFFFFF


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
