from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from sqlalchemy import create_engine, event, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.matching.pipeline import metadata as suggested_links_metadata
from app.matching.pipeline import suggested_links_table
from app.relationships.models import (
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata as relationships_metadata,
    streaming_relationship_suggestions_table,
    streaming_relationships_table,
)
from app.relationships.router import create_router
from app.relationships.schemas import (
    AcceptStreamingRelationshipSuggestionRequest,
    CreateStreamingRelationshipRequest,
    UpdateStreamingRelationshipRequest,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    metadata as streaming_metadata,
)
from tests import factories


def _call_endpoint(endpoint, *args, **kwargs):
    result = endpoint(*args, **kwargs)
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
        ],
        "total_count": 1,
        "returned_count": 1,
        "limit": 50,
        "next_cursor": None,
    }


def test_list_relationship_suggestions_batches_local_link_context_queries(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-list-context-batch.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)

    for index in range(3):
        first_track_id = test_data.streaming_track(
            provider_track_id=f"ytm-context-{index}-a",
            title=f"Track {index} A",
        )
        second_track_id = test_data.streaming_track(
            provider_track_id=f"ytm-context-{index}-b",
            title=f"Track {index} B",
        )
        first_local_id = test_data.local_track(
            beets_id=100 + index * 2,
            file_path=f"Artist/context-{index}-a.mp3",
        )
        second_local_id = test_data.local_track(
            beets_id=101 + index * 2,
            file_path=f"Artist/context-{index}-b.mp3",
        )
        test_data.beets_item(
            beets_id=100 + index * 2,
            title=f"Local {index} A",
        )
        test_data.beets_item(
            beets_id=101 + index * 2,
            title=f"Local {index} B",
        )
        test_data.final_link(
            local_track_id=first_local_id,
            streaming_track_id=first_track_id,
        )
        test_data.final_link(
            local_track_id=second_local_id,
            streaming_track_id=second_track_id,
        )
        test_data.streaming_relationship_suggestion(
            first_track_id=first_track_id,
            second_track_id=second_track_id,
            score=0.99 - index / 100,
        )

    local_link_context_statement_count = 0

    def count_local_link_context_statement(
        conn, cursor, statement, parameters, context, executemany
    ) -> None:
        nonlocal local_link_context_statement_count
        if (
            "final_links" in statement
            and "local_tracks" in statement
            and "beets_items" in statement
        ):
            local_link_context_statement_count += 1

    event.listen(engine, "before_cursor_execute", count_local_link_context_statement)
    router = create_router(require_database_url=lambda: database_url)

    try:
        response = _call_endpoint(
            _route(router, "GET", "/streaming/relationships/suggestions").endpoint,
            engine=engine,
        )
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            count_local_link_context_statement,
        )

    assert response.returned_count == 3
    assert local_link_context_statement_count == 1


def test_list_relationship_suggestions_limits_returned_rows(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-list-limit.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    third_track_id = test_data.streaming_track(
        provider_track_id="ytm-3",
        title="Track 3",
    )
    fourth_track_id = test_data.streaming_track(
        provider_track_id="ytm-4",
        title="Track 4",
    )
    higher_score_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        score=0.99,
    )
    test_data.streaming_relationship_suggestion(
        first_track_id=third_track_id,
        second_track_id=fourth_track_id,
        score=0.75,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(router, "GET", "/streaming/relationships/suggestions").endpoint,
        limit=1,
    )

    assert response.total_count == 2
    assert response.returned_count == 1
    assert response.limit == 1
    assert response.next_cursor is not None
    assert [suggestion.id for suggestion in response.suggestions] == [higher_score_id]


def test_list_relationship_suggestions_uses_cursor_pagination(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-list-cursor.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    third_track_id = test_data.streaming_track(
        provider_track_id="ytm-3",
        title="Track 3",
    )
    fourth_track_id = test_data.streaming_track(
        provider_track_id="ytm-4",
        title="Track 4",
    )
    fifth_track_id = test_data.streaming_track(
        provider_track_id="ytm-5",
        title="Track 5",
    )
    sixth_track_id = test_data.streaming_track(
        provider_track_id="ytm-6",
        title="Track 6",
    )
    first_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        score=0.99,
    )
    second_id = test_data.streaming_relationship_suggestion(
        first_track_id=third_track_id,
        second_track_id=fourth_track_id,
        score=0.99,
    )
    third_id = test_data.streaming_relationship_suggestion(
        first_track_id=fifth_track_id,
        second_track_id=sixth_track_id,
        score=0.75,
    )

    router = create_router(require_database_url=lambda: database_url)
    endpoint = _route(router, "GET", "/streaming/relationships/suggestions").endpoint
    first_page = _call_endpoint(endpoint, limit=2)
    second_page = _call_endpoint(endpoint, cursor=first_page.next_cursor, limit=2)

    assert first_page.total_count == 3
    assert [suggestion.id for suggestion in first_page.suggestions] == [
        first_id,
        second_id,
    ]
    assert first_page.next_cursor is not None
    assert second_page.total_count == 3
    assert [suggestion.id for suggestion in second_page.suggestions] == [third_id]
    assert second_page.next_cursor is None


def test_list_relationship_suggestions_filters_by_relationship_type(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-list-filter.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    third_track_id = test_data.streaming_track(
        provider_track_id="ytm-3",
        title="Track 3",
    )
    fourth_track_id = test_data.streaming_track(
        provider_track_id="ytm-4",
        title="Track 4",
    )
    test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
        score=0.99,
    )
    related_id = test_data.streaming_relationship_suggestion(
        first_track_id=third_track_id,
        second_track_id=fourth_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        score=0.92,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(router, "GET", "/streaming/relationships/suggestions").endpoint,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
    )

    assert response.total_count == 1
    assert response.returned_count == 1
    assert response.limit == 50
    assert response.next_cursor is None
    assert [suggestion.id for suggestion in response.suggestions] == [related_id]
    assert response.suggestions[0].relationship_type == "related"


def test_list_relationship_suggestions_hides_stale_rows_without_pruning(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-list-stale.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    group_track_id = test_data.streaming_track(
        provider_track_id="ytm-3",
        title="Track 3",
    )
    exact_first_id = test_data.streaming_track(
        provider_track_id="ytm-4",
        title="Track 4",
    )
    exact_second_id = test_data.streaming_track(
        provider_track_id="ytm-5",
        title="Track 5",
    )
    fresh_first_id = test_data.streaming_track(
        provider_track_id="ytm-6",
        title="Track 6",
    )
    fresh_second_id = test_data.streaming_track(
        provider_track_id="ytm-7",
        title="Track 7",
    )
    test_data.streaming_relationship(
        first_track_id=first_track_id,
        second_track_id=group_track_id,
    )
    test_data.streaming_relationship(
        first_track_id=second_track_id,
        second_track_id=group_track_id,
    )
    test_data.streaming_relationship(
        first_track_id=exact_first_id,
        second_track_id=exact_second_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
    )
    equivalent_stale_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        score=0.99,
    )
    related_stale_id = test_data.streaming_relationship_suggestion(
        first_track_id=exact_first_id,
        second_track_id=exact_second_id,
        score=0.98,
    )
    fresh_id = test_data.streaming_relationship_suggestion(
        first_track_id=fresh_first_id,
        second_track_id=fresh_second_id,
        score=0.75,
    )

    router = create_router(require_database_url=lambda: database_url)
    response = _call_endpoint(
        _route(router, "GET", "/streaming/relationships/suggestions").endpoint,
        limit=1,
    )

    assert response.total_count == 1
    assert response.returned_count == 1
    assert response.next_cursor is None
    assert [suggestion.id for suggestion in response.suggestions] == [
        fresh_id,
    ]
    with engine.connect() as connection:
        pending_ids = set(
            connection.execute(
                select(streaming_relationship_suggestions_table.c.id).where(
                    streaming_relationship_suggestions_table.c.status
                    == STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING
                )
            ).scalars()
        )

    assert pending_ids == {equivalent_stale_id, related_stale_id, fresh_id}


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


def test_accept_equivalent_recommendation_as_related_ignores_link_conflicts(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-equivalent-as-related.db'}"
    engine = _create_relationship_router_engine(database_url)
    test_data = factories.TestDataFactory(engine)
    first_track_id, second_track_id = _streaming_pair(test_data)
    first_local_id = test_data.local_track(file_path="Artist/first.mp3")
    second_local_id = test_data.local_track(file_path="Artist/second.mp3")
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
        relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
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
            relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        ),
    )

    assert response.relationship_type == "related"
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
        final_link_ids = connection.execute(
            select(final_links_table.c.id).order_by(final_links_table.c.id.asc())
        ).scalars()

    assert relationship["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_RELATED
    assert suggestion["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT
    assert list(final_link_ids) == [first_link_id, second_link_id]


def test_accept_related_recommendation_as_equivalent_resolves_conflicts(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-related-as-equivalent.db'}"
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
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        second_track_id=second_track_id,
    )

    router = create_router(require_database_url=lambda: database_url)
    list_response = _call_endpoint(
        _route(router, "GET", "/streaming/relationships/suggestions").endpoint,
    )
    assert list_response.suggestions[0].relationship_type == "related"
    assert list_response.suggestions[0].conflict_state == "different_local_links"
    try:
        _call_endpoint(
            _route(
                router,
                "POST",
                "/streaming/relationships/suggestions/{suggestion_id}/accept",
            ).endpoint,
            suggestion_id,
            AcceptStreamingRelationshipSuggestionRequest(
                relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            ),
        )
    except StarletteHTTPException as exc:
        assert exc.status_code == 409
        assert (
            exc.detail
            == "winning_final_link_id is required for conflicting equivalent relationship"
        )
    else:
        raise AssertionError(
            "Expected related recommendation accepted as equivalent to require a winner"
        )

    response = _call_endpoint(
        _route(
            router,
            "POST",
            "/streaming/relationships/suggestions/{suggestion_id}/accept",
        ).endpoint,
        suggestion_id,
        AcceptStreamingRelationshipSuggestionRequest(
            relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            winning_final_link_id=winning_link_id,
        ),
    )

    assert response.relationship_type == "equivalent"
    assert response.detached_final_link_ids == [losing_link_id]
    with engine.connect() as connection:
        relationship = (
            connection.execute(select(streaming_relationships_table)).mappings().one()
        )
        suggestion = (
            connection.execute(select(streaming_relationship_suggestions_table))
            .mappings()
            .one()
        )
        final_link_ids = list(
            connection.execute(select(final_links_table.c.id)).scalars()
        )

    assert relationship["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT
    assert suggestion["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_RELATED
    assert final_link_ids == [winning_link_id]


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
    stale_first_id = test_data.streaming_track(
        provider_track_id="stale-1",
        title="Stale First",
        isrc=None,
    )
    stale_second_id = test_data.streaming_track(
        provider_track_id="stale-2",
        title="Stale Second",
        isrc=None,
    )
    test_data.streaming_relationship_suggestion(
        first_track_id=stale_first_id,
        second_track_id=stale_second_id,
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
    assert response.pruned_count == 1


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


def test_streaming_relationship_create_update_delete_endpoints(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'relationship-manual-crud.db'}"
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

    router = create_router(
        require_database_url=lambda: database_url,
        require_redis_url=lambda: "redis://redis:6379/9",
    )
    create_response = _call_endpoint(
        _route(router, "POST", "/streaming/relationships").endpoint,
        CreateStreamingRelationshipRequest(
            first_track_id=first_track_id,
            relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
            second_track_id=second_track_id,
        ),
    )

    assert create_response.status == "created"
    assert create_response.relationship_type == "related"
    assert create_response.detached_final_link_ids == []
    assert seen == {"redis_urls": [], "playlist_ids": []}

    update_response = _call_endpoint(
        _route(router, "PATCH", "/streaming/relationships/{relationship_id}").endpoint,
        create_response.relationship_id,
        UpdateStreamingRelationshipRequest(
            relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
        ),
    )

    assert update_response.status == "updated"
    assert update_response.relationship_type == "equivalent"
    assert update_response.detached_final_link_ids == []

    delete_response = _call_endpoint(
        _route(
            router,
            "DELETE",
            "/streaming/relationships/{relationship_id}",
        ).endpoint,
        create_response.relationship_id,
    )

    assert delete_response.status == "deleted"
    assert delete_response.relationship_type == "equivalent"
    assert delete_response.accepted_at is None
    assert seen == {
        "redis_urls": ["redis://redis:6379/9", "redis://redis:6379/9"],
        "playlist_ids": [
            (first_playlist_id, second_playlist_id),
            (first_playlist_id, second_playlist_id),
        ],
    }
    with engine.connect() as connection:
        relationships = connection.execute(select(streaming_relationships_table)).all()

    assert relationships == []


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
