import asyncio
import inspect
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
    SUGGESTED_LINK_STATUS_PENDING,
    SUGGESTED_LINK_STATUS_REJECTED,
    metadata as suggested_links_metadata,
    suggested_links_table,
)
from app.streaming.models import metadata as streaming_metadata
from app.streaming.models import (
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)


def _call_endpoint(endpoint, *args):
    result = endpoint(*args)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def test_list_proposals_returns_joined_pending_records(
    migrated_database,
    test_data,
) -> None:
    database_url, _ = migrated_database
    rejected_at = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)
    pending_local_id = test_data.local_track(
        beets_id=4,
        file_path="Artist/Track.mp3",
        fingerprint="fp-4",
    )
    rejected_local_id = test_data.local_track(
        beets_id=5,
        file_path="Artist/Rejected.mp3",
        fingerprint="fp-5",
    )
    pending_streaming_id = test_data.streaming_track(
        album="Album",
        artist="Artist",
        duration_ms=123000,
        isrc="ABC123456789",
        provider_track_id="ytm-9",
        title="Track",
        year=2024,
    )
    rejected_streaming_id = test_data.streaming_track(
        album="Album",
        artist="Artist",
        duration_ms=124000,
        isrc="DEF123456789",
        provider_track_id="ytm-10",
        title="Rejected",
        year=2024,
    )
    proposal_id = test_data.suggested_link(
        local_track_id=pending_local_id,
        match_method="tags",
        score=0.82,
        status=SUGGESTED_LINK_STATUS_PENDING,
        streaming_track_id=pending_streaming_id,
    )
    test_data.suggested_link(
        local_track_id=rejected_local_id,
        match_method="tags",
        rejected_at=rejected_at,
        score=0.72,
        status=SUGGESTED_LINK_STATUS_REJECTED,
        streaming_track_id=rejected_streaming_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals"
        and "GET" in getattr(route, "methods", set())
    )
    response = _call_endpoint(route.endpoint)

    assert response.model_dump(mode="json") == {
        "proposals": [
            {
                "id": proposal_id,
                "local_track_id": pending_local_id,
                "local_file_path": "Artist/Track.mp3",
                "streaming_track_id": pending_streaming_id,
                "streaming_title": "Track",
                "streaming_artist": "Artist",
                "streaming_album": "Album",
                "match_method": "tags",
                "score": 0.82,
                "status": "pending",
                "confidence_band": "medium",
                "rejected_at": None,
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

    high_response = _call_endpoint(route.endpoint, ConfidenceBand.HIGH)
    medium_response = _call_endpoint(route.endpoint, ConfidenceBand.MEDIUM)
    low_response = _call_endpoint(route.endpoint, ConfidenceBand.LOW)

    assert [proposal.id for proposal in high_response.proposals] == [21]
    assert [proposal.id for proposal in medium_response.proposals] == [22]
    assert [proposal.id for proposal in low_response.proposals] == [23]


def test_approve_proposal_writes_final_link_and_clears_pending_siblings(
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
                [
                    {
                        "id": 4,
                        "file_path": "Artist/approved.mp3",
                        "library_root_rel_path": "Artist/approved.mp3",
                        "fingerprint": "fp-4",
                        "beets_id": 4,
                    },
                    {
                        "id": 5,
                        "file_path": "Artist/other.mp3",
                        "library_root_rel_path": "Artist/other.mp3",
                        "fingerprint": "fp-5",
                        "beets_id": 5,
                    },
                ]
            )
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 9,
                    "provider_track_id": "ytm-9",
                    "title": "Approved Track",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "ABC123456789",
                    "duration_ms": 123000,
                },
                {
                    "id": 10,
                    "provider_track_id": "ytm-10",
                    "title": "Pending Sibling",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "DEF123456789",
                    "duration_ms": 123000,
                },
                {
                    "id": 11,
                    "provider_track_id": "ytm-11",
                    "title": "Rejected Sibling",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "GHI123456789",
                    "duration_ms": 123000,
                },
                {
                    "id": 12,
                    "provider_track_id": "ytm-12",
                    "title": "Other Track",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "JKL123456789",
                    "duration_ms": 123000,
                },
            ],
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "id": 13,
                    "local_track_id": 4,
                    "streaming_track_id": 9,
                    "match_method": "tags",
                    "score": 0.82,
                    "status": "pending",
                },
                {
                    "id": 14,
                    "local_track_id": 4,
                    "streaming_track_id": 10,
                    "match_method": "tags",
                    "score": 0.76,
                    "status": "pending",
                },
                {
                    "id": 15,
                    "local_track_id": 4,
                    "streaming_track_id": 11,
                    "match_method": "manual_break",
                    "score": 0.0,
                    "status": "rejected",
                },
                {
                    "id": 16,
                    "local_track_id": 5,
                    "streaming_track_id": 12,
                    "match_method": "tags",
                    "score": 0.74,
                    "status": "pending",
                },
            ],
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/approve"
        and "POST" in getattr(route, "methods", set())
    )

    response = _call_endpoint(route.endpoint, 13)

    assert response == {
        "proposal_id": 13,
        "final_link_id": 1,
        "status": "approved",
    }

    with engine.connect() as connection:
        final_link = connection.execute(select(final_links_table)).mappings().one()
        suggestions = (
            connection.execute(
                select(
                    suggested_links_table.c.id,
                    suggested_links_table.c.local_track_id,
                    suggested_links_table.c.streaming_track_id,
                    suggested_links_table.c.status,
                ).order_by(suggested_links_table.c.id.asc())
            )
            .mappings()
            .all()
        )

    assert final_link["local_track_id"] == 4
    assert final_link["streaming_track_id"] == 9
    assert final_link["approved_at"] is not None
    assert [dict(suggestion) for suggestion in suggestions] == [
        {
            "id": 13,
            "local_track_id": 4,
            "streaming_track_id": 9,
            "status": SUGGESTED_LINK_STATUS_APPROVED,
        },
        {
            "id": 15,
            "local_track_id": 4,
            "streaming_track_id": 11,
            "status": SUGGESTED_LINK_STATUS_REJECTED,
        },
        {
            "id": 16,
            "local_track_id": 5,
            "streaming_track_id": 12,
            "status": SUGGESTED_LINK_STATUS_PENDING,
        },
    ]


def test_approve_proposal_regenerates_playlist_m3u(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'approve-proposal-regenerates-m3u.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIBRARY_ROOT", str(tmp_path / "library"))
    monkeypatch.setenv("M3U_OUTPUT_DIR", str(tmp_path / "m3u"))

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
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=9,
                position=1,
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

    _call_endpoint(route.endpoint, 13)

    assert (tmp_path / "m3u" / "Road-Trip-Mix.m3u").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "#EXTM3U",
        "#EXTINF:123,Artist - Approved Track",
        str((tmp_path / "library" / "Artist/approved.mp3").resolve()),
    ]


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
        _call_endpoint(route.endpoint, 999)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Proposal not found"
    else:
        raise AssertionError(
            "Expected approve endpoint to raise 404 for missing proposal"
        )


def test_approve_proposal_returns_409_for_rejected_pair(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'approve-proposal-rejected-pair.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/rejected-pair.mp3",
                library_root_rel_path="Artist/rejected-pair.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Rejected Pair Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="ABC123456789",
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "id": 12,
                    "local_track_id": 4,
                    "streaming_track_id": 9,
                    "match_method": "manual_break",
                    "score": 0.0,
                    "status": "rejected",
                },
                {
                    "id": 13,
                    "local_track_id": 4,
                    "streaming_track_id": 9,
                    "match_method": "tags",
                    "score": 0.82,
                    "status": "pending",
                },
            ],
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/proposals/{proposal_id}/approve"
        and "POST" in getattr(route, "methods", set())
    )

    try:
        _call_endpoint(route.endpoint, 13)
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "Rejected pair cannot be approved"
    else:
        raise AssertionError("Expected approve endpoint to raise 409 for rejected pair")

    with engine.connect() as connection:
        final_links = connection.execute(select(final_links_table)).mappings().all()
        pending_suggestion = (
            connection.execute(
                select(suggested_links_table).where(suggested_links_table.c.id == 13)
            )
            .mappings()
            .one()
        )

    assert final_links == []
    assert pending_suggestion["status"] == "pending"


def test_approve_proposal_returns_409_when_track_already_has_final_link(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'approve-proposal-duplicate-final-link.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/already-approved.mp3",
                library_root_rel_path="Artist/already-approved.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table),
            [
                {
                    "id": 9,
                    "provider_track_id": "ytm-9",
                    "title": "Approved Track",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "ABC123456789",
                    "duration_ms": 123000,
                },
                {
                    "id": 10,
                    "provider_track_id": "ytm-10",
                    "title": "Second Candidate",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "XYZ123456789",
                    "duration_ms": 123000,
                },
            ],
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=4,
                streaming_track_id=9,
            )
        )
        connection.execute(
            insert(suggested_links_table).values(
                id=13,
                local_track_id=4,
                streaming_track_id=10,
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

    try:
        _call_endpoint(route.endpoint, 13)
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "Track already has an approved link"
    else:
        raise AssertionError(
            "Expected approve endpoint to raise 409 when final link exists"
        )

    with engine.connect() as connection:
        final_links = (
            connection.execute(
                select(final_links_table).order_by(final_links_table.c.id.asc())
            )
            .mappings()
            .all()
        )
        pending_suggestion = (
            connection.execute(
                select(suggested_links_table).where(suggested_links_table.c.id == 13)
            )
            .mappings()
            .one()
        )

    assert len(final_links) == 1
    assert final_links[0]["local_track_id"] == 4
    assert final_links[0]["streaming_track_id"] == 9
    assert pending_suggestion["status"] == "pending"


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

    response = _call_endpoint(route.endpoint, 13)

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


def test_reject_proposal_regenerates_playlist_m3u(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'reject-proposal-regenerates-m3u.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIBRARY_ROOT", str(tmp_path / "library"))
    monkeypatch.setenv("M3U_OUTPUT_DIR", str(tmp_path / "m3u"))

    output_path = tmp_path / "m3u" / "Road-Trip-Mix.m3u"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("stale", encoding="utf-8")

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
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=9,
                position=1,
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

    _call_endpoint(route.endpoint, 13)

    assert output_path.read_text(encoding="utf-8") == "#EXTM3U"


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
        _call_endpoint(route.endpoint, 999)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Proposal not found"
    else:
        raise AssertionError(
            "Expected reject endpoint to raise 404 for missing proposal"
        )


def test_break_final_link_removes_final_link_and_writes_rejected_suggestion(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'break-final-link.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/broken.mp3",
                library_root_rel_path="Artist/broken.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Broken Link Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="ABC123456789",
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                id=7,
                local_track_id=4,
                streaming_track_id=9,
            )
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/final-links/{final_link_id}"
        and "DELETE" in getattr(route, "methods", set())
    )

    response = _call_endpoint(route.endpoint, 7)

    assert response["final_link_id"] == 7
    assert response["rejected_suggestion_id"] == 1
    assert response["status"] == SUGGESTED_LINK_STATUS_REJECTED
    assert response["rejected_at"] is not None

    with engine.connect() as connection:
        remaining_final_links = (
            connection.execute(select(final_links_table)).mappings().all()
        )
        suggestion = connection.execute(select(suggested_links_table)).mappings().one()

    assert remaining_final_links == []
    assert suggestion["local_track_id"] == 4
    assert suggestion["streaming_track_id"] == 9
    assert suggestion["match_method"] == "manual_break"
    assert suggestion["score"] == 0.0
    assert suggestion["status"] == SUGGESTED_LINK_STATUS_REJECTED
    assert suggestion["rejected_at"] is not None


def test_break_final_link_regenerates_playlist_m3u(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'break-final-link-regenerates-m3u.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIBRARY_ROOT", str(tmp_path / "library"))
    monkeypatch.setenv("M3U_OUTPUT_DIR", str(tmp_path / "m3u"))

    output_path = tmp_path / "m3u" / "Road-Trip-Mix.m3u"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("stale", encoding="utf-8")

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                id=4,
                file_path="Artist/broken.mp3",
                library_root_rel_path="Artist/broken.mp3",
                fingerprint="fp-4",
                beets_id=4,
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Broken Link Track",
                artist="Artist",
                album="Album",
                year=2024,
                isrc="ABC123456789",
                duration_ms=123000,
            )
        )
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=1,
                provider_playlist_id="PL7",
                title="Road Trip Mix",
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=9,
                position=1,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                id=7,
                local_track_id=4,
                streaming_track_id=9,
            )
        )

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/final-links/{final_link_id}"
        and "DELETE" in getattr(route, "methods", set())
    )

    _call_endpoint(route.endpoint, 7)

    assert output_path.read_text(encoding="utf-8") == "#EXTM3U"


def test_break_final_link_returns_404_when_missing(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'break-final-link-missing.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)

    router = create_router(require_database_url=lambda: database_url)
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", None) == "/final-links/{final_link_id}"
        and "DELETE" in getattr(route, "methods", set())
    )

    try:
        _call_endpoint(route.endpoint, 999)
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Final link not found"
    else:
        raise AssertionError(
            "Expected break final link endpoint to raise 404 for missing link"
        )
