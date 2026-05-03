from __future__ import annotations

import logging

from app.matching.acoustic import (
    AcousticCandidate,
    AcousticMatcher,
    run_acoustic_match_job,
)
from app.matching.isrc import IsrcMatcher
from app.matching.models import ConfidenceBand, MatchResult
from app.matching.pipeline import (
    AcousticJobEnqueuer,
    MatchingPipeline,
    SuggestedLinkStore,
    fetch_suggested_links,
    run_matching_pipeline,
    suggested_links_table,
)
from app.matching.tags import TagMatcher


logger = logging.getLogger(__name__)


__all__ = [
    "AcousticCandidate",
    "AcousticJobEnqueuer",
    "AcousticMatcher",
    "ConfidenceBand",
    "IsrcMatcher",
    "MatchResult",
    "MatchingPipeline",
    "SuggestedLinkStore",
    "TagMatcher",
    "fetch_suggested_links",
    "run_acoustic_match_job",
    "run_matching_pipeline",
    "suggested_links_table",
]
