from __future__ import annotations

import logging

from app.matching.acoustic import (
    AcousticCandidate,
    AcousticMatcher,
    DownloadedStreamingAudio,
    StreamingTrackAudioDownloader,
    YtDlpAudioDownloader,
    run_acoustic_match_job,
)
from app.matching.isrc import IsrcMatcher
from app.matching.jobs import MatchingJobEnqueuer, run_matching_pipeline
from app.matching.models import ConfidenceBand, MatchResult
from app.matching.pipeline import (
    AcousticJobEnqueuer,
    MatchingPipeline,
    SuggestedLinkStore,
    fetch_suggested_links,
    suggested_links_table,
)
from app.matching.tags import TagMatcher


logger = logging.getLogger(__name__)


__all__ = [
    "AcousticCandidate",
    "AcousticJobEnqueuer",
    "AcousticMatcher",
    "ConfidenceBand",
    "DownloadedStreamingAudio",
    "IsrcMatcher",
    "MatchResult",
    "MatchingJobEnqueuer",
    "MatchingPipeline",
    "StreamingTrackAudioDownloader",
    "SuggestedLinkStore",
    "TagMatcher",
    "YtDlpAudioDownloader",
    "fetch_suggested_links",
    "run_acoustic_match_job",
    "run_matching_pipeline",
    "suggested_links_table",
]
