from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.local_tracks.store import local_tracks_table
from app.soulseek.models import (
    SoulseekAcquisitionRecord,
    SoulseekCandidateRecord,
)

MIN_IDENTITY_CONFIDENCE = 0.82
MIN_VERSION_CONFIDENCE = 0.80
MIN_QUALITY_SCORE = 0.40
MIN_RUNNER_UP_MARGIN = 0.08
MIN_AUDIO_BYTES = 512 * 1024
MAX_DURATION_DELTA_MS = 8_000
MAX_DURATION_DELTA_RATIO = 0.04


@dataclass(frozen=True, slots=True)
class CandidateGateDecision:
    accepted: bool
    reason_code: str
    detail: str
    candidate: SoulseekCandidateRecord | None
    identity_confidence: float | None = None
    version_confidence: float | None = None
    quality_score: float | None = None
    runner_up_margin: float | None = None
    expected_duration_ms: int | None = None
    candidate_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class ImportVerificationDecision:
    accepted: bool
    reason_code: str
    detail: str
    actual_duration_ms: int | None = None


def evaluate_unattended_candidates(
    *,
    candidates: list[SoulseekCandidateRecord],
    expected_duration_ms: int | None,
) -> CandidateGateDecision:
    """Select by identity/version first; quality only ranks compatible peers."""
    complete = [
        candidate
        for candidate in candidates
        if candidate.identity_confidence is not None
        and candidate.version_confidence is not None
        and candidate.quality_score is not None
    ]
    if not complete:
        return CandidateGateDecision(
            accepted=False,
            reason_code="missing_separated_evidence",
            detail=(
                "No candidate has separate identity, version, and transfer-quality "
                "evidence"
            ),
            candidate=None,
            expected_duration_ms=expected_duration_ms,
        )

    ranked = sorted(
        complete,
        key=lambda candidate: (
            float(candidate.identity_confidence or 0),
            float(candidate.version_confidence or 0),
            float(candidate.quality_score or 0),
            candidate.id,
        ),
        reverse=True,
    )
    hard_compatible = [
        candidate
        for candidate in ranked
        if _candidate_is_hard_compatible(
            candidate,
            expected_duration_ms=expected_duration_ms,
        )
    ]
    selected = hard_compatible[0] if hard_compatible else ranked[0]
    runner_up = hard_compatible[1] if len(hard_compatible) > 1 else None
    identity = float(selected.identity_confidence or 0)
    version = float(selected.version_confidence or 0)
    quality = float(selected.quality_score or 0)
    runner_up_margin = (
        1.0
        if runner_up is None
        else _identity_version_score(selected) - _identity_version_score(runner_up)
    )
    candidate_duration_ms = (
        selected.duration_seconds * 1000
        if selected.duration_seconds is not None
        else None
    )
    evidence = {
        "candidate": selected,
        "identity_confidence": identity,
        "version_confidence": version,
        "quality_score": quality,
        "runner_up_margin": runner_up_margin,
        "expected_duration_ms": expected_duration_ms,
        "candidate_duration_ms": candidate_duration_ms,
    }

    if identity < MIN_IDENTITY_CONFIDENCE:
        return CandidateGateDecision(
            accepted=False,
            reason_code="weak_identity",
            detail=f"Identity confidence {identity:.3f} is below the unattended gate",
            **evidence,
        )
    if version < MIN_VERSION_CONFIDENCE:
        return CandidateGateDecision(
            accepted=False,
            reason_code="version_mismatch",
            detail=f"Version confidence {version:.3f} is below the unattended gate",
            **evidence,
        )
    if expected_duration_ms is None or candidate_duration_ms is None:
        return CandidateGateDecision(
            accepted=False,
            reason_code="duration_unavailable",
            detail="Unattended acquisition requires expected and candidate durations",
            **evidence,
        )
    if not duration_is_compatible(expected_duration_ms, candidate_duration_ms):
        return CandidateGateDecision(
            accepted=False,
            reason_code="duration_mismatch",
            detail=(
                f"Candidate duration {candidate_duration_ms}ms materially differs "
                f"from expected {expected_duration_ms}ms"
            ),
            **evidence,
        )
    if runner_up_margin < MIN_RUNNER_UP_MARGIN:
        return CandidateGateDecision(
            accepted=False,
            reason_code="ambiguous_runner_up",
            detail=(
                f"Identity/version runner-up margin {runner_up_margin:.3f} is below "
                "the unattended gate"
            ),
            **evidence,
        )
    if selected.size < MIN_AUDIO_BYTES:
        return CandidateGateDecision(
            accepted=False,
            reason_code="implausible_file_size",
            detail=f"Candidate file is only {selected.size} bytes",
            **evidence,
        )
    if quality < MIN_QUALITY_SCORE:
        return CandidateGateDecision(
            accepted=False,
            reason_code="weak_transfer_quality",
            detail=(
                f"Transfer quality {quality:.3f} is below the unattended desirability "
                "gate"
            ),
            **evidence,
        )
    return CandidateGateDecision(
        accepted=True,
        reason_code="accepted",
        detail=(
            "Identity, version, duration, ambiguity, format, and transfer-quality "
            "gates passed independently"
        ),
        **evidence,
    )


def verify_imported_audio(
    *,
    acquisition: SoulseekAcquisitionRecord,
    candidate: SoulseekCandidateRecord,
    engine: Engine,
    library_root: Path | str,
) -> ImportVerificationDecision:
    if acquisition.local_track_id is None:
        return ImportVerificationDecision(
            accepted=False,
            reason_code="not_ingested",
            detail="The unattended acquisition has no ingested local track",
        )
    with engine.connect() as connection:
        relative_path = connection.execute(
            select(local_tracks_table.c.library_root_rel_path).where(
                local_tracks_table.c.id == acquisition.local_track_id
            )
        ).scalar_one_or_none()
    if not isinstance(relative_path, str) or not relative_path:
        return ImportVerificationDecision(
            accepted=False,
            reason_code="local_track_missing",
            detail="The ingested local-track record has no usable library path",
        )
    path = Path(relative_path)
    if not path.is_absolute():
        path = Path(library_root) / path
    try:
        if path.stat().st_size < MIN_AUDIO_BYTES:
            return ImportVerificationDecision(
                accepted=False,
                reason_code="corrupt_or_truncated",
                detail=f"Imported audio is implausibly small: {path.stat().st_size} bytes",
            )
        audio = MutagenFile(path)
    except (OSError, ValueError) as exc:
        return ImportVerificationDecision(
            accepted=False,
            reason_code="unreadable_audio",
            detail=f"Imported audio could not be read: {exc}",
        )
    if audio is None or getattr(audio, "info", None) is None:
        return ImportVerificationDecision(
            accepted=False,
            reason_code="unreadable_audio",
            detail="Imported file is not recognised as readable audio",
        )
    length = getattr(audio.info, "length", None)
    if not isinstance(length, (float, int)) or length <= 0:
        return ImportVerificationDecision(
            accepted=False,
            reason_code="duration_unavailable",
            detail="Imported audio has no readable positive duration",
        )
    actual_duration_ms = round(float(length) * 1000)
    expected_duration_ms = (
        candidate.duration_seconds * 1000
        if candidate.duration_seconds is not None
        else None
    )
    if expected_duration_ms is None or not duration_is_compatible(
        expected_duration_ms, actual_duration_ms
    ):
        return ImportVerificationDecision(
            accepted=False,
            reason_code="post_import_duration_mismatch",
            detail=(
                f"Imported audio duration {actual_duration_ms}ms does not match the "
                f"selected transfer duration {expected_duration_ms}ms"
            ),
            actual_duration_ms=actual_duration_ms,
        )
    if (
        candidate.identity_confidence is None
        or candidate.identity_confidence < MIN_IDENTITY_CONFIDENCE
        or candidate.version_confidence is None
        or candidate.version_confidence < MIN_VERSION_CONFIDENCE
    ):
        return ImportVerificationDecision(
            accepted=False,
            reason_code="identity_evidence_changed",
            detail="Persisted unattended identity/version evidence no longer passes",
            actual_duration_ms=actual_duration_ms,
        )
    return ImportVerificationDecision(
        accepted=True,
        reason_code="verified",
        detail=(
            "Imported audio is readable and its duration and persisted identity/version "
            "evidence match the selected transfer"
        ),
        actual_duration_ms=actual_duration_ms,
    )


def duration_is_compatible(expected_ms: int, actual_ms: int) -> bool:
    tolerance = max(
        MAX_DURATION_DELTA_MS, round(expected_ms * MAX_DURATION_DELTA_RATIO)
    )
    return abs(expected_ms - actual_ms) <= tolerance


def _identity_version_score(candidate: SoulseekCandidateRecord) -> float:
    return (
        float(candidate.identity_confidence or 0) * 0.85
        + float(candidate.version_confidence or 0) * 0.15
    )


def _candidate_is_hard_compatible(
    candidate: SoulseekCandidateRecord,
    *,
    expected_duration_ms: int | None,
) -> bool:
    if float(candidate.identity_confidence or 0) < MIN_IDENTITY_CONFIDENCE:
        return False
    if float(candidate.version_confidence or 0) < MIN_VERSION_CONFIDENCE:
        return False
    if expected_duration_ms is None or candidate.duration_seconds is None:
        return False
    if not duration_is_compatible(
        expected_duration_ms,
        candidate.duration_seconds * 1000,
    ):
        return False
    return candidate.size >= MIN_AUDIO_BYTES
