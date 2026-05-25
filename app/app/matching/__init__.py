from __future__ import annotations

import logging

from app.matching.isrc import IsrcMatcher
from app.matching.jobs import (
    LocalTrackRematchBackfillJobEnqueuer,
    MatchingJobEnqueuer,
    run_matching_pipeline,
    run_unresolved_local_tracks_rematch_backfill,
)
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
    "LocalTrackRematchBackfillJobEnqueuer",
    "MatchResult",
    "MatchingJobEnqueuer",
    "MatchingPipeline",
    "SuggestedLinkStore",
    "TagMatcher",
    "fetch_suggested_links",
    "run_matching_pipeline",
    "run_unresolved_local_tracks_rematch_backfill",
    "suggested_links_table",
]
