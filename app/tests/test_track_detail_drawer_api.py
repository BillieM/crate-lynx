from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, insert

from app.ingestion.beets_mirror import (
    beets_album_attributes_table,
    beets_albums_table,
    metadata as beets_metadata,
)
from app.ingestion.failures import (
    failed_ingestion_attempts_table,
    metadata as failed_ingestion_metadata,
)
from app.links.store import metadata as links_metadata
from app.local_tracks.router import create_router as create_local_tracks_router
from app.local_tracks.store import metadata as local_tracks_metadata
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_PENDING,
    metadata as suggested_links_metadata,
)
from app.relationships.models import (
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata as relationships_metadata,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    metadata as streaming_metadata,
)
from app.streaming.router import create_router as create_streaming_router
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


def test_rich_local_detail_includes_links_beets_metadata_and_failures(
    tmp_path: Path,
) -> None:
    engine = _create_track_detail_engine(tmp_path / "rich-local-detail.db")
    test_data = factories.TestDataFactory(engine)
    local_track_id = test_data.local_track(
        beets_id=101,
        file_path="Local Artist/Signals/Memory Lane.flac",
        fingerprint="fp-memory-lane",
    )
    test_data.beets_item(
        beets_id=101,
        album="Signals",
        album_id=701,
        artist="Local Artist",
        length=245.5,
        title="Memory Lane",
    )
    test_data.beets_item_attribute(beets_id=101, key="mood", value="warm")
    with engine.begin() as connection:
        connection.execute(
            insert(beets_albums_table).values(
                beets_album_id=701,
                album="Signals",
                albumartist="Local Artist",
            )
        )
        connection.execute(
            insert(beets_album_attributes_table).values(
                entity_id=701,
                key="catalognum",
                value="SIG-701",
            )
        )
        connection.execute(
            insert(failed_ingestion_attempts_table).values(
                source_path="/imports/Memory Lane.wav",
                filename="Memory Lane.wav",
                fingerprint="fp-memory-lane",
                failure_reason="beets import failed",
                failed_at=datetime(2026, 5, 3, 9, 15, tzinfo=UTC),
                local_track_id=local_track_id,
            )
        )

    final_streaming_id = test_data.streaming_track(
        album="Signals",
        artist="Local Artist",
        provider_track_id="ytm-memory",
        title="Memory Lane",
    )
    suggestion_streaming_id = test_data.streaming_track(
        album="Signals",
        artist="Local Artist",
        provider_track_id="ytm-memory-live",
        title="Memory Lane (Live)",
    )
    final_link_id = test_data.final_link(
        approved_at=datetime(2026, 5, 2, 8, 30, tzinfo=UTC),
        local_track_id=local_track_id,
        streaming_track_id=final_streaming_id,
    )
    suggestion_id = test_data.suggested_link(
        local_track_id=local_track_id,
        match_method="tags",
        score=0.83,
        status=SUGGESTED_LINK_STATUS_PENDING,
        streaming_track_id=suggestion_streaming_id,
    )

    router = create_local_tracks_router()
    response = _call_endpoint(
        _route(router, "GET", "/local-tracks/{local_track_id}").endpoint,
        local_track_id,
        engine,
    )

    assert response.id == local_track_id
    assert response.title == "Memory Lane"
    assert response.artist == "Local Artist"
    assert response.album == "Signals"
    assert response.duration_ms == 245500
    assert response.link_status == "linked"
    assert response.final_link is not None
    assert response.final_link.id == final_link_id
    assert response.final_link.streaming_track.title == "Memory Lane"
    assert [suggestion.id for suggestion in response.pending_suggestions] == [
        suggestion_id
    ]
    assert response.pending_suggestions[0].streaming_track.title == (
        "Memory Lane (Live)"
    )
    assert response.beets_item is not None
    assert {"key": "title", "value": "Memory Lane"} in [
        field.model_dump() for field in response.beets_item.fields
    ]
    assert response.beets_item.attributes[0].model_dump() == {
        "key": "mood",
        "value": "warm",
    }
    assert response.beets_album is not None
    assert response.beets_album.attributes[0].model_dump() == {
        "key": "catalognum",
        "value": "SIG-701",
    }
    assert response.failed_ingestion_attempts[0].source_path == (
        "/imports/Memory Lane.wav"
    )


def test_rich_streaming_detail_includes_resolution_relationships_and_activity(
    tmp_path: Path,
) -> None:
    engine = _create_track_detail_engine(tmp_path / "rich-streaming-detail.db")
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-detail",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Detail Playlist",
    )
    streaming_track_id = test_data.streaming_track(
        album="Afterimage",
        artist="Frame Delay",
        provider_track_id="ytm-detail",
        title="Night Runner",
    )
    equivalent_track_id = test_data.streaming_track(
        album="Afterimage",
        artist="Frame Delay",
        provider_track_id="ytm-equivalent",
        title="Night Runner (Upload)",
    )
    related_track_id = test_data.streaming_track(
        provider_track_id="ytm-related",
        title="Night Runner Remix",
    )
    local_track_id = test_data.local_track(
        beets_id=202,
        file_path="Frame Delay/Night Runner.flac",
    )
    test_data.beets_item(
        beets_id=202,
        album="Afterimage",
        artist="Frame Delay",
        title="Night Runner",
    )
    suggestion_local_id = test_data.local_track(
        beets_id=203,
        file_path="Frame Delay/Night Runner demo.flac",
    )
    test_data.beets_item(beets_id=203, title="Night Runner Demo")
    test_data.playlist_membership(
        playlist_id=playlist_id,
        position=4,
        streaming_track_id=streaming_track_id,
    )
    final_link_id = test_data.final_link(
        local_track_id=local_track_id,
        streaming_track_id=streaming_track_id,
    )
    equivalent_relationship_id = test_data.streaming_relationship(
        first_track_id=streaming_track_id,
        second_track_id=equivalent_track_id,
    )
    related_relationship_id = test_data.streaming_relationship(
        first_track_id=streaming_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        second_track_id=related_track_id,
    )
    suggestion_id = test_data.suggested_link(
        local_track_id=suggestion_local_id,
        match_method="fingerprint",
        score=0.88,
        streaming_track_id=streaming_track_id,
    )

    router = create_streaming_router(require_redis_url=lambda: "redis://example/0")
    response = _call_endpoint(
        _route(router, "GET", "/streaming/tracks/{streaming_track_id}").endpoint,
        streaming_track_id,
        engine,
    )

    assert response.id == streaming_track_id
    assert response.provider_track_id == "ytm-detail"
    assert response.resolved_local_link is not None
    assert response.resolved_local_link.final_link_id == final_link_id
    assert response.resolved_local_link.resolution_source == "direct"
    assert response.resolved_local_link.local_track.title == "Night Runner"
    assert [track.id for track in response.equivalent_tracks] == [equivalent_track_id]
    assert {relationship.id for relationship in response.relationships} == {
        equivalent_relationship_id,
        related_relationship_id,
    }
    assert response.playlist_appearances[0].title == "Detail Playlist"
    assert response.playlist_appearances[0].position == 4
    assert [suggestion.id for suggestion in response.pending_local_suggestions] == [
        suggestion_id
    ]
    assert response.pending_local_suggestions[0].local_track.file_path == (
        "Frame Delay/Night Runner demo.flac"
    )


def test_track_search_endpoints_return_link_state(tmp_path: Path) -> None:
    engine = _create_track_detail_engine(tmp_path / "track-search.db")
    test_data = factories.TestDataFactory(engine)
    linked_local_id = test_data.local_track(
        beets_id=301,
        file_path="Search/Linked.flac",
    )
    pending_local_id = test_data.local_track(
        beets_id=302,
        file_path="Search/Pending.flac",
    )
    test_data.beets_item(beets_id=301, artist="Search Artist", title="Linked")
    test_data.beets_item(beets_id=302, artist="Search Artist", title="Pending")
    linked_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-linked",
        title="Linked",
    )
    pending_streaming_id = test_data.streaming_track(
        provider_track_id="ytm-pending",
        title="Pending",
    )
    test_data.final_link(
        local_track_id=linked_local_id,
        streaming_track_id=linked_streaming_id,
    )
    test_data.suggested_link(
        local_track_id=pending_local_id,
        streaming_track_id=pending_streaming_id,
    )

    local_router = create_local_tracks_router()
    streaming_router = create_streaming_router(
        require_redis_url=lambda: "redis://example/0"
    )

    local_response = _call_endpoint(
        _route(local_router, "GET", "/local-tracks/search").endpoint,
        "Search Artist",
        20,
        engine,
    )
    streaming_response = _call_endpoint(
        _route(streaming_router, "GET", "/streaming/tracks/search").endpoint,
        "ytm",
        20,
        engine,
    )

    assert [track.id for track in local_response.tracks] == [
        linked_local_id,
        pending_local_id,
    ]
    assert [track.link_status for track in local_response.tracks] == [
        "linked",
        "pending",
    ]
    assert [track.id for track in streaming_response.tracks] == [
        linked_streaming_id,
        pending_streaming_id,
    ]
    assert [track.link_status for track in streaming_response.tracks] == [
        "linked",
        "pending",
    ]


def test_local_track_audio_streams_library_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = _create_track_detail_engine(tmp_path / "local-audio.db")
    test_data = factories.TestDataFactory(engine)
    library_root = tmp_path / "library"
    audio_path = library_root / "Artist" / "Track.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio bytes")
    monkeypatch.setenv("LIBRARY_ROOT", str(library_root))
    local_track_id = test_data.local_track(file_path="Artist/Track.mp3")

    response = _call_local_track_audio_endpoint(engine, local_track_id)

    assert isinstance(response, FileResponse)
    assert Path(response.path) == audio_path
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"] == 'inline; filename="Track.mp3"'
    assert response.media_type == "audio/mpeg"


def test_local_track_audio_returns_404_for_unknown_track(tmp_path: Path) -> None:
    engine = _create_track_detail_engine(tmp_path / "missing-track-audio.db")

    try:
        _call_local_track_audio_endpoint(engine, 404)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected HTTPException")


def test_local_track_audio_returns_404_for_missing_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = _create_track_detail_engine(tmp_path / "missing-file-audio.db")
    test_data = factories.TestDataFactory(engine)
    library_root = tmp_path / "library"
    library_root.mkdir()
    monkeypatch.setenv("LIBRARY_ROOT", str(library_root))
    local_track_id = test_data.local_track(file_path="Artist/Missing.mp3")

    try:
        _call_local_track_audio_endpoint(engine, local_track_id)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected HTTPException")


def test_local_track_audio_returns_404_for_path_escape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = _create_track_detail_engine(tmp_path / "escaped-audio.db")
    test_data = factories.TestDataFactory(engine)
    library_root = tmp_path / "library"
    library_root.mkdir()
    escaped_path = tmp_path / "outside.mp3"
    escaped_path.write_bytes(b"outside")
    monkeypatch.setenv("LIBRARY_ROOT", str(library_root))
    local_track_id = test_data.local_track(file_path="../outside.mp3")

    try:
        _call_local_track_audio_endpoint(engine, local_track_id)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected HTTPException")


def _call_local_track_audio_endpoint(engine, local_track_id: int):
    router = create_local_tracks_router()
    return _call_endpoint(
        _route(router, "GET", "/local-tracks/{local_track_id}/audio").endpoint,
        local_track_id,
        engine,
    )


def _create_track_detail_engine(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    beets_metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    failed_ingestion_metadata.create_all(engine)
    return engine
