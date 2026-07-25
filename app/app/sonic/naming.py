from __future__ import annotations

import re
from math import ceil
from typing import Any

STYLE_TAG_MIN_AGREEMENT = 0.65
STYLE_TAG_MIN_RUNNER_UP_MARGIN = 0.2
GENERIC_STYLE_TAGS = {
    "alternative",
    "dance",
    "electronic",
    "electronica",
    "music",
    "other",
    "pop",
    "unknown",
    "various",
}
STYLE_TEMPO_RANGES = {
    "ambient": (45, 115),
    "ambient dub": (65, 115),
    "breakbeat": (110, 150),
    "breaks": (110, 150),
    "deep house": (112, 128),
    "disco": (105, 135),
    "drum and bass": (155, 180),
    "dnb": (155, 180),
    "dub": (65, 125),
    "dubstep": (130, 145),
    "garage": (118, 140),
    "grime": (130, 145),
    "house": (112, 135),
    "jungle": (150, 180),
    "tech house": (118, 135),
    "techno": (118, 155),
    "trance": (125, 150),
    "uk garage": (118, 140),
}
ACRONYMS = {
    "dnb": "DnB",
    "edm": "EDM",
    "idm": "IDM",
    "uk": "UK",
}


def select_intrinsic_style_label(summary: dict[str, Any]) -> str | None:
    common_tags = summary.get("common_tags")
    track_count = summary.get("track_count")
    if not isinstance(common_tags, list) or not isinstance(track_count, int):
        return None
    if track_count <= 0:
        return None

    candidates = []
    for raw_tag in common_tags:
        if not isinstance(raw_tag, dict):
            continue
        raw_value = raw_tag.get("value")
        count = raw_tag.get("count")
        if not isinstance(raw_value, str) or not isinstance(count, int):
            continue
        normalized = normalize_style_tag(raw_value)
        if (
            not normalized
            or normalized in GENERIC_STYLE_TAGS
            or normalized not in STYLE_TEMPO_RANGES
        ):
            continue
        candidates.append((normalized, count))
    if not candidates:
        return None

    candidates.sort(key=lambda entry: (-entry[1], entry[0]))
    normalized, count = candidates[0]
    required = max(2, ceil(track_count * STYLE_TAG_MIN_AGREEMENT))
    if track_count <= 2:
        required = track_count
    if count < required:
        return None
    runner_up_count = candidates[1][1] if len(candidates) > 1 else 0
    if (count - runner_up_count) / track_count < STYLE_TAG_MIN_RUNNER_UP_MARGIN:
        return None

    bpm = summary.get("bpm")
    if not isinstance(bpm, dict):
        return None
    median_bpm = bpm.get("median")
    if isinstance(median_bpm, bool) or not isinstance(median_bpm, int | float):
        return None
    if not _tempo_agrees(float(median_bpm), STYLE_TEMPO_RANGES[normalized]):
        return None
    return format_style_tag(normalized)


def intrinsic_name_candidates(
    components: dict[str, Any],
    *,
    fallback: str,
) -> list[str]:
    style = _string(components.get("style"))
    tempo = _string(components.get("tempo"))
    role = _string(components.get("role"))
    energy = components.get("energy")
    energy_band = _string(energy.get("band")) if isinstance(energy, dict) else None
    raw_traits = components.get("traits")
    traits = [
        value
        for value in (raw_traits if isinstance(raw_traits, list) else [])
        if isinstance(value, str) and value
    ]
    trait = " + ".join(traits[:2]) if traits else None

    candidates = []
    if style and role and tempo:
        candidates.append(f"{style} / {role} / {tempo}")
    if style and trait and tempo:
        candidates.append(f"{style} / {trait} / {tempo}")
    if style and tempo:
        candidates.append(f"{style} / {tempo}")
    if energy_band and tempo:
        candidates.append(f"{tempo} / {energy_band}")
    if role and trait and tempo:
        candidates.append(f"{role} / {trait} / {tempo}")
    if role and tempo:
        candidates.append(f"{role} / {tempo}")
    if trait and tempo:
        candidates.append(f"{trait} / {tempo}")
    if style:
        candidates.append(style)
    if tempo:
        candidates.append(tempo)
    if role:
        candidates.append(role)
    if energy_band:
        candidates.append(energy_band)
    candidates.append(fallback)
    return _unique(candidates)


def normalize_style_tag(value: str) -> str:
    normalized = re.sub(r"[_/]+", " ", value.casefold())
    normalized = re.sub(r"[^a-z0-9&+ -]", "", normalized)
    normalized = " ".join(normalized.split())
    aliases = {
        "drum & bass": "drum and bass",
        "drum n bass": "drum and bass",
        "drumandbass": "drum and bass",
        "ukg": "uk garage",
    }
    return aliases.get(normalized, normalized)


def format_style_tag(value: str) -> str:
    return " ".join(ACRONYMS.get(part, part.capitalize()) for part in value.split())


def _tempo_agrees(tempo: float, expected_range: tuple[int, int]) -> bool:
    low, high = expected_range
    candidates = {tempo, tempo * 2.0, tempo / 2.0}
    return any(low - 3 <= candidate <= high + 3 for candidate in candidates)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result
