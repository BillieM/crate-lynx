from __future__ import annotations

from datetime import UTC, datetime

from app.autopilot.gates import evaluate_unattended_candidates
from app.soulseek.models import SoulseekCandidateRecord


def _candidate(
    candidate_id: str,
    *,
    identity: float,
    version: float,
    quality: float,
    duration_seconds: int = 240,
    size: int = 8_000_000,
) -> SoulseekCandidateRecord:
    return SoulseekCandidateRecord(
        id=candidate_id,
        acquisition_id="acquisition-1",
        slskd_search_id="search-1",
        username="peer",
        filename=f"Artist/Track-{candidate_id}.flac",
        size=size,
        extension=".flac",
        duration_seconds=duration_seconds,
        bit_rate=None,
        bit_depth=16,
        sample_rate=44_100,
        is_variable_bit_rate=None,
        has_free_upload_slot=True,
        queue_length=0,
        upload_speed=1_000_000,
        score=0.9,
        identity_confidence=identity,
        version_confidence=version,
        quality_score=quality,
        created_at=datetime.now(UTC),
    )


def test_quality_cannot_compensate_for_weak_identity() -> None:
    decision = evaluate_unattended_candidates(
        candidates=[
            _candidate(
                "high-quality-wrong-track",
                identity=0.60,
                version=1.0,
                quality=1.0,
            )
        ],
        expected_duration_ms=240_000,
    )

    assert decision.accepted is False
    assert decision.reason_code == "weak_identity"


def test_version_and_duration_are_independent_hard_gates() -> None:
    version = evaluate_unattended_candidates(
        candidates=[
            _candidate("wrong-version", identity=0.95, version=0.30, quality=1.0)
        ],
        expected_duration_ms=240_000,
    )
    duration = evaluate_unattended_candidates(
        candidates=[
            _candidate(
                "wrong-duration",
                identity=0.95,
                version=1.0,
                quality=1.0,
                duration_seconds=300,
            )
        ],
        expected_duration_ms=240_000,
    )

    assert version.reason_code == "version_mismatch"
    assert duration.reason_code == "duration_mismatch"


def test_runner_up_ambiguity_routes_to_review() -> None:
    decision = evaluate_unattended_candidates(
        candidates=[
            _candidate("first", identity=0.95, version=1.0, quality=0.7),
            _candidate("second", identity=0.94, version=1.0, quality=1.0),
        ],
        expected_duration_ms=240_000,
    )

    assert decision.accepted is False
    assert decision.reason_code == "ambiguous_runner_up"


def test_compatible_candidate_passes_all_unattended_gates() -> None:
    decision = evaluate_unattended_candidates(
        candidates=[
            _candidate("accepted", identity=0.95, version=1.0, quality=0.8),
            _candidate("distant-runner-up", identity=0.70, version=1.0, quality=1.0),
        ],
        expected_duration_ms=240_000,
    )

    assert decision.accepted is True
    assert decision.candidate is not None
    assert decision.candidate.id == "accepted"


def test_incompatible_top_identity_does_not_mask_passing_candidate() -> None:
    decision = evaluate_unattended_candidates(
        candidates=[
            _candidate(
                "top-wrong-version",
                identity=0.99,
                version=0.20,
                quality=1.0,
            ),
            _candidate(
                "top-wrong-duration",
                identity=0.98,
                version=1.0,
                quality=1.0,
                duration_seconds=360,
            ),
            _candidate(
                "passing",
                identity=0.94,
                version=1.0,
                quality=0.6,
            ),
        ],
        expected_duration_ms=240_000,
    )

    assert decision.accepted is True
    assert decision.candidate is not None
    assert decision.candidate.id == "passing"
    assert decision.quality_score == 0.6
