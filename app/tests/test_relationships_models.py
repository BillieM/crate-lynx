from __future__ import annotations

from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError
import pytest

from app.relationships.models import (
    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
    STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata,
    normalize_streaming_track_pair,
    streaming_relationship_suggestions_table,
    streaming_relationships_table,
)
from tests import factories


def test_normalize_streaming_track_pair_orders_distinct_track_ids() -> None:
    pair = normalize_streaming_track_pair(42, 7)

    assert pair.lower_track_id == 7
    assert pair.higher_track_id == 42


def test_normalize_streaming_track_pair_rejects_self_relationships() -> None:
    with pytest.raises(ValueError, match="two distinct tracks"):
        normalize_streaming_track_pair(7, 7)


def test_streaming_relationships_store_accepted_equivalent_and_related_edges() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    test_data = factories.TestDataFactory(engine)

    equivalent_id = test_data.streaming_relationship(
        first_track_id=2,
        second_track_id=1,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    )
    related_id = test_data.streaming_relationship(
        first_track_id=3,
        second_track_id=4,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
    )

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(
                    streaming_relationships_table.c.id,
                    streaming_relationships_table.c.lower_track_id,
                    streaming_relationships_table.c.higher_track_id,
                    streaming_relationships_table.c.relationship_type,
                    streaming_relationships_table.c.accepted_at,
                ).order_by(streaming_relationships_table.c.id.asc())
            )
            .mappings()
            .all()
        )

    assert [row["id"] for row in rows] == [equivalent_id, related_id]
    assert [dict(row) for row in rows] == [
        {
            "id": equivalent_id,
            "lower_track_id": 1,
            "higher_track_id": 2,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "accepted_at": rows[0]["accepted_at"],
        },
        {
            "id": related_id,
            "lower_track_id": 3,
            "higher_track_id": 4,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_RELATED,
            "accepted_at": rows[1]["accepted_at"],
        },
    ]
    assert rows[0]["accepted_at"] is not None
    assert rows[1]["accepted_at"] is not None


def test_streaming_relationships_reject_unnormalized_and_duplicate_pairs() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_relationships_table).values(
                lower_track_id=1,
                higher_track_id=2,
                relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(streaming_relationships_table).values(
                    lower_track_id=2,
                    higher_track_id=1,
                    relationship_type=STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
                )
            )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(streaming_relationships_table).values(
                    lower_track_id=1,
                    higher_track_id=2,
                    relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
                )
            )


def test_streaming_relationship_suggestions_store_all_statuses() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    test_data = factories.TestDataFactory(engine)

    relationship_id = test_data.streaming_relationship(
        first_track_id=1,
        second_track_id=2,
    )
    pending_id = test_data.streaming_relationship_suggestion(
        first_track_id=5,
        second_track_id=3,
        status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    )
    accepted_id = test_data.streaming_relationship_suggestion(
        accepted_relationship_id=relationship_id,
        confidence=STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
        first_track_id=2,
        second_track_id=1,
        status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    )
    rejected_id = test_data.streaming_relationship_suggestion(
        confidence=STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
        first_track_id=8,
        second_track_id=9,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        status=STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
    )

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(
                    streaming_relationship_suggestions_table.c.id,
                    streaming_relationship_suggestions_table.c.lower_track_id,
                    streaming_relationship_suggestions_table.c.higher_track_id,
                    streaming_relationship_suggestions_table.c.relationship_type,
                    streaming_relationship_suggestions_table.c.confidence,
                    streaming_relationship_suggestions_table.c.status,
                    streaming_relationship_suggestions_table.c.accepted_relationship_id,
                    streaming_relationship_suggestions_table.c.accepted_at,
                    streaming_relationship_suggestions_table.c.rejected_at,
                ).order_by(streaming_relationship_suggestions_table.c.id.asc())
            )
            .mappings()
            .all()
        )

    assert [dict(row) for row in rows] == [
        {
            "id": pending_id,
            "lower_track_id": 3,
            "higher_track_id": 5,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
            "accepted_relationship_id": None,
            "accepted_at": None,
            "rejected_at": None,
        },
        {
            "id": accepted_id,
            "lower_track_id": 1,
            "higher_track_id": 2,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
            "accepted_relationship_id": relationship_id,
            "accepted_at": rows[1]["accepted_at"],
            "rejected_at": None,
        },
        {
            "id": rejected_id,
            "lower_track_id": 8,
            "higher_track_id": 9,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_RELATED,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
            "accepted_relationship_id": None,
            "accepted_at": None,
            "rejected_at": rows[2]["rejected_at"],
        },
    ]
    assert rows[1]["accepted_at"] is not None
    assert rows[2]["rejected_at"] is not None


def test_streaming_relationships_reject_invalid_values() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(streaming_relationships_table).values(
                lower_track_id=1,
                higher_track_id=2,
                relationship_type="unsupported",
            )
        )


@pytest.mark.parametrize(
    "column_values",
    [
        {
            "lower_track_id": 1,
            "higher_track_id": 2,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "match_method": "isrc",
            "score": 0.98,
            "confidence": "unsupported",
            "status": STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
        },
        {
            "lower_track_id": 1,
            "higher_track_id": 2,
            "relationship_type": STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
            "match_method": "isrc",
            "score": 0.98,
            "confidence": STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
            "status": "unsupported",
        },
    ],
)
def test_streaming_relationship_suggestions_reject_invalid_values(
    column_values: dict[str, object],
) -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(streaming_relationship_suggestions_table).values(column_values)
        )
