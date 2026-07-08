from __future__ import annotations

import re


ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
_ISRC_NON_CODE_CHARS_RE = re.compile(r"[^A-Za-z0-9]+")


def normalize_isrc_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = _ISRC_NON_CODE_CHARS_RE.sub("", value).upper()
    return normalized or None


def normalize_valid_isrc_code(value: object) -> str | None:
    normalized = normalize_isrc_code(value)
    if normalized is None or ISRC_RE.fullmatch(normalized) is None:
        return None

    return normalized
