from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def run_matching_pipeline(local_track_id: int) -> None:
    logger.info(
        "Matching pipeline placeholder queued for local_track_id=%s",
        local_track_id,
    )
