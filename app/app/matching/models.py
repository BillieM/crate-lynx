from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> ConfidenceBand:
        if score > 0.85:
            return cls.HIGH
        if score >= 0.5:
            return cls.MEDIUM
        return cls.LOW


@dataclass(frozen=True, slots=True)
class MatchResult:
    local_track_id: int
    streaming_track_id: int
    match_method: str
    score: float
    confidence_band: ConfidenceBand
