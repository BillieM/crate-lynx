from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy import insert

from app.links.store import final_links_table
from app.links.store import metadata as links_metadata
from app.matching import ConfidenceBand, MatchResult, MatchingPipeline
from app.matching.pipeline import (
    fetch_suggested_links,
    metadata as suggested_links_metadata,
    suggested_links_table,
)


@dataclass
class FakeMatcher:
    result: MatchResult | None
    calls: list[int]

    def match(self, local_track_id: int) -> MatchResult | None:
        self.calls.append(local_track_id)
        return self.result

    def candidates(
        self,
        local_track_id: int,
        *,
        excluded_streaming_track_ids: set[int] | frozenset[int] | None = None,
        limit: int = 10,
    ) -> list[MatchResult]:
        self.calls.append(local_track_id)
        if self.result is None:
            return []
        if (
            excluded_streaming_track_ids is not None
            and self.result.streaming_track_id in excluded_streaming_track_ids
        ):
            return []
        return [self.result][:limit]


@dataclass
class FakeCandidateMatcher:
    results: list[MatchResult]
    calls: list[int]
    seen_excluded_streaming_track_ids: set[int] | frozenset[int] | None = None
    seen_limit: int | None = None

    def candidates(
        self,
        local_track_id: int,
        *,
        excluded_streaming_track_ids: set[int] | frozenset[int] | None = None,
        limit: int = 10,
    ) -> list[MatchResult]:
        self.calls.append(local_track_id)
        self.seen_excluded_streaming_track_ids = excluded_streaming_track_ids
        self.seen_limit = limit
        excluded_ids = excluded_streaming_track_ids or frozenset()
        return [
            result
            for result in self.results
            if result.streaming_track_id not in excluded_ids
        ][:limit]


def test_matching_pipeline_persists_isrc_match_without_running_tag_matcher(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    isrc_matcher = FakeMatcher(
        result=MatchResult(
            local_track_id=17,
            streaming_track_id=51,
            match_method="isrc",
            score=1.0,
            confidence_band=ConfidenceBand.HIGH,
        ),
        calls=[],
    )
    tag_matcher = FakeMatcher(result=None, calls=[])

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=isrc_matcher,
        tag_matcher=tag_matcher,
    ).run(17)

    assert result is not None
    assert isrc_matcher.calls == [17]
    assert tag_matcher.calls == []
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 17,
            "streaming_track_id": 51,
            "match_method": "isrc",
            "score": 1.0,
            "status": "pending",
        }
    ]


def test_matching_pipeline_persists_medium_confidence_tag_match(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    tag_matcher = FakeMatcher(
        result=MatchResult(
            local_track_id=9,
            streaming_track_id=14,
            match_method="tags",
            score=0.75,
            confidence_band=ConfidenceBand.MEDIUM,
        ),
        calls=[],
    )

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        redis_url="redis://redis:6379/0",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=tag_matcher,
    ).run(9)

    assert result is not None
    assert tag_matcher.calls == [9]
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 9,
            "streaming_track_id": 14,
            "match_method": "tags",
            "score": 0.75,
            "status": "pending",
        }
    ]


def test_matching_pipeline_persists_low_confidence_tag_match_without_acoustic_job(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        redis_url="redis://redis:6379/0",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=FakeMatcher(
            result=MatchResult(
                local_track_id=22,
                streaming_track_id=31,
                match_method="tags",
                score=0.2,
                confidence_band=ConfidenceBand.LOW,
            ),
            calls=[],
        ),
    ).run(22)

    assert result is not None
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 22,
            "streaming_track_id": 31,
            "match_method": "tags",
            "score": 0.2,
            "status": "pending",
        }
    ]


def test_matching_pipeline_rerun_clears_existing_non_approved_suggestion(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "local_track_id": 33,
                    "streaming_track_id": 70,
                    "match_method": "tags",
                    "score": 0.4,
                    "status": "pending",
                },
                {
                    "local_track_id": 33,
                    "streaming_track_id": 71,
                    "match_method": "tags",
                    "score": 0.3,
                    "status": "rejected",
                },
                {
                    "local_track_id": 33,
                    "streaming_track_id": 72,
                    "match_method": "isrc",
                    "score": 1.0,
                    "status": "approved",
                },
            ],
        )

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=FakeMatcher(
            result=MatchResult(
                local_track_id=33,
                streaming_track_id=99,
                match_method="tags",
                score=0.9,
                confidence_band=ConfidenceBand.HIGH,
            ),
            calls=[],
        ),
    ).run(33)

    assert result is not None
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 33,
            "streaming_track_id": 71,
            "match_method": "tags",
            "score": 0.3,
            "status": "rejected",
        },
        {
            "local_track_id": 33,
            "streaming_track_id": 72,
            "match_method": "isrc",
            "score": 1.0,
            "status": "approved",
        },
        {
            "local_track_id": 33,
            "streaming_track_id": 99,
            "match_method": "tags",
            "score": 0.9,
            "status": "pending",
        },
    ]


def test_matching_pipeline_skips_rejected_isrc_pair_and_persists_tag_match(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'skip-rejected-isrc.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(suggested_links_table).values(
                local_track_id=52,
                streaming_track_id=91,
                match_method="manual_break",
                score=0.0,
                status="rejected",
            )
        )

    isrc_matcher = FakeMatcher(
        result=MatchResult(
            local_track_id=52,
            streaming_track_id=91,
            match_method="isrc",
            score=1.0,
            confidence_band=ConfidenceBand.HIGH,
        ),
        calls=[],
    )
    tag_matcher = FakeMatcher(
        result=MatchResult(
            local_track_id=52,
            streaming_track_id=92,
            match_method="tags",
            score=0.9,
            confidence_band=ConfidenceBand.HIGH,
        ),
        calls=[],
    )

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=isrc_matcher,
        tag_matcher=tag_matcher,
    ).run(52)

    assert result is not None
    assert result.streaming_track_id == 92
    assert isrc_matcher.calls == [52]
    assert tag_matcher.calls == [52]
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 52,
            "streaming_track_id": 91,
            "match_method": "manual_break",
            "score": 0.0,
            "status": "rejected",
        },
        {
            "local_track_id": 52,
            "streaming_track_id": 92,
            "match_method": "tags",
            "score": 0.9,
            "status": "pending",
        },
    ]


def test_matching_pipeline_does_not_recreate_rejected_tag_pair(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'skip-rejected-tag.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(suggested_links_table).values(
                local_track_id=61,
                streaming_track_id=101,
                match_method="manual_break",
                score=0.0,
                status="rejected",
            )
        )

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=FakeMatcher(
            result=MatchResult(
                local_track_id=61,
                streaming_track_id=101,
                match_method="tags",
                score=0.45,
                confidence_band=ConfidenceBand.LOW,
            ),
            calls=[],
        ),
    ).run(61)

    assert result is None
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 61,
            "streaming_track_id": 101,
            "match_method": "manual_break",
            "score": 0.0,
            "status": "rejected",
        }
    ]


def test_matching_pipeline_filters_rejected_pairs_before_tag_ranking(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'filter-rejected-tag.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(suggested_links_table).values(
                local_track_id=71,
                streaming_track_id=201,
                match_method="tags",
                score=0.95,
                status="rejected",
            )
        )

    tag_matcher = FakeCandidateMatcher(
        results=[
            MatchResult(
                local_track_id=71,
                streaming_track_id=201,
                match_method="tags",
                score=0.95,
                confidence_band=ConfidenceBand.HIGH,
            ),
            MatchResult(
                local_track_id=71,
                streaming_track_id=202,
                match_method="tags",
                score=0.91,
                confidence_band=ConfidenceBand.HIGH,
            ),
        ],
        calls=[],
    )

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=tag_matcher,
    ).run(71)

    assert result is not None
    assert result.streaming_track_id == 202
    assert tag_matcher.seen_excluded_streaming_track_ids == {201}
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 71,
            "streaming_track_id": 201,
            "match_method": "tags",
            "score": 0.95,
            "status": "rejected",
        },
        {
            "local_track_id": 71,
            "streaming_track_id": 202,
            "match_method": "tags",
            "score": 0.91,
            "status": "pending",
        },
    ]


def test_matching_pipeline_persists_ranked_tag_shortlist(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'tag-shortlist.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        redis_url="redis://redis:6379/0",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=FakeCandidateMatcher(
            results=[
                MatchResult(
                    local_track_id=81,
                    streaming_track_id=301,
                    match_method="tags",
                    score=0.49,
                    confidence_band=ConfidenceBand.LOW,
                ),
                MatchResult(
                    local_track_id=81,
                    streaming_track_id=302,
                    match_method="tags",
                    score=0.45,
                    confidence_band=ConfidenceBand.LOW,
                ),
            ],
            calls=[],
        ),
    ).run(81)

    assert result is not None
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 81,
            "streaming_track_id": 301,
            "match_method": "tags",
            "score": 0.49,
            "status": "pending",
        },
        {
            "local_track_id": 81,
            "streaming_track_id": 302,
            "match_method": "tags",
            "score": 0.45,
            "status": "pending",
        },
    ]


def test_matching_pipeline_persists_only_plausible_tag_candidates(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'plausible-tag-shortlist.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    tag_matcher = FakeCandidateMatcher(
        results=[
            MatchResult(
                local_track_id=82,
                streaming_track_id=401,
                match_method="tags",
                score=0.82,
                confidence_band=ConfidenceBand.MEDIUM,
            ),
            MatchResult(
                local_track_id=82,
                streaming_track_id=402,
                match_method="tags",
                score=0.51,
                confidence_band=ConfidenceBand.MEDIUM,
            ),
            MatchResult(
                local_track_id=82,
                streaming_track_id=403,
                match_method="tags",
                score=0.49,
                confidence_band=ConfidenceBand.LOW,
            ),
            MatchResult(
                local_track_id=82,
                streaming_track_id=404,
                match_method="tags",
                score=0.48,
                confidence_band=ConfidenceBand.LOW,
            ),
        ],
        calls=[],
    )

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=tag_matcher,
    ).run(82)

    assert result is not None
    assert result.streaming_track_id == 401
    assert tag_matcher.seen_limit == 3
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 82,
            "streaming_track_id": 401,
            "match_method": "tags",
            "score": 0.82,
            "status": "pending",
        },
        {
            "local_track_id": 82,
            "streaming_track_id": 402,
            "match_method": "tags",
            "score": 0.51,
            "status": "pending",
        },
    ]


def test_matching_pipeline_keeps_top_low_confidence_fallback_candidates(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fallback-tag-shortlist.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    result = MatchingPipeline(
        database_url=database_url,
        beets_library=tmp_path / "library.db",
        isrc_matcher=FakeMatcher(result=None, calls=[]),
        tag_matcher=FakeCandidateMatcher(
            results=[
                MatchResult(
                    local_track_id=83,
                    streaming_track_id=501,
                    match_method="tags",
                    score=0.49,
                    confidence_band=ConfidenceBand.LOW,
                ),
                MatchResult(
                    local_track_id=83,
                    streaming_track_id=502,
                    match_method="tags",
                    score=0.42,
                    confidence_band=ConfidenceBand.LOW,
                ),
                MatchResult(
                    local_track_id=83,
                    streaming_track_id=503,
                    match_method="tags",
                    score=0.31,
                    confidence_band=ConfidenceBand.LOW,
                ),
            ],
            calls=[],
        ),
    ).run(83)

    assert result is not None
    assert result.streaming_track_id == 501
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 83,
            "streaming_track_id": 501,
            "match_method": "tags",
            "score": 0.49,
            "status": "pending",
        },
        {
            "local_track_id": 83,
            "streaming_track_id": 502,
            "match_method": "tags",
            "score": 0.42,
            "status": "pending",
        },
    ]


def test_suggested_link_store_clear_non_approved_for_track(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'clear-suggestions.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "local_track_id": 44,
                    "streaming_track_id": 80,
                    "match_method": "tags",
                    "score": 0.4,
                    "status": "pending",
                },
                {
                    "local_track_id": 44,
                    "streaming_track_id": 81,
                    "match_method": "tags",
                    "score": 0.3,
                    "status": "rejected",
                },
                {
                    "local_track_id": 44,
                    "streaming_track_id": 82,
                    "match_method": "isrc",
                    "score": 1.0,
                    "status": "approved",
                },
                {
                    "local_track_id": 45,
                    "streaming_track_id": 83,
                    "match_method": "tags",
                    "score": 0.9,
                    "status": "pending",
                },
            ],
        )

    from app.matching.pipeline import SuggestedLinkStore

    SuggestedLinkStore(database_url).clear_non_approved_for_track(44)

    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 44,
            "streaming_track_id": 81,
            "match_method": "tags",
            "score": 0.3,
            "status": "rejected",
        },
        {
            "local_track_id": 44,
            "streaming_track_id": 82,
            "match_method": "isrc",
            "score": 1.0,
            "status": "approved",
        },
        {
            "local_track_id": 45,
            "streaming_track_id": 83,
            "match_method": "tags",
            "score": 0.9,
            "status": "pending",
        },
    ]


def test_suggested_link_store_deletes_pending_for_linked_tracks(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'linked-suggestions.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(final_links_table),
            [
                {
                    "local_track_id": 44,
                    "streaming_track_id": 82,
                },
                {
                    "local_track_id": 46,
                    "streaming_track_id": 84,
                },
            ],
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "local_track_id": 44,
                    "streaming_track_id": 80,
                    "match_method": "tags",
                    "score": 0.4,
                    "status": "pending",
                },
                {
                    "local_track_id": 44,
                    "streaming_track_id": 81,
                    "match_method": "tags",
                    "score": 0.3,
                    "status": "rejected",
                },
                {
                    "local_track_id": 46,
                    "streaming_track_id": 84,
                    "match_method": "isrc",
                    "score": 1.0,
                    "status": "approved",
                },
                {
                    "local_track_id": 45,
                    "streaming_track_id": 83,
                    "match_method": "tags",
                    "score": 0.9,
                    "status": "pending",
                },
            ],
        )

    from app.matching.pipeline import SuggestedLinkStore

    deleted_count = SuggestedLinkStore(database_url).delete_pending_for_linked_tracks()

    assert deleted_count == 1
    assert fetch_suggested_links(database_url) == [
        {
            "local_track_id": 44,
            "streaming_track_id": 81,
            "match_method": "tags",
            "score": 0.3,
            "status": "rejected",
        },
        {
            "local_track_id": 46,
            "streaming_track_id": 84,
            "match_method": "isrc",
            "score": 1.0,
            "status": "approved",
        },
        {
            "local_track_id": 45,
            "streaming_track_id": 83,
            "match_method": "tags",
            "score": 0.9,
            "status": "pending",
        },
    ]
