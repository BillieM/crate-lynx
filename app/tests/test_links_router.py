import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, insert, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.links.router import create_router
from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.matching.models import ConfidenceBand
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_REJECTED,
    metadata as suggested_links_metadata,
    suggested_links_table,
)
from app.streaming.models import metadata as streaming_metadata
from app.streaming.models import streaming_tracks_table


def test_list_proposals_returns_joined_records(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'proposals.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)

    rejected_at = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="ABC123456789",
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(suggested_links_table).values(
                id=13,
                local_track_id=4,
                streaming_track_id=9,
                match_method="tags",
                score=0.82,
                status="rejected",
                rejected_at=rejected_at,
            )
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals"
        and "GET" in getattr(route, "methods", set())
    )
    response = asyncio.run(route.endpoint())

    assert response.model_dump(mode="json") == {
        "proposals": [
            {
                "id": 13,
                "local_track_id": 4,
                "local_file_path": "Artist/Track.mp3",
                "streaming_track_id": 9,
                "streaming_title": "Track",
                "streaming_artist": "Artist",
                "streaming_album": "Album",
                "match_method": "tags",
                "score": 0.82,
                "status": "rejected",
                "confidence_band": "medium",
                "rejected_at": "2026-05-03T12:00:00",
            }
        ]
    }


def test_list_proposals_filters_by_confidence_band(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'proposal-filter.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table),
            [
                {
                    "id": 1,
                    "file_path": "Artist/high.mp3",
                    "library_root_rel_path": "Artist/high.mp3",
                    "fingerprint": "fp-1",
                    "beets_id": 1,
                },
                {
                    "id": 2,
                    "file_path": "Artist/medium.mp3",
                    "library_root_rel_path": "Artist/medium.mp3",
                    "fingerprint": "fp-2",
                    "beets_id": 2,
                },
                {
                    "id": 3,
                    "file_path": "Artist/low.mp3",
                    "library_root_rel_path": "Artist/low.mp3",
                    "fingerprint": "fp-3",
                    "beets_id": 3,
                },
            ],
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "High",
                    "artist": "Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": None,
                },
                {
                    "id": 12,
                    "provider_track_id": "ytm-12",
                    "title": "Medium",
                    "artist": "Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": None,
                },
                {
                    "id": 13,
                    "provider_track_id": "ytm-13",
                    "title": "Low",
                    "artist": "Artist",
                    "album": None,
                    "year": None,
                    "isrc": None,
                    "duration_ms": None,
                },
            ],
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "id": 21,
                    "local_track_id": 1,
                    "streaming_track_id": 11,
                    "match_method": "isrc",
                    "score": 0.99,
                    "status": "pending",
                },
                {
                    "id": 22,
                    "local_track_id": 2,
                    "streaming_track_id": 12,
                    "match_method": "tags",
                    "score": 0.85,
                    "status": "pending",
                },
                {
                    "id": 23,
                    "local_track_id": 3,
                    "streaming_track_id": 13,
                    "match_method": "tags",
                    "score": 0.49,
                    "status": "pending",
                },
            ],
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals"
        and "GET" in getattr(route, "methods", set())
    )

    high_response = asyncio.run(route.endpoint(ConfidenceBand.HIGH))
    medium_response = asyncio.run(route.endpoint(ConfidenceBand.MEDIUM))
    low_response = asyncio.run(route.endpoint(ConfidenceBand.LOW))

    assert [proposal.id for proposal in high_response.proposals] == [21]
    assert [proposal.id for proposal in medium_response.proposals] == [22]
    assert [proposal.id for proposal in low_response.proposals] == [23]


def test_approve_proposal_writes_final_link_and_marks_suggestion_approved(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'approve-proposal.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/approved.mp3",
                library_root_rel_path="Artist/approved.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Approved Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="ABC123456789",
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(suggested_links_table).values(
                id=13,
                local_track_id=4,
                streaming_track_id=9,
                match_method="tags",
                score=0.82,
                status="pending",
            )
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/approve"
        and "POST" in getattr(route, "methods", set())
    )

    response = asyncio.run(route.endpoint(13))

    assert response == {
        "proposal_id": 13,
        "final_link_id": 1,
        "status": "approved",
    }

    with engine.connect() as connection:
        final_link = connection.execute(select(final_links_table)).mappings().one()
        suggestion = (
            connection.execute(
                select(suggested_links_table).where(suggested_links_table.c.id == 13)
            )
            .mappings()
            .one()
        )

    assert final_link["local_track_id"] == 4
    assert final_link["streaming_track_id"] == 9
    assert final_link["approved_at"] is not None
    assert suggestion["status"] == SUGGESTED_LINK_STATUS_APPROVED


def test_approve_proposal_returns_404_when_missing(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'approve-proposal-missing.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/approve"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(route.endpoint(999))
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Proposal not found"
    else:
        raise AssertionError(
            "Expected approve endpoint to raise 404 for missing proposal"
        )


def test_reject_proposal_marks_suggestion_rejected(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'reject-proposal.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/rejected.mp3",
                library_root_rel_path="Artist/rejected.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Rejected Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="ABC123456789",
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(suggested_links_table).values(
                id=13,
                local_track_id=4,
                streaming_track_id=9,
                match_method="tags",
                score=0.82,
                status="pending",
            )
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/reject"
        and "POST" in getattr(route, "methods", set())
    )

    response = asyncio.run(route.endpoint(13))

    assert response["proposal_id"] == 13
    assert response["status"] == SUGGESTED_LINK_STATUS_REJECTED
    assert response["rejected_at"] is not None

    with engine.connect() as connection:
        suggestion = (
            connection.execute(
                select(suggested_links_table).where(suggested_links_table.c.id == 13)
            )
            .mappings()
            .one()
        )

    assert suggestion["status"] == SUGGESTED_LINK_STATUS_REJECTED
    assert suggestion["rejected_at"] is not None


def test_reject_proposal_returns_404_when_missing(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'reject-proposal-missing.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/reject"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        asyncio.run(route.endpoint(999))
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Proposal not found"
    else:
        raise AssertionError(
            "Expected reject endpoint to raise 404 for missing proposal"
        )
