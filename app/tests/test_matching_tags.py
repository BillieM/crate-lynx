from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.ingestion.beets_mirror import metadata as beets_mirror_metadata
from app.local_tracks.store import metadata as local_metadata
from app.matching import ConfidenceBand, TagMatcher
from app.streaming.models import metadata as streaming_metadata
from tests.factories import TestDataFactory


def _setup_matcher_database(tmp_path: Path) -> tuple[str, TestDataFactory]:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)
    beets_mirror_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    return database_url, TestDataFactory(engine)


def test_tag_matcher_returns_best_high_confidence_match(tmp_path: Path) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=42)
    test_data.beets_item(
        beets_id=42,
        title=" Track ",
        artist="ARTIST",
        album="Album",
    )
    matching_streaming_id = test_data.streaming_track(
        album="Album",
        artist="Artist",
        duration_ms=180000,
        isrc=None,
        provider_track_id="yt-1",
        title="Track",
        year=2024,
    )
    test_data.streaming_track(
        album="Elsewhere",
        artist="Another Artist",
        duration_ms=180000,
        isrc=None,
        provider_track_id="yt-2",
        title="Different Song",
        year=2024,
    )

    result = TagMatcher(database_url=database_url).match(local_track_id)

    assert result is not None
    assert result.local_track_id == local_track_id
    assert result.streaming_track_id == matching_streaming_id
    assert result.match_method == "tags"
    assert result.score == pytest.approx(0.98)
    assert result.confidence_band is ConfidenceBand.HIGH


def test_tag_matcher_returns_medium_confidence_when_score_hits_threshold(
    tmp_path: Path,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=7)
    test_data.beets_item(beets_id=7, title="Aaab", artist="Bbbc", album=None)
    streaming_id = test_data.streaming_track(
        album=None,
        artist="Bbbb",
        duration_ms=180000,
        isrc=None,
        provider_track_id="yt-1",
        title="Aaaa",
        year=2024,
    )

    result = TagMatcher(database_url=database_url).match(local_track_id)

    assert result is not None
    assert result.streaming_track_id == streaming_id
    assert result.score == pytest.approx(0.705)
    assert result.confidence_band is ConfidenceBand.MEDIUM


def test_tag_matcher_returns_low_confidence_when_score_is_below_threshold(
    tmp_path: Path,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=9)
    test_data.beets_item(beets_id=9, title="Aaab", artist="Bbbc", album=None)
    streaming_id = test_data.streaming_track(
        album=None,
        artist="Mismatch",
        duration_ms=180000,
        isrc=None,
        provider_track_id="yt-1",
        title="Nope",
        year=2024,
    )

    result = TagMatcher(database_url=database_url).match(local_track_id)

    assert result is not None
    assert result.streaming_track_id == streaming_id
    assert result.score < 0.5
    assert result.confidence_band is ConfidenceBand.LOW


def test_tag_matcher_candidates_rank_noisy_title_identity_above_false_positive(
    tmp_path: Path,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(
        beets_id=9,
        file_path="Mind Against, TSHA, NIMMO/OnlyL.mp3",
    )
    test_data.beets_item(
        beets_id=9,
        title="OnlyL ft. TSHA & NIMMO (Original Mix)",
        artist="Mind Against, TSHA, NIMMO",
        album="djsoundtop.com",
    )
    matching_streaming_id = test_data.streaming_track(
        album="Capricorn Sun",
        artist="TSHA",
        duration_ms=180000,
        isrc=None,
        provider_track_id="ldvmHCyXM0M",
        title="OnlyL (feat. NIMMO)",
        year=2021,
    )
    false_positive_id = test_data.streaming_track(
        album="L'Amour Toujour (Maxi)",
        artist="Gigi D'Agostino",
        duration_ms=180000,
        isrc=None,
        provider_track_id="SA0-V9FJKno",
        title="L'amour Toujours(Small Mix)",
        year=1999,
    )

    candidates = TagMatcher(database_url=database_url).candidates(
        local_track_id,
        limit=2,
    )

    assert [candidate.streaming_track_id for candidate in candidates] == [
        matching_streaming_id,
        false_positive_id,
    ]
    assert candidates[0].score > candidates[1].score


def test_tag_matcher_uses_album_and_duration_only_as_positive_bonuses(
    tmp_path: Path,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=9)
    test_data.beets_item(
        beets_id=9,
        title="Track",
        artist="Artist",
        album="Album",
        length=180.0,
    )
    matching_streaming_id = test_data.streaming_track(
        album="Album",
        artist="Artist",
        duration_ms=183000,
        isrc=None,
        provider_track_id="yt-1",
        title="Track",
        year=2024,
    )
    weaker_streaming_id = test_data.streaming_track(
        album="Different Album",
        artist="Artist",
        duration_ms=260000,
        isrc=None,
        provider_track_id="yt-2",
        title="Track",
        year=2024,
    )

    candidates = TagMatcher(database_url=database_url).candidates(
        local_track_id,
        limit=2,
    )

    assert [candidate.streaming_track_id for candidate in candidates] == [
        matching_streaming_id,
        weaker_streaming_id,
    ]
    assert candidates[0].score == 1.0
    assert candidates[1].score > 0.95
    assert candidates[0].score > candidates[1].score


def test_tag_matcher_returns_none_when_beets_item_has_no_title_or_artist(
    tmp_path: Path,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=11)
    test_data.beets_item(beets_id=11, title=None, artist="Artist", album="Album")

    result = TagMatcher(database_url=database_url).match(local_track_id)

    assert result is None
