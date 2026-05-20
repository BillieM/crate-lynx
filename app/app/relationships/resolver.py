from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.core.tables import final_links_view, streaming_relationships_view
from app.relationships.models import STREAMING_RELATIONSHIP_TYPE_EQUIVALENT


RESOLUTION_SOURCE_DIRECT = "direct"
RESOLUTION_SOURCE_EQUIVALENT = "equivalent"

type ResolutionSource = Literal["direct", "equivalent"]


@dataclass(frozen=True, slots=True)
class RelationshipFinalLink:
    id: int
    local_track_id: int
    streaming_track_id: int
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedStreamingTrackLink:
    streaming_track_id: int
    final_link_id: int
    local_track_id: int
    source_streaming_track_id: int
    resolution_source: ResolutionSource


@dataclass(frozen=True, slots=True)
class EquivalentAcceptanceConflict:
    first_track_id: int
    second_track_id: int
    first_group_track_ids: tuple[int, ...]
    second_group_track_ids: tuple[int, ...]
    final_links: tuple[RelationshipFinalLink, ...]
    local_track_ids: tuple[int, ...]


class StreamingRelationshipResolver:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._equivalent_adjacency_by_track: dict[int, tuple[int, ...]] | None = None
        self._equivalent_group_by_track: dict[int, tuple[int, ...]] = {}
        self._final_links_by_streaming_track_id: (
            dict[int, tuple[RelationshipFinalLink, ...]] | None
        ) = None

    def resolve(self, streaming_track_id: int) -> ResolvedStreamingTrackLink | None:
        direct_link = self._first_final_link_for_track(streaming_track_id)
        if direct_link is not None:
            return _resolved_link(
                streaming_track_id=streaming_track_id,
                final_link=direct_link,
                resolution_source=RESOLUTION_SOURCE_DIRECT,
            )

        group_track_ids = self.equivalent_group_track_ids(streaming_track_id)
        group_final_links = self._final_links_for_tracks(group_track_ids)
        local_track_ids = {link.local_track_id for link in group_final_links}
        if len(local_track_ids) != 1:
            return None

        return _resolved_link(
            streaming_track_id=streaming_track_id,
            final_link=group_final_links[0],
            resolution_source=RESOLUTION_SOURCE_EQUIVALENT,
        )

    def equivalent_group_track_ids(self, streaming_track_id: int) -> tuple[int, ...]:
        cached_group = self._equivalent_group_by_track.get(streaming_track_id)
        if cached_group is not None:
            return cached_group

        adjacency = self._equivalent_adjacency()
        visited_track_ids = {streaming_track_id}
        pending_track_ids = [streaming_track_id]

        while pending_track_ids:
            track_id = pending_track_ids.pop()
            for adjacent_track_id in adjacency.get(track_id, ()):
                if adjacent_track_id in visited_track_ids:
                    continue
                visited_track_ids.add(adjacent_track_id)
                pending_track_ids.append(adjacent_track_id)

        group_track_ids = tuple(sorted(visited_track_ids))
        for track_id in group_track_ids:
            self._equivalent_group_by_track[track_id] = group_track_ids
        return group_track_ids

    def detect_equivalent_acceptance_conflict(
        self,
        first_track_id: int,
        second_track_id: int,
    ) -> EquivalentAcceptanceConflict | None:
        first_group_track_ids = self.equivalent_group_track_ids(first_track_id)
        second_group_track_ids = self.equivalent_group_track_ids(second_track_id)
        merged_group_track_ids = tuple(
            sorted({*first_group_track_ids, *second_group_track_ids})
        )
        final_links = self._final_links_for_tracks(merged_group_track_ids)
        local_track_ids = tuple(sorted({link.local_track_id for link in final_links}))
        if len(local_track_ids) <= 1:
            return None

        return EquivalentAcceptanceConflict(
            first_track_id=first_track_id,
            second_track_id=second_track_id,
            first_group_track_ids=first_group_track_ids,
            second_group_track_ids=second_group_track_ids,
            final_links=final_links,
            local_track_ids=local_track_ids,
        )

    def _equivalent_adjacency(self) -> dict[int, tuple[int, ...]]:
        if self._equivalent_adjacency_by_track is not None:
            return self._equivalent_adjacency_by_track

        adjacency: defaultdict[int, set[int]] = defaultdict(set)
        rows = (
            self._connection.execute(
                select(
                    streaming_relationships_view.c.lower_track_id,
                    streaming_relationships_view.c.higher_track_id,
                )
                .where(
                    streaming_relationships_view.c.relationship_type
                    == STREAMING_RELATIONSHIP_TYPE_EQUIVALENT
                )
                .order_by(
                    streaming_relationships_view.c.lower_track_id.asc(),
                    streaming_relationships_view.c.higher_track_id.asc(),
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            lower_track_id = int(row["lower_track_id"])
            higher_track_id = int(row["higher_track_id"])
            adjacency[lower_track_id].add(higher_track_id)
            adjacency[higher_track_id].add(lower_track_id)

        self._equivalent_adjacency_by_track = {
            track_id: tuple(sorted(adjacent_track_ids))
            for track_id, adjacent_track_ids in adjacency.items()
        }
        return self._equivalent_adjacency_by_track

    def _first_final_link_for_track(
        self,
        streaming_track_id: int,
    ) -> RelationshipFinalLink | None:
        return next(
            iter(self._final_links_by_track().get(streaming_track_id, ())),
            None,
        )

    def _final_links_for_tracks(
        self,
        streaming_track_ids: Iterable[int],
    ) -> tuple[RelationshipFinalLink, ...]:
        final_links_by_track = self._final_links_by_track()
        return tuple(
            link
            for streaming_track_id in sorted(set(streaming_track_ids))
            for link in final_links_by_track.get(streaming_track_id, ())
        )

    def _final_links_by_track(self) -> dict[int, tuple[RelationshipFinalLink, ...]]:
        if self._final_links_by_streaming_track_id is not None:
            return self._final_links_by_streaming_track_id

        links_by_track: defaultdict[int, list[RelationshipFinalLink]] = defaultdict(
            list
        )
        rows = (
            self._connection.execute(
                select(
                    final_links_view.c.id,
                    final_links_view.c.local_track_id,
                    final_links_view.c.streaming_track_id,
                    final_links_view.c.approved_at,
                ).order_by(final_links_view.c.id.asc())
            )
            .mappings()
            .all()
        )
        for row in rows:
            streaming_track_id = int(row["streaming_track_id"])
            links_by_track[streaming_track_id].append(
                RelationshipFinalLink(
                    id=int(row["id"]),
                    local_track_id=int(row["local_track_id"]),
                    streaming_track_id=streaming_track_id,
                    approved_at=row["approved_at"],
                )
            )

        self._final_links_by_streaming_track_id = {
            streaming_track_id: tuple(final_links)
            for streaming_track_id, final_links in links_by_track.items()
        }
        return self._final_links_by_streaming_track_id


def _resolved_link(
    *,
    streaming_track_id: int,
    final_link: RelationshipFinalLink,
    resolution_source: ResolutionSource,
) -> ResolvedStreamingTrackLink:
    return ResolvedStreamingTrackLink(
        streaming_track_id=streaming_track_id,
        final_link_id=final_link.id,
        local_track_id=final_link.local_track_id,
        source_streaming_track_id=final_link.streaming_track_id,
        resolution_source=resolution_source,
    )
