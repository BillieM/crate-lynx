import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, insert

from app.links.router import create_router
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.matching.models import ConfidenceBand
from app.matching.pipeline import (
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
