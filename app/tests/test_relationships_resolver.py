from __future__ import annotations

from sqlalchemy import Engine, create_engine

from app.links.store import metadata as links_metadata
from app.relationships.models import (
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata as relationships_metadata,
)
from app.relationships.resolver import (
    RESOLUTION_SOURCE_DIRECT,
    RESOLUTION_SOURCE_EQUIVALENT,
    StreamingRelationshipResolver,
)
from tests import factories


def test_resolver_returns_direct_final_link_for_exact_streaming_track() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    direct_link_id = test_data.final_link(local_track_id=100, streaming_track_id=1)
    test_data.final_link(local_track_id=200, streaming_track_id=2)
    test_data.streaming_relationship(first_track_id=1, second_track_id=2)

    with engine.connect() as connection:
        resolved = StreamingRelationshipResolver(connection).resolve(1)

    assert resolved is not None
    assert resolved.streaming_track_id == 1
    assert resolved.final_link_id == direct_link_id
    assert resolved.local_track_id == 100
    assert resolved.source_streaming_track_id == 1
    assert resolved.resolution_source == RESOLUTION_SOURCE_DIRECT


def test_resolver_uses_single_group_link_for_unlinked_equivalent_member() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    final_link_id = test_data.final_link(local_track_id=100, streaming_track_id=1)
    test_data.streaming_relationship(first_track_id=1, second_track_id=2)

    with engine.connect() as connection:
        resolved = StreamingRelationshipResolver(connection).resolve(2)

    assert resolved is not None
    assert resolved.streaming_track_id == 2
    assert resolved.final_link_id == final_link_id
    assert resolved.local_track_id == 100
    assert resolved.source_streaming_track_id == 1
    assert resolved.resolution_source == RESOLUTION_SOURCE_EQUIVALENT


def test_resolver_uses_transitive_equivalent_group_link() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    final_link_id = test_data.final_link(local_track_id=100, streaming_track_id=1)
    test_data.streaming_relationship(first_track_id=1, second_track_id=2)
    test_data.streaming_relationship(first_track_id=2, second_track_id=3)

    with engine.connect() as connection:
        resolved = StreamingRelationshipResolver(connection).resolve(3)

    assert resolved is not None
    assert resolved.final_link_id == final_link_id
    assert resolved.local_track_id == 100
    assert resolved.source_streaming_track_id == 1
    assert resolved.resolution_source == RESOLUTION_SOURCE_EQUIVALENT


def test_related_relationships_do_not_resolve_unlinked_tracks() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    test_data.final_link(local_track_id=100, streaming_track_id=1)
    test_data.streaming_relationship(
        first_track_id=1,
        second_track_id=2,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
    )

    with engine.connect() as connection:
        resolved = StreamingRelationshipResolver(connection).resolve(2)

    assert resolved is None


def test_unlinked_equivalent_group_has_no_resolution() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    test_data.streaming_relationship(first_track_id=1, second_track_id=2)

    with engine.connect() as connection:
        resolved = StreamingRelationshipResolver(connection).resolve(1)

    assert resolved is None


def test_conflict_detector_detects_different_local_links_across_groups() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    first_link_id = test_data.final_link(local_track_id=100, streaming_track_id=3)
    second_link_id = test_data.final_link(local_track_id=200, streaming_track_id=4)
    test_data.streaming_relationship(first_track_id=1, second_track_id=3)
    test_data.streaming_relationship(first_track_id=2, second_track_id=4)

    with engine.connect() as connection:
        conflict = StreamingRelationshipResolver(
            connection
        ).detect_equivalent_acceptance_conflict(1, 2)

    assert conflict is not None
    assert conflict.first_track_id == 1
    assert conflict.second_track_id == 2
    assert conflict.first_group_track_ids == (1, 3)
    assert conflict.second_group_track_ids == (2, 4)
    assert conflict.local_track_ids == (100, 200)
    assert {link.id for link in conflict.final_links} == {
        first_link_id,
        second_link_id,
    }


def test_conflict_detector_treats_same_resolved_local_as_non_conflicting() -> None:
    engine = _create_relationship_resolver_engine()
    test_data = factories.TestDataFactory(engine)
    test_data.final_link(local_track_id=100, streaming_track_id=3)
    test_data.streaming_relationship(first_track_id=1, second_track_id=3)
    test_data.streaming_relationship(first_track_id=2, second_track_id=3)

    with engine.connect() as connection:
        conflict = StreamingRelationshipResolver(
            connection
        ).detect_equivalent_acceptance_conflict(1, 2)

    assert conflict is None


def _create_relationship_resolver_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    return engine
