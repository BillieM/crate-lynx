from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from sqlalchemy import create_engine, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.matching.pipeline import metadata as suggested_links_metadata
from app.matching.pipeline import suggested_links_table
from app.relationships.models import (
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata as relationships_metadata,
    streaming_relationship_suggestions_table,
    streaming_relationships_table,
)
from app.relationships.router import create_router
from app.relationships.schemas import AcceptStreamingRelationshipSuggestionRequest
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    metadata as streaming_metadata,
)
from tests import factories


def _call_endpoint(endpoint, *args):
    result = endpoint(*args)
    if inspect.isawaitable(result):
        return asyncio.run(result)
    return result


def _route(router, method: str, path: str):
    return next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def _capture_m3u_enqueues(monkeypatch) -> dict[str, list[object]]:
    seen: dict[str, list[object]] = {"redis_urls": [], "playlist_ids": []}

    class FakeM3uRegenerationJobEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_urls"].append(redis_url)

        def enqueue_playlists(self, playlist_ids) -> list[str]:
            seen["playlist_ids"].append(tuple(playlist_ids))
            return ["m3u-job-123"]

    monkeypatch.setattr(
        "app.relationships.router.M3uRegenerationJobEnqueuer",
        FakeM3uRegenerationJobEnqueuer,
    )
    return seen


def test_list_relationship_suggestions_returns_metadata_links_and_conflicts(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-list.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    first_local_id = test_data.local_track(
        beets_id=10,
        file_path="Artist/first.mp3",
    )
    second_local_id = test_data.local_track(
        beets_id=20,
        file_path="Artist/second.mp3",
    )
    test_data.beets_item(
        beets_id=10,
        title="First Local",
        artist="Local Artist",
        album="Local Album",
    )
    test_data.beets_item(
        beets_id=20,
        title="Second Local",
        artist="Other Artist",
        album="Other Album",
    )
    first_link_id = test_data.final_link(
        local_track_id=first_local_id,
        streaming_track_id=first_track_id,
    )
    second_link_id = test_data.final_link(
        local_track_id=second_local_id,
        streaming_track_id=second_track_id,
    )
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
        score=0.99,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(router, "GET", "/streaming/relationships/suggestions").endpoint,
    )

    assert response.model_dump(mode="json") == {
        "suggestions": [
            {
                "id": suggestion_id,
                "relationship_type": "equivalent",
                "match_method": "isrc",
                "score": 0.99,
                "confidence": "high",
                "status": "pending",
                "created_at": response.suggestions[0].created_at,
                "first_track": {
                    "id": first_track_id,
                    "provider_track_id": "ytm-1",
                    "title": "Track 1",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "ABC123456789",
                    "duration_ms": 123000,
                },
                "second_track": {
                    "id": second_track_id,
                    "provider_track_id": "ytm-2",
                    "title": "Track 2",
                    "artist": "Artist",
                    "album": "Album",
                    "year": 2024,
                    "isrc": "ABC123456789",
                    "duration_ms": 123000,
                },
                "first_link": {
                    "final_link_id": first_link_id,
                    "local_track_id": first_local_id,
                    "local_file_path": "Artist/first.mp3",
                    "local_title": "First Local",
                    "local_artist": "Local Artist",
                    "local_album": "Local Album",
                    "streaming_track_id": first_track_id,
                    "source_streaming_track_id": first_track_id,
                    "resolution_source": "direct",
                    "approved_at": response.suggestions[0].first_link.approved_at,
                },
                "second_link": {
                    "final_link_id": second_link_id,
                    "local_track_id": second_local_id,
                    "local_file_path": "Artist/second.mp3",
                    "local_title": "Second Local",
                    "local_artist": "Other Artist",
                    "local_album": "Other Album",
                    "streaming_track_id": second_track_id,
                    "source_streaming_track_id": second_track_id,
                    "resolution_source": "direct",
                    "approved_at": response.suggestions[0].second_link.approved_at,
                },
                "conflict_state": "different_local_links",
                "conflict": {
                    "first_group_track_ids": [first_track_id],
                    "second_group_track_ids": [second_track_id],
                    "local_track_ids": [first_local_id, second_local_id],
                    "final_links": [
                        response.suggestions[0]
                        .conflict.final_links[0]
                        .model_dump(mode="json"),
                        response.suggestions[0]
                        .conflict.final_links[1]
                        .model_dump(mode="json"),
                    ],
                },
            }
        ]
    }


def test_accept_equivalent_suggestion_creates_relationship(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-accept.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    local_track_id = test_data.local_track()
    test_data.final_link(
        local_track_id=local_track_id,
        streaming_track_id=first_track_id,
    )
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/{suggestion_id}/accept",
        ).endpoint,
        suggestion_id,
    )

    assert response.relationship_type == "equivalent"
    assert response.status == "accepted"
    assert response.detached_final_link_ids == []
    with engine.connect() as connection:
        relationship = (
            connection.execute(select(streaming_relationships_table)).mappings().one()
        )
        suggestion = (
            connection.execute(select(streaming_relationship_suggestions_table))
            .mappings()
            .one()
        )

    assert relationship["lower_track_id"] == first_track_id
    assert relationship["higher_track_id"] == second_track_id
    assert relationship["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT
    assert suggestion["status"] == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED
    assert suggestion["accepted_relationship_id"] == relationship["id"]


def test_accept_related_suggestion_ignores_link_conflicts(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-related.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    first_local_id = test_data.local_track(file_path="Artist/first.mp3")
    second_local_id = test_data.local_track(file_path="Artist/second.mp3")
    test_data.final_link(
        local_track_id=first_local_id,
        streaming_track_id=first_track_id,
    )
    test_data.final_link(
        local_track_id=second_local_id,
        streaming_track_id=second_track_id,
    )
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        second_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/{suggestion_id}/accept",
        ).endpoint,
        suggestion_id,
    )

    assert response.relationship_type == "related"
    assert response.detached_final_link_ids == []
    with engine.connect() as connection:
        relationship = (
            connection.execute(select(streaming_relationships_table)).mappings().one()
        )
        final_link_ids = connection.execute(
            select(final_links_table.c.id).order_by(final_links_table.c.id.asc())
        ).scalars()

    assert relationship["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_RELATED
    assert list(final_link_ids) == [1, 2]


def test_reject_relationship_suggestion_marks_rejected(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-reject.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/{suggestion_id}/reject",
        ).endpoint,
        suggestion_id,
    )

    assert response.status == "rejected"
    with engine.connect() as connection:
        suggestion = (
            connection.execute(select(streaming_relationship_suggestions_table))
            .mappings()
            .one()
        )

    assert suggestion["status"] == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED
    assert suggestion["rejected_at"] is not None


def test_generate_relationship_suggestions_returns_created_count(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-generate.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    first_track_id, second_track_id = _streaming_pair(test_data)
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=1,
        streaming_track_id=first_track_id,
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=2,
        streaming_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/generate",
        ).endpoint,
    )

    assert response.created_count == 1


def test_accept_relationship_suggestion_returns_404_when_missing(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-missing.db'}"
    _create_relationship_router_engine(database_url)

    router = create_router(require_database_url=lambda: database_url)
    try:
        _call_endpoint(
            _route(
                router,
                "POST",
                "/streaming/relationships/suggestions/{suggestion_id}/accept",
            ).endpoint,
            999,
        )
    except StarletteHTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Relationship suggestion not found"
    else:
        raise AssertionError("Expected missing relationship suggestion to return 404")


def test_accept_relationship_suggestion_returns_409_when_stale(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-stale.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    )

    router = create_router(require_database_url=lambda: database_url)
    try:
        _call_endpoint(
            _route(
                router,
                "POST",
                "/streaming/relationships/suggestions/{suggestion_id}/accept",
            ).endpoint,
            suggestion_id,
        )
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "Relationship suggestion is no longer pending"
    else:
        raise AssertionError("Expected stale relationship suggestion to return 409")


def test_accept_equivalent_conflict_requires_winning_final_link(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-conflict-required.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    test_data.final_link(
        local_track_id=test_data.local_track(file_path="Artist/first.mp3"),
        streaming_track_id=first_track_id,
    )
    test_data.final_link(
        local_track_id=test_data.local_track(file_path="Artist/second.mp3"),
        streaming_track_id=second_track_id,
    )
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    try:
        _call_endpoint(
            _route(
                router,
                "POST",
                "/streaming/relationships/suggestions/{suggestion_id}/accept",
            ).endpoint,
            suggestion_id,
        )
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert (
            exc.detail
            == "winning_final_link_id is required for conflicting equivalent relationship"
        )
    else:
        raise AssertionError("Expected conflicting relationship to require a winner")


def test_accept_equivalent_conflict_detaches_losing_links_without_rejection(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-conflict-detach.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    first_local_id = test_data.local_track(file_path="Artist/first.mp3")
    second_local_id = test_data.local_track(file_path="Artist/second.mp3")
    winning_link_id = test_data.final_link(
        local_track_id=first_local_id,
        streaming_track_id=first_track_id,
    )
    losing_link_id = test_data.final_link(
        local_track_id=second_local_id,
        streaming_track_id=second_track_id,
    )
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/{suggestion_id}/accept",
        ).endpoint,
        suggestion_id,
        AcceptStreamingRelationshipSuggestionRequest(
            winning_final_link_id=winning_link_id,
        ),
    )

    assert response.detached_final_link_ids == [losing_link_id]
    with engine.connect() as connection:
        final_link_ids = list(
            connection.execute(select(final_links_table.c.id)).scalars()
        )
        rejected_suggestion_count = len(
            connection.execute(select(suggested_links_table.c.id)).scalars().all()
        )

    assert final_link_ids == [winning_link_id]
    assert rejected_suggestion_count == 0


def test_accept_equivalent_suggestion_enqueues_m3u_regeneration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-m3u.db'}"
    engine = _create_relationship_router_engine(database_url)
    seen = _capture_m3u_enqueues(monkeypatch)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    first_track_id, second_track_id = _streaming_pair(test_data)
    first_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-first",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    second_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-second",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    test_data.playlist_membership(
        playlist_id=first_playlist_id,
        streaming_track_id=first_track_id,
    )
    test_data.playlist_membership(
        playlist_id=second_playlist_id,
        streaming_track_id=second_track_id,
    )
    suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
    )

    router = create_router(
        require_database_url=lambda: database_url,
        require_redis_url=lambda: "redis://redis:6379/9",
    )
    _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/{suggestion_id}/accept",
        ).endpoint,
        suggestion_id,
    )

    assert seen == {
        "redis_urls": ["redis://redis:6379/9"],
        "playlist_ids": [(first_playlist_id, second_playlist_id)],
    }


def _streaming_pair(
    test_data: factories.TestDataFactory,
) -> tuple[int, int]:
    first_track_id = test_data.streaming_track(
        provider_track_id="ytm-1",
        title="Track 1",
        artist="Artist",
        isrc="ABC123456789",
    )
    second_track_id = test_data.streaming_track(
        provider_track_id="ytm-2",
        title="Track 2",
        artist="Artist",
        isrc="ABC123456789",
    )
    return first_track_id, second_track_id


def _create_relationship_router_engine(database_url: str):
    engine = create_engine(database_url)
    beets_metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    return engine
