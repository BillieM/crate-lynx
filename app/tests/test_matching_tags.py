from pathlib import Path

import pytest
from sqlalchemy import create_engine

import app.matching.tags as tags_module
from app.ingestion.beets_mirror import metadata as beets_mirror_metadata
from app.local_tracks.store import metadata as local_metadata
from app.matching import ConfidenceBand, TagMatcher
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_OFF,
    metadata as streaming_metadata,
)
from tests.factories import TestDataFactory


def _setup_matcher_database(tmp_path: Path) -> tuple[str, TestDataFactory]:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)
    beets_mirror_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    return database_url, TestDataFactory(engine)


def _playlist(
    test_data: TestDataFactory,
    *,
    provider_playlist_id: str = "PL1",
    sync_mode: str = PLAYLIST_SYNC_MODE_FULL,
) -> int:
    account_id = test_data.streaming_account()
    return test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id=provider_playlist_id,
        sync_mode=sync_mode,
    )


def _add_playlist_membership(
    test_data: TestDataFactory,
    *,
    playlist_id: int,
    streaming_track_id: int,
) -> None:
    test_data.playlist_membership(
        playlist_id=playlist_id,
        streaming_track_id=streaming_track_id,
    )


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
    weaker_streaming_id = test_data.streaming_track(
        album="Elsewhere",
        artist="Another Artist",
        duration_ms=180000,
        isrc=None,
        provider_track_id="yt-2",
        title="Different Song",
        year=2024,
    )
    playlist_id = _playlist(test_data)
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=matching_streaming_id,
    )
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=weaker_streaming_id,
    )

    result = TagMatcher(database_url=database_url).match(local_track_id)

    assert result is not None
    assert result.local_track_id == local_track_id
    assert result.streaming_track_id == matching_streaming_id
    assert result.match_method == "tags"
    assert result.score == pytest.approx(0.98)
    assert result.confidence_band is ConfidenceBand.HIGH


def test_tag_matcher_prefilters_streaming_tracks_before_scoring(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=42)
    test_data.beets_item(beets_id=42, title="Needle", artist="Artist", album=None)
    playlist_id = _playlist(test_data)
    for index in range(150):
        streaming_track_id = test_data.streaming_track(
            album=None,
            artist="Artist",
            duration_ms=180000,
            isrc=None,
            provider_track_id=f"filler-{index}",
            title=f"Haystack {index}",
            year=2024,
        )
        _add_playlist_membership(
            test_data,
            playlist_id=playlist_id,
            streaming_track_id=streaming_track_id,
        )
    matching_streaming_id = test_data.streaming_track(
        album=None,
        artist="Artist",
        duration_ms=180000,
        isrc=None,
        provider_track_id="needle",
        title="Needle",
        year=2024,
    )
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=matching_streaming_id,
    )
    scored_titles: list[str] = []
    score_tags = tags_module._score_tags

    def spy_score_tags(**kwargs: object) -> float:
        scored_titles.append(str(kwargs["streaming_title"]))
        return score_tags(**kwargs)

    monkeypatch.setattr(tags_module, "_score_tags", spy_score_tags)

    candidates = TagMatcher(database_url=database_url).candidates(
        local_track_id,
        limit=1,
    )

    assert [candidate.streaming_track_id for candidate in candidates] == [
        matching_streaming_id,
    ]
    assert scored_titles == ["needle"]


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
    _add_playlist_membership(
        test_data,
        playlist_id=_playlist(test_data),
        streaming_track_id=streaming_id,
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
    _add_playlist_membership(
        test_data,
        playlist_id=_playlist(test_data),
        streaming_track_id=streaming_id,
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
    playlist_id = _playlist(test_data)
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=matching_streaming_id,
    )
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=false_positive_id,
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
    playlist_id = _playlist(test_data)
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=matching_streaming_id,
    )
    _add_playlist_membership(
        test_data,
        playlist_id=playlist_id,
        streaming_track_id=weaker_streaming_id,
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


@pytest.mark.parametrize(
    ("sync_modes", "expected_match"),
    [
        pytest.param([PLAYLIST_SYNC_MODE_OFF], False, id="off-only"),
        pytest.param([PLAYLIST_SYNC_MODE_MATCH_ONLY], True, id="match-only"),
        pytest.param([PLAYLIST_SYNC_MODE_FULL], True, id="full"),
        pytest.param(
            [PLAYLIST_SYNC_MODE_OFF, PLAYLIST_SYNC_MODE_FULL],
            True,
            id="mixed-active",
        ),
    ],
)
def test_tag_matcher_scopes_candidates_to_active_playlist_modes(
    tmp_path: Path,
    sync_modes: list[str],
    expected_match: bool,
) -> None:
    database_url, test_data = _setup_matcher_database(tmp_path)
    local_track_id = test_data.local_track(beets_id=12)
    test_data.beets_item(
        beets_id=12,
        title="Track",
        artist="Artist",
        album="Album",
    )
    streaming_track_id = test_data.streaming_track(
        album="Album",
        artist="Artist",
        duration_ms=180000,
        isrc=None,
        provider_track_id="yt-scope",
        title="Track",
        year=2024,
    )
    for index, sync_mode in enumerate(sync_modes, start=1):
        playlist_id = _playlist(
            test_data,
            provider_playlist_id=f"PL-SCOPE-{index}",
            sync_mode=sync_mode,
        )
        _add_playlist_membership(
            test_data,
            playlist_id=playlist_id,
            streaming_track_id=streaming_track_id,
        )

    result = TagMatcher(database_url=database_url).match(local_track_id)

    if expected_match:
        assert result is not None
        assert result.streaming_track_id == streaming_track_id
    else:
        assert result is None
