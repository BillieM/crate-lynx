from __future__ import annotations

import logging

from app.matching.isrc import IsrcMatcher
from app.matching.jobs import MatchingJobEnqueuer, run_matching_pipeline
from app.matching.models import ConfidenceBand, MatchResult
from app.matching.pipeline import (
    MatchingPipeline,
    SuggestedLinkStore,
    fetch_suggested_links,
    suggested_links_table,
)
from app.matching.tags import TagMatcher


logger = logging.getLogger(__name__)


__all__ = [
    "ConfidenceBand",
    "IsrcMatcher",
    "MatchResult",
    "MatchingJobEnqueuer",
    "MatchingPipeline",
    "SuggestedLinkStore",
    "TagMatcher",
    "fetch_suggested_links",
    "run_matching_pipeline",
    "suggested_links_table",
]
