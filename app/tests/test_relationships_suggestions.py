from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import Engine, create_engine, select

from app.relationships.models import (
    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
    STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata as relationships_metadata,
    streaming_relationship_suggestions_table,
)
from app.relationships.suggestions import (
    MATCH_METHOD_ISRC,
    MATCH_METHOD_TAGS,
    StreamingRelationshipSuggestionGenerator,
)
from app.streaming.adapters.youtube_music import YouTubeMusicPlaylist, YouTubeMusicTrack
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_OFF,
    metadata as streaming_metadata,
)
from app.streaming.store import StreamingAccountStore
from tests import factories


def test_generator_creates_isrc_equivalent_for_active_tracks() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    full_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-full",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    match_only_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-match",
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
    )
    off_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-off",
        sync_mode=PLAYLIST_SYNC_MODE_OFF,
    )
    full_track_id = test_data.streaming_track(
        provider_track_id="full-track",
        title="Same Song",
        artist="Same Artist",
        isrc="gbum72105976",
    )
    match_only_track_id = test_data.streaming_track(
        provider_track_id="match-track",
        title="Same Song",
        artist="Same Artist",
        isrc="GBUM72105976",
    )
    off_track_id = test_data.streaming_track(
        provider_track_id="off-track",
        title="Same Song",
        artist="Same Artist",
        isrc="GBUM72105976",
    )
    test_data.playlist_membership(
        playlist_id=full_playlist_id,
        streaming_track_id=full_track_id,
    )
    test_data.playlist_membership(
        playlist_id=match_only_playlist_id,
        streaming_track_id=match_only_track_id,
    )
    test_data.playlist_membership(
        playlist_id=off_playlist_id,
        streaming_track_id=off_track_id,
    )

    result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    assert result.created_count == 1
    assert _suggestions(engine) == [
        {
            "lower_track_id": full_track_id,
            "higher_track_id": match_only_track_id,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "match_method": MATCH_METHOD_ISRC,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
            "score": 1.0,
        }
    ]


def test_generator_uses_fuzzy_scoring_for_equivalent_and_related_suggestions() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    equivalent_track_id = test_data.streaming_track(
        provider_track_id="equiv-1",
        title="North Star",
        artist="June",
        album="Night",
        duration_ms=180000,
        isrc=None,
    )
    equivalent_match_id = test_data.streaming_track(
        provider_track_id="equiv-2",
        title="North Star",
        artist="June",
        album="Night",
        duration_ms=180500,
        isrc=None,
    )
    related_track_id = test_data.streaming_track(
        provider_track_id="related-1",
        title="Blue Train",
        artist="Alpha",
        album=None,
        duration_ms=220000,
        isrc=None,
    )
    related_match_id = test_data.streaming_track(
        provider_track_id="related-2",
        title="Blue Train",
        artist="Omega",
        album=None,
        duration_ms=220000,
        isrc=None,
    )
    for position, track_id in enumerate(
        (
            equivalent_track_id,
            equivalent_match_id,
            related_track_id,
            related_match_id,
        ),
        start=1,
    ):
        test_data.playlist_membership(
            playlist_id=playlist_id,
            position=position,
            streaming_track_id=track_id,
        )

    result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    suggestions = _suggestions(engine)
    assert result.created_count == 2
    assert suggestions == [
        {
            "lower_track_id": equivalent_track_id,
            "higher_track_id": equivalent_match_id,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "match_method": MATCH_METHOD_TAGS,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
            "score": suggestions[0]["score"],
        },
        {
            "lower_track_id": related_track_id,
            "higher_track_id": related_match_id,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_RELATED,
            "match_method": MATCH_METHOD_TAGS,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
            "score": suggestions[1]["score"],
        },
    ]
    assert suggestions[0]["score"] > 0.85
    assert 0.75 <= suggestions[1]["score"] <= 0.85


def test_generator_skips_cross_title_fuzzy_pairs() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    first_track_id = test_data.streaming_track(
        provider_track_id="cross-title-1",
        title="North Star",
        artist="Shared Artist",
        album="Shared Album",
        duration_ms=180000,
        isrc=None,
    )
    second_track_id = test_data.streaming_track(
        provider_track_id="cross-title-2",
        title="South Star",
        artist="Shared Artist",
        album="Shared Album",
        duration_ms=180000,
        isrc=None,
    )
    for position, track_id in enumerate((first_track_id, second_track_id), start=1):
        test_data.playlist_membership(
            playlist_id=playlist_id,
            position=position,
            streaming_track_id=track_id,
        )

    result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    assert result.created_count == 0
    assert _suggestions(engine) == []


def test_generator_dedupes_memberships_and_preserves_pending_suggestions() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    first_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL1",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    second_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL2",
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
    )
    first_track_id = test_data.streaming_track(
        provider_track_id="track-1",
        isrc="USRC17607839",
    )
    second_track_id = test_data.streaming_track(
        provider_track_id="track-2",
        isrc="USRC17607839",
    )
    test_data.playlist_membership(
        playlist_id=first_playlist_id,
        position=1,
        streaming_track_id=first_track_id,
    )
    test_data.playlist_membership(
        playlist_id=second_playlist_id,
        position=1,
        streaming_track_id=first_track_id,
    )
    test_data.playlist_membership(
        playlist_id=second_playlist_id,
        position=2,
        streaming_track_id=second_track_id,
    )

    first_result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()
    second_result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    assert first_result.created_count == 1
    assert second_result.created_count == 0
    assert len(_suggestions(engine)) == 1


def test_generator_suppresses_accepted_equivalent_relationships() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    first_track_id, second_track_id = _active_isrc_pair(test_data, playlist_id)
    test_data.streaming_relationship(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    )

    result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    assert result.created_count == 0
    assert _suggestions(engine) == []


def test_generator_suppresses_accepted_related_relationships() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    first_track_id, second_track_id = _active_isrc_pair(test_data, playlist_id)
    test_data.streaming_relationship(
        first_track_id=first_track_id,
        second_track_id=second_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
    )

    result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    assert result.created_count == 0
    assert _suggestions(engine) == []


def test_generator_suppresses_group_rejected_pairs() -> None:
    engine = _create_generation_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    first_rejected_id = test_data.streaming_track(
        provider_track_id="rejected-1",
        title="Rejected First",
        artist="Artist A",
        isrc=None,
    )
    second_rejected_id = test_data.streaming_track(
        provider_track_id="rejected-2",
        title="Rejected Second",
        artist="Artist B",
        isrc=None,
    )
    first_group_id = test_data.streaming_track(
        provider_track_id="group-1",
        title="Group First",
        artist="Artist C",
        isrc="USRC17607839",
    )
    second_group_id = test_data.streaming_track(
        provider_track_id="group-2",
        title="Group Second",
        artist="Artist D",
        isrc="USRC17607839",
    )
    for position, track_id in enumerate(
        (
            first_rejected_id,
            second_rejected_id,
            first_group_id,
            second_group_id,
        ),
        start=1,
    ):
        test_data.playlist_membership(
            playlist_id=playlist_id,
            position=position,
            streaming_track_id=track_id,
        )
    test_data.streaming_relationship(
        first_track_id=first_rejected_id,
        second_track_id=first_group_id,
    )
    test_data.streaming_relationship(
        first_track_id=second_rejected_id,
        second_track_id=second_group_id,
    )
    rejected_suggestion_id = test_data.streaming_relationship_suggestion(
        first_track_id=first_rejected_id,
        second_track_id=second_rejected_id,
        status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    )

    result = StreamingRelationshipSuggestionGenerator(engine=engine).generate()

    assert result.created_count == 0
    assert [
        suggestion["id"] for suggestion in _suggestions(engine, include_id=True)
    ] == [rejected_suggestion_id]


def test_streaming_sync_runs_relationship_suggestion_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming-sync-generates.db'}"
    engine = create_engine(database_url)
    streaming_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

    store = StreamingAccountStore(database_url)
    account = store.create_youtube_music_account(
        display_name="Listener",
        browser_headers={"refresh_token": "refresh-token"},
    )
    playlists = store.upsert_playlists(
        account_id=account.id,
        playlists=[
            YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Full Mix"),
            YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Match Mix"),
        ],
    )
    store.set_playlist_sync_mode(
        playlist_id=playlists[0].id,
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
    )
    store.set_playlist_sync_mode(
        playlist_id=playlists[1].id,
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
    )

    class FakeAdapter:
        def list_library_playlists(self):
            return [
                YouTubeMusicPlaylist(provider_playlist_id="PL1", title="Full Mix"),
                YouTubeMusicPlaylist(provider_playlist_id="PL2", title="Match Mix"),
            ]

        def list_playlist_tracks(self, playlist_id, *, limit=100):
            assert limit is None
            return [
                YouTubeMusicTrack(
                    provider_track_id=f"{playlist_id}-track",
                    title="Shared Track",
                    artist="Shared Artist",
                    album=None,
                    year=None,
                    isrc="GBUM72105976",
                    duration_ms=120000,
                )
            ]

    monkeypatch.setattr(
        "app.streaming.store.YouTubeMusicAdapter.from_browser_auth",
        lambda auth, *, user=None, language="en", location="": FakeAdapter(),
    )

    synced = store.sync_youtube_music_playlist_tracks(account_id=account.id)

    assert len(synced) == 2
    suggestions = _suggestions(engine)
    assert len(suggestions) == 1
    assert suggestions[0]["relationship_type"] == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT
    assert suggestions[0]["match_method"] == MATCH_METHOD_ISRC


def _active_isrc_pair(
    test_data: factories.TestDataFactory,
    playlist_id: int,
) -> tuple[int, int]:
    first_track_id = test_data.streaming_track(
        provider_track_id="track-1",
        isrc="USRC17607839",
    )
    second_track_id = test_data.streaming_track(
        provider_track_id="track-2",
        isrc="USRC17607839",
    )
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
    return first_track_id, second_track_id


def _suggestions(
    engine: Engine,
    *,
    include_id: bool = False,
) -> list[dict[str, object]]:
    columns = [
        streaming_relationship_suggestions_table.c.lower_track_id,
        streaming_relationship_suggestions_table.c.higher_track_id,
        streaming_relationship_suggestions_table.c.relationship_type,
        streaming_relationship_suggestions_table.c.match_method,
        streaming_relationship_suggestions_table.c.confidence,
        streaming_relationship_suggestions_table.c.status,
        streaming_relationship_suggestions_table.c.score,
    ]
    if include_id:
        columns.insert(0, streaming_relationship_suggestions_table.c.id)

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(*columns).order_by(
                    streaming_relationship_suggestions_table.c.lower_track_id.asc(),
                    streaming_relationship_suggestions_table.c.higher_track_id.asc(),
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _create_generation_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    streaming_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    return engine
