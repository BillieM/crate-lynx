from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os

from rapidfuzz.distance import Levenshtein
from sqlalchemy import create_engine, select

from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand, MatchResult


@dataclass(frozen=True, slots=True)
class AcousticCandidate:
    streaming_track_id: int
    fingerprint: str


class AcousticMatcher:
    def __init__(self, *, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def match(
        self,
        local_track_id: int,
        candidates: Iterable[AcousticCandidate],
    ) -> MatchResult | None:
        local_fingerprint = self._lookup_local_fingerprint(local_track_id)
        if local_fingerprint is None:
            return None

        best_match: MatchResult | None = None
        best_score = -1.0

        for candidate in candidates:
            candidate_fingerprint = _normalize_fingerprint(candidate.fingerprint)
            if candidate_fingerprint is None:
                continue

            score = _score_fingerprints(local_fingerprint, candidate_fingerprint)
            if score <= best_score:
                continue

            best_score = score
            best_match = MatchResult(
                local_track_id=local_track_id,
                streaming_track_id=candidate.streaming_track_id,
                match_method="acoustic",
                score=score,
                confidence_band=ConfidenceBand.from_score(score),
            )

        return best_match

    def _lookup_local_fingerprint(self, local_track_id: int) -> str | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(local_tracks_table.c.fingerprint).where(
                        local_tracks_table.c.id == local_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return _normalize_fingerprint(row["fingerprint"])


def run_acoustic_match_job(
    local_track_id: int,
    candidates: list[dict[str, object]],
    *,
    database_url: str | None = None,
) -> MatchResult | None:
    resolved_database_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_database_url:
        raise RuntimeError("DATABASE_URL must be configured for acoustic matching")

    return AcousticMatcher(database_url=resolved_database_url).match(
        local_track_id,
        [_candidate_from_payload(candidate) for candidate in candidates],
    )


def _candidate_from_payload(payload: dict[str, object]) -> AcousticCandidate:
    streaming_track_id = payload.get("streaming_track_id")
    fingerprint = payload.get("fingerprint")

    if not isinstance(streaming_track_id, int):
        raise ValueError("Acoustic candidate payload is missing streaming_track_id")
    if not isinstance(fingerprint, str):
        raise ValueError("Acoustic candidate payload is missing fingerprint")

    return AcousticCandidate(
        streaming_track_id=streaming_track_id,
        fingerprint=fingerprint,
    )


def _score_fingerprints(left: str, right: str) -> float:
    return Levenshtein.normalized_similarity(left, right)


def _normalize_fingerprint(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None
