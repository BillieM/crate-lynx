from __future__ import annotations

import logging

from app.matching.isrc import IsrcMatcher
from app.matching.models import ConfidenceBand, MatchResult
from app.matching.tags import TagMatcher


logger = logging.getLogger(__name__)


def run_matching_pipeline(local_track_id: int) -> None:
    logger.info(
        "Matching pipeline placeholder queued for local_track_id=%s",
        local_track_id,
    )


__all__ = [
    "ConfidenceBand",
    "IsrcMatcher",
    "MatchResult",
    "TagMatcher",
    "run_matching_pipeline",
]
