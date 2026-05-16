from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.engine import Engine

from app.matching import ConfidenceBand, IsrcMatcher
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_OFF,
)

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
    _add_playlist_membership(test_data, streaming_track_id)

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


@pytest.mark.parametrize(
    ("sync_modes", "expected_match"),
    [
        pytest.param([PLAYLIST_SYNC_MODE_OFF], False, id="off-only"),
        pytest.param([PLAYLIST_SYNC_MODE_MATCH_ONLY], True, id="match-only"),
        pytest.param([PLAYLIST_SYNC_MODE_FULL], True, id="full"),
        pytest.param(
            [PLAYLIST_SYNC_MODE_OFF, PLAYLIST_SYNC_MODE_MATCH_ONLY],
            True,
            id="mixed-active",
        ),
    ],
)
def test_isrc_matcher_scopes_candidates_to_active_playlist_modes(
    migrated_database: tuple[str, Engine],
    test_data: TestDataFactory,
    sync_modes: list[str],
    expected_match: bool,
) -> None:
    database_url, _ = migrated_database
    local_track_id = test_data.local_track(beets_id=10)
    test_data.beets_item(beets_id=10, isrc="USQX92200001")
    streaming_track_id = test_data.streaming_track(
        provider_track_id="yt-scope",
        title="Track",
        artist="Artist",
        album="Album",
        year=2024,
        isrc="USQX92200001",
        duration_ms=180000,
    )
    for index, sync_mode in enumerate(sync_modes, start=1):
        _add_playlist_membership(
            test_data,
            streaming_track_id,
            provider_playlist_id=f"PL-SCOPE-{index}",
            sync_mode=sync_mode,
        )

    result = IsrcMatcher(database_url=database_url).match(local_track_id)

    if expected_match:
        assert result is not None
        assert result.streaming_track_id == streaming_track_id
    else:
        assert result is None


def _add_playlist_membership(
    test_data: TestDataFactory,
    streaming_track_id: int,
    *,
    provider_playlist_id: str = "PL1",
    sync_mode: str = PLAYLIST_SYNC_MODE_FULL,
) -> None:
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id=provider_playlist_id,
        sync_mode=sync_mode,
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        streaming_track_id=streaming_track_id,
    )
