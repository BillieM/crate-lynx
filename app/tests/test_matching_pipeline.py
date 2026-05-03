from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy import insert

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


def test_matching_pipeline_persists_medium_confidence_tag_match(tmp_path) -> None:
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


def test_matching_pipeline_enqueues_acoustic_job_for_low_confidence_tag_match(
    monkeypatch,
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    suggested_links_metadata.create_all(engine)

    seen: dict[str, object] = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def enqueue(
            self,
            func: str,
            local_track_id: int,
            candidates: list[dict[str, object]],
            *,
            job_timeout: str,
        ) -> SimpleNamespace:
            seen["func"] = func
            seen["local_track_id"] = local_track_id
            seen["candidates"] = candidates
            seen["job_timeout"] = job_timeout
            return SimpleNamespace(id="acoustic-job-1")

    monkeypatch.setattr("app.matching.pipeline.Redis", FakeRedis)
    monkeypatch.setattr("app.matching.pipeline.Queue", FakeQueue)

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
    assert seen == {
        "redis_url": "redis://redis:6379/0",
        "queue_name": "matching",
        "connection": seen["connection"],
        "func": "app.matching.run_acoustic_match_job",
        "local_track_id": 22,
        "candidates": [
            {
                "streaming_track_id": 31,
                "fingerprint": "",
            }
        ],
        "job_timeout": "10m",
    }


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
                score=0.82,
                confidence_band=ConfidenceBand.MEDIUM,
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
            "score": 0.82,
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
            score=0.8,
            confidence_band=ConfidenceBand.MEDIUM,
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
            "score": 0.8,
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
