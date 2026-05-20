from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)


STREAMING_RELATIONSHIP_TYPE_EQUIVALENT = "equivalent"
STREAMING_RELATIONSHIP_TYPE_RELATED = "related"
STREAMING_RELATIONSHIP_TYPES = (
    STREAMING_RELATIONSHIP_TYPE_EQUIVALENT,
    STREAMING_RELATIONSHIP_TYPE_RELATED,
)

STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING = "pending"
STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED = "accepted"
STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED = "rejected"
STREAMING_RELATIONSHIP_SUGGESTION_STATUSES = (
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_PENDING,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_ACCEPTED,
    STREAMING_RELATIONSHIP_SUGGESTION_STATUS_REJECTED,
)

STREAMING_RELATIONSHIP_CONFIDENCE_HIGH = "high"
STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM = "medium"
STREAMING_RELATIONSHIP_CONFIDENCE_LOW = "low"
STREAMING_RELATIONSHIP_CONFIDENCES = (
    STREAMING_RELATIONSHIP_CONFIDENCE_HIGH,
    STREAMING_RELATIONSHIP_CONFIDENCE_MEDIUM,
    STREAMING_RELATIONSHIP_CONFIDENCE_LOW,
)

metadata = MetaData()


@dataclass(frozen=True, slots=True)
class NormalizedStreamingTrackPair:
    lower_track_id: int
    higher_track_id: int


def normalize_streaming_track_pair(
    first_track_id: int,
    second_track_id: int,
) -> NormalizedStreamingTrackPair:
    if first_track_id == second_track_id:
        raise ValueError("Streaming relationships require two distinct tracks")

    lower_track_id, higher_track_id = sorted((first_track_id, second_track_id))
    return NormalizedStreamingTrackPair(
        lower_track_id=lower_track_id,
        higher_track_id=higher_track_id,
    )


streaming_relationships_table = Table(
    "streaming_relationships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lower_track_id", Integer, nullable=False),
    Column("higher_track_id", Integer, nullable=False),
    Column("relationship_type", String, nullable=False),
    Column(
        "accepted_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    CheckConstraint(
        "lower_track_id < higher_track_id",
        name="ck_streaming_relationships_normalized_pair",
    ),
    CheckConstraint(
        "relationship_type IN ('equivalent', 'related')",
        name="ck_streaming_relationships_relationship_type",
    ),
    UniqueConstraint(
        "lower_track_id",
        "higher_track_id",
        name="uq_streaming_relationships_pair",
    ),
    Index("ix_streaming_relationships_lower_track_id", "lower_track_id"),
    Index("ix_streaming_relationships_higher_track_id", "higher_track_id"),
)

streaming_relationship_suggestions_table = Table(
    "streaming_relationship_suggestions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lower_track_id", Integer, nullable=False),
    Column("higher_track_id", Integer, nullable=False),
    Column("relationship_type", String, nullable=False),
    Column("match_method", String, nullable=False),
    Column("score", Float, nullable=False),
    Column("confidence", String, nullable=False),
    Column("status", String, nullable=False),
    Column("accepted_relationship_id", Integer, nullable=True),
    Column("accepted_at", DateTime(timezone=True), nullable=True),
    Column("rejected_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    CheckConstraint(
        "lower_track_id < higher_track_id",
        name="ck_streaming_relationship_suggestions_normalized_pair",
    ),
    CheckConstraint(
        "relationship_type IN ('equivalent', 'related')",
        name="ck_streaming_relationship_suggestions_relationship_type",
    ),
    CheckConstraint(
        "confidence IN ('high', 'medium', 'low')",
        name="ck_streaming_relationship_suggestions_confidence",
    ),
    CheckConstraint(
        "status IN ('pending', 'accepted', 'rejected')",
        name="ck_streaming_relationship_suggestions_status",
    ),
    UniqueConstraint(
        "lower_track_id",
        "higher_track_id",
        name="uq_streaming_relationship_suggestions_pair",
    ),
    Index("ix_streaming_relationship_suggestions_status", "status"),
    Index("ix_streaming_relationship_suggestions_lower_track_id", "lower_track_id"),
    Index("ix_streaming_relationship_suggestions_higher_track_id", "higher_track_id"),
)
