from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine

from app.matching import ConfidenceBand, IsrcMatcher

if TYPE_CHECKING:
    from tests.factories import TestDataFactory


def test_isrc_matcher_returns_high_confidence_match(
    migrated_database: tuple[str, Engine],
    test_data: TestDataFactory,
) -> None:
    database_url, _ = migrated_database
    local_track_id = test_data.local_track(beets_id=42)
    test_data.beets_item(beets_id=42, isrc=" GBUM72105976 ")
    streaming_track_id = test_data.streaming_track(
        provider_track_id="yt-1",
        title="Track",
        artist="Artist",
        album="Album",
        year=2024,
        isrc="gbum72105976",
        duration_ms=180000,
    )

    result = IsrcMatcher(database_url=database_url).match(local_track_id)

    assert result is not None
    assert result.local_track_id == local_track_id
    assert result.streaming_track_id == streaming_track_id
    assert result.match_method == "isrc"
    assert result.score == 1.0
    assert result.confidence_band is ConfidenceBand.HIGH


def test_isrc_matcher_returns_none_when_beets_item_has_no_isrc(
    migrated_database: tuple[str, Engine],
    test_data: TestDataFactory,
) -> None:
    database_url, _ = migrated_database
    local_track_id = test_data.local_track(beets_id=7)
    test_data.beets_item(beets_id=7, isrc=None)

    result = IsrcMatcher(database_url=database_url).match(local_track_id)

    assert result is None


def test_isrc_matcher_returns_none_when_beets_item_is_missing(
    migrated_database: tuple[str, Engine],
    test_data: TestDataFactory,
) -> None:
    database_url, _ = migrated_database
    local_track_id = test_data.local_track(beets_id=8)

    result = IsrcMatcher(database_url=database_url).match(local_track_id)

    assert result is None


def test_isrc_matcher_returns_none_when_streaming_track_is_missing(
    migrated_database: tuple[str, Engine],
    test_data: TestDataFactory,
) -> None:
    database_url, _ = migrated_database
    local_track_id = test_data.local_track(beets_id=9)
    test_data.beets_item(beets_id=9, isrc="USQX92200001")

    result = IsrcMatcher(database_url=database_url).match(local_track_id)

    assert result is None
