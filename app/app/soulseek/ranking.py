from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import PureWindowsPath
import re
from typing import Any

from rapidfuzz import fuzz

from app.ingestion.pipeline import LOSSLESS_AUDIO_EXTENSIONS, SUPPORTED_AUDIO_EXTENSIONS
from app.matching.tags import normalize_match_text, score_track_tags
from app.soulseek.models import StreamingTrackForSoulseek


MIN_CANDIDATE_SCORE = 0.36
WEAK_TOP_CANDIDATE_SCORE = 0.68
SEVERE_DURATION_MISMATCH_MS = 60_000
MAX_CANDIDATES = 50
_WHITESPACE_RE = re.compile(r"\s+")
_QUERY_PUNCTUATION_RE = re.compile(r"[^\w\s']+")
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\+|/|\band\b|\bfeat\.?\b|\bfeaturing\b|\bft\.?\b|\bwith\b|\bvs\.?\b|\bx\b)\s*",
    re.IGNORECASE,
)
_TITLE_FEATURE_PAREN_RE = re.compile(
    r"\s*[\[(][^\])]*\b(?:ft|feat|featuring|with)\b[^\])]*[\])]",
    re.IGNORECASE,
)
_TITLE_FEATURE_SUFFIX_RE = re.compile(
    r"\s+(?:-|:)?\s*\b(?:ft|feat|featuring|with)\b\.?.*$",
    re.IGNORECASE,
)
_TITLE_VERSION_PAREN_RE = re.compile(
    r"\s*[\[(][^\])]*\b(?:remix|edit|mix|version|vip|dub|instrumental|remaster(?:ed)?)\b[^\])]*[\])]",
    re.IGNORECASE,
)
_TITLE_VERSION_SUFFIX_RE = re.compile(
    r"\s+(?:-|:)?\s*\b(?:original|extended|radio|club|edit|mix|version|vip|dub|instrumental|remaster(?:ed)?)\b.*$",
    re.IGNORECASE,
)
_LEADING_TRACK_NUMBER_RE = re.compile(r"^\s*(?:\d{1,3}|[A-D]\d{1,2})\s*[\.\-_]\s*")
_TRAILING_BRACKET_RE = re.compile(r"\s*[\[(][^\])]*[\])]\s*$")
_TRAILING_YEAR_RE = re.compile(r"\s*[-\[(]?\d{4}[-\])]?\s*$")
MAX_QUERY_VARIANTS = 12
_GENERIC_TITLE_ONLY_QUERIES = {
    "intro",
    "outro",
    "interlude",
    "skit",
    "untitled",
    "track",
}


@dataclass(frozen=True, slots=True)
class RankedSoulseekCandidate:
    slskd_search_id: str
    username: str
    filename: str
    size: int
    extension: str | None
    duration_seconds: int | None
    bit_rate: int | None
    bit_depth: int | None
    sample_rate: int | None
    is_variable_bit_rate: bool | None
    has_free_upload_slot: bool
    queue_length: int | None
    upload_speed: int | None
    score: float


def soulseek_query_for_track(
    track: StreamingTrackForSoulseek, *, include_album: bool = False
) -> str:
    parts = [track.artist, track.title]
    if include_album and track.album:
        parts.append(track.album)
    return _normalize_query(" ".join(parts))


def soulseek_query_variants_for_track(track: StreamingTrackForSoulseek) -> list[str]:
    full_artist = _normalize_query(track.artist)
    artist_candidates = _artist_query_candidates(track.artist)
    title_candidates = _title_query_candidates(track.title)
    broad_title = title_candidates[-1]

    variants = [soulseek_query_for_track(track)]
    if artist_candidates:
        primary_artist = artist_candidates[0]
        variants.append(_join_query(primary_artist, broad_title))
        variants.append(_join_query(primary_artist, title_candidates[0]))

    for artist in artist_candidates[1:4]:
        variants.append(_join_query(artist, broad_title))
        variants.append(_join_query(artist, title_candidates[0]))

    for title in title_candidates[1:]:
        variants.append(_join_query(full_artist, title))

    if track.album:
        album_candidates = _title_query_candidates(track.album)
        variants.append(_join_query(full_artist, album_candidates[-1]))
        if artist_candidates:
            variants.append(_join_query(artist_candidates[0], album_candidates[-1]))

    for title in title_candidates:
        if _is_title_only_searchable(title):
            variants.append(title)

    return _unique_queries(variants)[:MAX_QUERY_VARIANTS]


def rank_search_responses(
    *,
    diagnostics: Counter[str] | None = None,
    search_id: str,
    track: StreamingTrackForSoulseek,
    responses: list[dict[str, Any]],
) -> list[RankedSoulseekCandidate]:
    candidates: list[RankedSoulseekCandidate] = []
    seen: set[tuple[str, str]] = set()
    for response in responses:
        username = _string_value(response, "username", "Username")
        if username is None:
            _reject(diagnostics, "missing_username")
            continue

        files = [
            (*_files(response, "files", "Files"), False),
            (*_files(response, "lockedFiles", "LockedFiles"), True),
        ]
        flattened_files: list[tuple[dict[str, Any], bool]] = []
        for file_group, locked in files:
            flattened_files.extend((file_data, locked) for file_data in file_group)

        for file_data, inherited_locked in flattened_files:
            candidate = _candidate_from_file(
                file_data,
                diagnostics=diagnostics,
                has_free_upload_slot=_bool_value(
                    response,
                    "hasFreeUploadSlot",
                    "HasFreeUploadSlot",
                    default=False,
                ),
                inherited_locked=inherited_locked,
                queue_length=_int_value(response, "queueLength", "QueueLength"),
                search_id=search_id,
                track=track,
                upload_speed=_int_value(response, "uploadSpeed", "UploadSpeed"),
                username=username,
            )
            if candidate is None:
                continue

            dedupe_key = (candidate.username.casefold(), candidate.filename.casefold())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(candidate)

    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates[:MAX_CANDIDATES]


def merge_ranked_candidates(
    first: list[RankedSoulseekCandidate],
    second: list[RankedSoulseekCandidate],
) -> list[RankedSoulseekCandidate]:
    merged: dict[tuple[str, str], RankedSoulseekCandidate] = {}
    for candidate in [*first, *second]:
        key = (candidate.username.casefold(), candidate.filename.casefold())
        existing = merged.get(key)
        if existing is None or candidate.score > existing.score:
            merged[key] = candidate

    ranked = list(merged.values())
    ranked.sort(key=lambda candidate: candidate.score, reverse=True)
    return ranked[:MAX_CANDIDATES]


def is_weak_candidate_set(candidates: list[RankedSoulseekCandidate]) -> bool:
    return not candidates or candidates[0].score < WEAK_TOP_CANDIDATE_SCORE


def _candidate_from_file(
    file_data: dict[str, Any],
    *,
    diagnostics: Counter[str] | None,
    has_free_upload_slot: bool,
    inherited_locked: bool,
    queue_length: int | None,
    search_id: str,
    track: StreamingTrackForSoulseek,
    upload_speed: int | None,
    username: str,
) -> RankedSoulseekCandidate | None:
    if inherited_locked or _bool_value(
        file_data, "isLocked", "IsLocked", default=False
    ):
        return _reject(diagnostics, "locked")

    filename = _string_value(file_data, "filename", "Filename")
    size = _int_value(file_data, "size", "Size")
    if filename is None or size is None or size <= 0:
        return _reject(diagnostics, "missing_file_data")
    if _has_dangerous_path(filename):
        return _reject(diagnostics, "unsafe_path")

    extension = _extension(filename, _string_value(file_data, "extension", "Extension"))
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        return _reject(diagnostics, "unsupported_extension")

    duration_seconds = _int_value(file_data, "length", "Length")
    duration_ms = duration_seconds * 1000 if duration_seconds is not None else None
    if _has_severe_duration_mismatch(track.duration_ms, duration_ms):
        return _reject(diagnostics, "duration_mismatch")

    candidate_title = _candidate_title(filename)
    artist_context = _candidate_artist_context(filename)
    album_context = _candidate_album_context(filename)
    path_context = _candidate_path_context(filename)
    normalized_title = normalize_match_text(track.title)
    normalized_artist = normalize_match_text(track.artist)
    normalized_album = normalize_match_text(track.album)
    normalized_candidate_title = normalize_match_text(candidate_title)
    normalized_artist_context = normalize_match_text(artist_context)
    normalized_album_context = normalize_match_text(album_context)
    normalized_path_context = normalize_match_text(path_context)
    if (
        normalized_title is None
        or normalized_artist is None
        or normalized_candidate_title is None
        or normalized_path_context is None
    ):
        return _reject(diagnostics, "unrankable_text")

    title_similarity = max(
        fuzz.token_set_ratio(normalized_title, normalized_candidate_title) / 100,
        fuzz.token_set_ratio(normalized_title, normalized_path_context) / 100,
    )
    artist_similarity = (
        fuzz.token_set_ratio(
            normalized_artist,
            normalized_artist_context or normalized_path_context,
        )
        / 100
    )
    if title_similarity < 0.45 or artist_similarity < 0.20:
        return _reject(diagnostics, "weak_text_match")

    tag_score = score_track_tags(
        left_title=normalized_title,
        left_artist=normalized_artist,
        left_album=normalized_album,
        left_duration_ms=track.duration_ms,
        right_title=normalized_candidate_title,
        right_artist=normalized_artist_context or normalized_path_context,
        right_album=normalized_album_context or normalized_path_context,
        right_duration_ms=duration_ms,
    )
    score = (
        tag_score * 0.58
        + _album_bonus(
            normalized_album, normalized_album_context or normalized_path_context
        )
        * 0.07
        + _duration_bonus(track.duration_ms, duration_ms) * 0.12
        + _extension_bonus(extension) * 0.07
        + _quality_bonus(
            bit_depth=_int_value(file_data, "bitDepth", "BitDepth"),
            bit_rate=_int_value(file_data, "bitRate", "BitRate"),
            extension=extension,
        )
        * 0.08
        + (0.04 if has_free_upload_slot else 0.0)
        + _queue_bonus(queue_length) * 0.02
        + _upload_speed_bonus(upload_speed) * 0.02
    )
    if score < MIN_CANDIDATE_SCORE:
        return _reject(diagnostics, "low_score")

    return RankedSoulseekCandidate(
        slskd_search_id=search_id,
        username=username,
        filename=filename,
        size=size,
        extension=extension,
        duration_seconds=duration_seconds,
        bit_rate=_int_value(file_data, "bitRate", "BitRate"),
        bit_depth=_int_value(file_data, "bitDepth", "BitDepth"),
        sample_rate=_int_value(file_data, "sampleRate", "SampleRate"),
        is_variable_bit_rate=_optional_bool_value(
            file_data,
            "isVariableBitRate",
            "IsVariableBitRate",
        ),
        has_free_upload_slot=has_free_upload_slot,
        queue_length=queue_length,
        upload_speed=upload_speed,
        score=min(score, 1.0),
    )


def _files(response: dict[str, Any], *keys: str) -> tuple[list[dict[str, Any]]]:
    value = _value(response, *keys)
    if not isinstance(value, list):
        return ([],)
    return ([item for item in value if isinstance(item, dict)],)


def _value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _string_value(mapping: dict[str, Any], *keys: str) -> str | None:
    value = _value(mapping, *keys)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _int_value(mapping: dict[str, Any], *keys: str) -> int | None:
    value = _value(mapping, *keys)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _bool_value(mapping: dict[str, Any], *keys: str, default: bool) -> bool:
    value = _value(mapping, *keys)
    return value if isinstance(value, bool) else default


def _optional_bool_value(mapping: dict[str, Any], *keys: str) -> bool | None:
    value = _value(mapping, *keys)
    return value if isinstance(value, bool) else None


def _normalize_query(value: str) -> str:
    without_punctuation = _QUERY_PUNCTUATION_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", without_punctuation.strip())


def _join_query(*parts: str | None) -> str:
    return _normalize_query(" ".join(part for part in parts if part))


def _artist_query_candidates(artist: str) -> list[str]:
    normalized_full = _normalize_query(artist)
    split_artists = [
        _normalize_query(part)
        for part in _ARTIST_SPLIT_RE.split(artist)
        if _normalize_query(part)
    ]
    return _unique_queries([*split_artists, normalized_full])


def _title_query_candidates(title: str) -> list[str]:
    without_features = _TITLE_FEATURE_SUFFIX_RE.sub(
        "",
        _TITLE_FEATURE_PAREN_RE.sub("", title),
    )
    without_versions = _TITLE_VERSION_SUFFIX_RE.sub(
        "",
        _TITLE_VERSION_PAREN_RE.sub("", without_features),
    )
    return _unique_queries(
        [
            _normalize_query(title),
            _normalize_query(without_features),
            _normalize_query(without_versions),
        ]
    )


def _unique_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.casefold()
        if query and key not in seen:
            unique.append(query)
            seen.add(key)
    return unique


def _is_title_only_searchable(title: str) -> bool:
    normalized = _normalize_query(title).casefold()
    if len(normalized) < 4:
        return False
    tokens = normalized.split()
    return not (len(tokens) == 1 and tokens[0] in _GENERIC_TITLE_ONLY_QUERIES)


def _extension(filename: str, raw_extension: str | None) -> str | None:
    if raw_extension:
        extension = raw_extension.casefold()
        if not extension.startswith("."):
            extension = "." + extension
        return extension

    suffix = PureWindowsPath(filename.replace("/", "\\")).suffix.casefold()
    return suffix or None


def _filename_stem(filename: str) -> str:
    normalized = filename.replace("/", "\\")
    return PureWindowsPath(normalized).stem


def _path_parts(filename: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", filename) if part]


def _clean_path_name(value: str) -> str:
    cleaned = value.replace("_", " ")
    cleaned = _LEADING_TRACK_NUMBER_RE.sub("", cleaned)
    cleaned = _TRAILING_BRACKET_RE.sub("", cleaned)
    cleaned = _TRAILING_YEAR_RE.sub("", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned.strip())


def _candidate_title(filename: str) -> str:
    stem = _clean_path_name(_filename_stem(filename))
    if " - " in stem:
        return _clean_path_name(stem.rsplit(" - ", 1)[1])
    return stem


def _candidate_artist_context(filename: str) -> str:
    stem = _clean_path_name(_filename_stem(filename))
    candidates: list[str] = []
    if " - " in stem:
        candidates.append(_clean_path_name(stem.rsplit(" - ", 1)[0]))
    candidates.extend(_clean_path_name(part) for part in _path_parts(filename)[:-1])
    return " ".join(part for part in candidates if part)


def _candidate_album_context(filename: str) -> str:
    parts = [_clean_path_name(part) for part in _path_parts(filename)[:-1]]
    return " ".join(part for part in parts if part)


def _candidate_path_context(filename: str) -> str:
    parts = [_clean_path_name(part) for part in _path_parts(filename)]
    return " ".join(part for part in parts if part)


def _has_dangerous_path(filename: str) -> bool:
    if filename.startswith(("/", "\\")):
        return True

    return any(part in {"", ".", ".."} for part in re.split(r"[\\/]+", filename))


def _has_severe_duration_mismatch(
    expected_duration_ms: int | None,
    candidate_duration_ms: int | None,
) -> bool:
    if expected_duration_ms is None or candidate_duration_ms is None:
        return False

    tolerance = max(SEVERE_DURATION_MISMATCH_MS, int(expected_duration_ms * 0.25))
    return abs(expected_duration_ms - candidate_duration_ms) > tolerance


def _album_bonus(album: str | None, filename_stem: str) -> float:
    if album is None:
        return 0.0
    return fuzz.token_set_ratio(album, filename_stem) / 100


def _duration_bonus(
    expected_duration_ms: int | None,
    candidate_duration_ms: int | None,
) -> float:
    if expected_duration_ms is None or candidate_duration_ms is None:
        return 0.0

    delta = abs(expected_duration_ms - candidate_duration_ms)
    if delta <= 5_000:
        return 1.0
    if delta >= SEVERE_DURATION_MISMATCH_MS:
        return 0.0
    return 1.0 - (delta / SEVERE_DURATION_MISMATCH_MS)


def _extension_bonus(extension: str | None) -> float:
    if extension in LOSSLESS_AUDIO_EXTENSIONS:
        return 1.0
    if extension == ".mp3":
        return 0.6
    return 0.0


def _quality_bonus(
    *, bit_depth: int | None, bit_rate: int | None, extension: str | None
) -> float:
    if bit_depth is not None and bit_depth >= 16:
        return 1.0
    if extension in LOSSLESS_AUDIO_EXTENSIONS:
        return 0.9
    if bit_rate is None:
        return 0.2
    if bit_rate >= 320:
        return 1.0
    if bit_rate >= 256:
        return 0.75
    if bit_rate >= 192:
        return 0.55
    return 0.25


def _queue_bonus(queue_length: int | None) -> float:
    if queue_length is None:
        return 0.2
    if queue_length <= 0:
        return 1.0
    if queue_length <= 5:
        return 0.75
    if queue_length <= 20:
        return 0.45
    return 0.1


def _upload_speed_bonus(upload_speed: int | None) -> float:
    if upload_speed is None or upload_speed <= 0:
        return 0.0
    if upload_speed >= 1_000_000:
        return 1.0
    if upload_speed >= 250_000:
        return 0.7
    if upload_speed >= 50_000:
        return 0.4
    return 0.15


def _reject(
    diagnostics: Counter[str] | None,
    reason: str,
) -> None:
    if diagnostics is not None:
        diagnostics[reason] += 1
    return None
