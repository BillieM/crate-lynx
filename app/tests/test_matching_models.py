from app.matching import ConfidenceBand, MatchResult


def test_confidence_band_from_score_uses_thresholds() -> None:
    assert ConfidenceBand.from_score(0.9) is ConfidenceBand.HIGH
    assert ConfidenceBand.from_score(0.85) is ConfidenceBand.MEDIUM
    assert ConfidenceBand.from_score(0.5) is ConfidenceBand.MEDIUM
    assert ConfidenceBand.from_score(0.49) is ConfidenceBand.LOW


def test_match_result_stores_matching_fields() -> None:
    result = MatchResult(
        local_track_id=7,
        streaming_track_id=11,
        match_method="isrc",
        score=1.0,
        confidence_band=ConfidenceBand.HIGH,
    )

    assert result.local_track_id == 7
    assert result.streaming_track_id == 11
    assert result.match_method == "isrc"
    assert result.score == 1.0
    assert result.confidence_band is ConfidenceBand.HIGH
