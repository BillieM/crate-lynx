from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class ScoreIdCursor:
    score: float
    row_id: int


def encode_score_id_cursor(*, score: float, row_id: int) -> str:
    payload = json.dumps(
        {"score": score, "id": row_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_score_id_cursor(cursor: str) -> ScoreIdCursor:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(f"{cursor}{padding}".encode("ascii"))
        payload: Any = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid pagination cursor") from exc

    if not isinstance(payload, dict):
        raise ValueError("Invalid pagination cursor")

    score = payload.get("score")
    row_id = payload.get("id")
    if not isinstance(score, int | float) or not isinstance(row_id, int):
        raise ValueError("Invalid pagination cursor")

    return ScoreIdCursor(score=float(score), row_id=row_id)
