from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.local_tracks.store import local_tracks_table
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_PENDING,
    SUGGESTED_LINK_STATUS_REJECTED,
    suggested_links_table,
)
from app.relationships.resolver import StreamingRelationshipResolver
from app.streaming.models import streaming_tracks_table


metadata = MetaData()

final_links_table = Table(
    "final_links",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("local_track_id", Integer, nullable=False, unique=True),
    Column("streaming_track_id", Integer, nullable=False, unique=True),
    Column(
        "approved_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)


class FinalLinkMutationError(Exception):
    """Base class for expected final-link mutation failures."""


class FinalLinkNotFoundError(FinalLinkMutationError):
    pass


class ProposalNotFoundError(FinalLinkMutationError):
    pass


class StaleProposalError(FinalLinkMutationError):
    pass


class FinalLinkConflictError(FinalLinkMutationError):
    def __init__(self, reason: str, detail: Any = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class FinalLinkMutationResult:
    final_link_id: int
    local_track_id: int
    streaming_track_id: int
    approved_at: datetime
    replaced_final_link_id: int | None = None
    detached_final_link_ids: tuple[int, ...] = ()
    affected_streaming_track_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class FinalLinkRemovalResult:
    final_link_id: int
    local_track_id: int
    streaming_track_id: int
    rejected_suggestion_id: int
    rejected_at: datetime


@dataclass(frozen=True, slots=True)
class ProposalRejectionResult:
    proposal_id: int
    streaming_track_id: int
    rejected_at: datetime


class FinalLinkMutationService:
    """Own all operator final-link transitions inside an existing transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def approve_proposal(self, proposal_id: int) -> FinalLinkMutationResult:
        proposal = (
            self._connection.execute(
                select(
                    suggested_links_table.c.id,
                    suggested_links_table.c.local_track_id,
                    suggested_links_table.c.streaming_track_id,
                    suggested_links_table.c.status,
                )
                .where(suggested_links_table.c.id == proposal_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if proposal is None:
            raise ProposalNotFoundError
        if proposal["status"] != SUGGESTED_LINK_STATUS_PENDING:
            raise StaleProposalError

        rejected_pair = self._connection.execute(
            select(suggested_links_table.c.id)
            .where(
                suggested_links_table.c.local_track_id == proposal["local_track_id"],
                suggested_links_table.c.streaming_track_id
                == proposal["streaming_track_id"],
                suggested_links_table.c.status == SUGGESTED_LINK_STATUS_REJECTED,
            )
            .limit(1)
        ).scalar_one_or_none()
        if rejected_pair is not None:
            raise FinalLinkConflictError("rejected_pair")

        return self.create(
            local_track_id=int(proposal["local_track_id"]),
            streaming_track_id=int(proposal["streaming_track_id"]),
            proposal_id=proposal_id,
        )

    def reject_proposal(self, proposal_id: int) -> ProposalRejectionResult:
        proposal = (
            self._connection.execute(
                select(
                    suggested_links_table.c.id,
                    suggested_links_table.c.streaming_track_id,
                    suggested_links_table.c.status,
                )
                .where(suggested_links_table.c.id == proposal_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if proposal is None:
            raise ProposalNotFoundError
        if proposal["status"] != SUGGESTED_LINK_STATUS_PENDING:
            raise StaleProposalError

        rejected_at = datetime.now(UTC)
        self._connection.execute(
            update(suggested_links_table)
            .where(
                suggested_links_table.c.id == proposal_id,
                suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
            )
            .values(
                status=SUGGESTED_LINK_STATUS_REJECTED,
                rejected_at=rejected_at,
            )
        )
        return ProposalRejectionResult(
            proposal_id=proposal_id,
            streaming_track_id=int(proposal["streaming_track_id"]),
            rejected_at=rejected_at,
        )

    def create(
        self,
        *,
        local_track_id: int,
        streaming_track_id: int,
        replace_final_link_id: int | None = None,
        detach_conflicting_final_link_ids: tuple[int, ...] = (),
        match_method: str | None = None,
        proposal_id: int | None = None,
    ) -> FinalLinkMutationResult:
        detach_ids = tuple(sorted(set(detach_conflicting_final_link_ids)))
        self._lock_local_track(local_track_id)

        resolver = StreamingRelationshipResolver(self._connection)
        target_group_ids = resolver.equivalent_group_track_ids(streaming_track_id)
        if streaming_track_id not in target_group_ids:
            target_group_ids = tuple(sorted((*target_group_ids, streaming_track_id)))
        self._lock_streaming_tracks(target_group_ids)

        existing_local_link = self._final_link_for_local_track(local_track_id)
        existing_group_ids: tuple[int, ...] = ()
        if existing_local_link is not None:
            existing_group_ids = resolver.equivalent_group_track_ids(
                int(existing_local_link["streaming_track_id"])
            )
            self._lock_streaming_tracks(existing_group_ids)

        if existing_local_link is not None:
            is_same_target = (
                int(existing_local_link["streaming_track_id"]) == streaming_track_id
            )
            if (
                replace_final_link_id is not None
                and replace_final_link_id != int(existing_local_link["id"])
            ) or (not is_same_target and replace_final_link_id is None):
                raise FinalLinkConflictError(
                    "local_track_already_linked",
                    {
                        "final_link_id": int(existing_local_link["id"]),
                        "streaming_track_id": int(
                            existing_local_link["streaming_track_id"]
                        ),
                    },
                )
        elif replace_final_link_id is not None:
            raise FinalLinkConflictError("replace_final_link_mismatch")

        conflicting_links = self._conflicting_group_final_links(
            target_group_ids,
            local_track_id=local_track_id,
            replacing_final_link_id=replace_final_link_id,
        )
        conflict_ids = {int(row["id"]) for row in conflicting_links}
        unknown_detach_ids = set(detach_ids) - conflict_ids
        if unknown_detach_ids:
            raise FinalLinkConflictError(
                "invalid_detach_conflicts",
                {"final_link_ids": sorted(unknown_detach_ids)},
            )
        missing_detach_ids = conflict_ids - set(detach_ids)
        if missing_detach_ids:
            raise FinalLinkConflictError(
                "streaming_group_already_linked",
                {
                    "conflicting_final_links": [
                        {
                            "final_link_id": int(row["id"]),
                            "local_track_id": int(row["local_track_id"]),
                            "streaming_track_id": int(row["streaming_track_id"]),
                        }
                        for row in conflicting_links
                        if int(row["id"]) in missing_detach_ids
                    ]
                },
            )

        if (
            existing_local_link is not None
            and int(existing_local_link["streaming_track_id"]) == streaming_track_id
            and not detach_ids
        ):
            if proposal_id is not None:
                self._approve_proposal_row(proposal_id, local_track_id)
            return _result_from_row(
                existing_local_link,
                affected_streaming_track_ids=target_group_ids,
            )

        replaced_final_link_id = (
            int(existing_local_link["id"]) if existing_local_link is not None else None
        )
        removed_ids = tuple(
            sorted(
                {
                    *detach_ids,
                    *(
                        (replaced_final_link_id,)
                        if replaced_final_link_id is not None
                        else ()
                    ),
                }
            )
        )
        detach_final_links(self._connection, removed_ids)

        try:
            result = self._connection.execute(
                insert(final_links_table).values(
                    local_track_id=local_track_id,
                    streaming_track_id=streaming_track_id,
                )
            )
        except IntegrityError as exc:
            raise FinalLinkConflictError("final_link_conflict") from exc
        final_link_id = result.inserted_primary_key[0]
        if not isinstance(final_link_id, int):
            raise ValueError("Failed to persist final link")

        approved_at = self._connection.execute(
            select(final_links_table.c.approved_at).where(
                final_links_table.c.id == final_link_id
            )
        ).scalar_one()
        if proposal_id is not None:
            self._approve_proposal_row(proposal_id, local_track_id)
        elif match_method is not None:
            self._connection.execute(
                insert(suggested_links_table).values(
                    local_track_id=local_track_id,
                    streaming_track_id=streaming_track_id,
                    match_method=match_method,
                    score=1.0,
                    status=SUGGESTED_LINK_STATUS_APPROVED,
                )
            )
            self._clear_pending_for_local_track(local_track_id)

        return FinalLinkMutationResult(
            final_link_id=final_link_id,
            local_track_id=local_track_id,
            streaming_track_id=streaming_track_id,
            approved_at=approved_at,
            replaced_final_link_id=replaced_final_link_id,
            detached_final_link_ids=detach_ids,
            affected_streaming_track_ids=tuple(
                sorted({*target_group_ids, *existing_group_ids})
            ),
        )

    def unlink(self, final_link_id: int) -> FinalLinkRemovalResult:
        final_link = (
            self._connection.execute(
                select(
                    final_links_table.c.id,
                    final_links_table.c.local_track_id,
                    final_links_table.c.streaming_track_id,
                )
                .where(final_links_table.c.id == final_link_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if final_link is None:
            raise FinalLinkNotFoundError

        self._lock_local_track(int(final_link["local_track_id"]))
        resolver = StreamingRelationshipResolver(self._connection)
        self._lock_streaming_tracks(
            resolver.equivalent_group_track_ids(int(final_link["streaming_track_id"]))
        )
        detach_final_links(self._connection, (final_link_id,))

        rejected_at = datetime.now(UTC)
        rejected_suggestion = self._connection.execute(
            insert(suggested_links_table).values(
                local_track_id=final_link["local_track_id"],
                streaming_track_id=final_link["streaming_track_id"],
                match_method="manual_break",
                score=0.0,
                status=SUGGESTED_LINK_STATUS_REJECTED,
                rejected_at=rejected_at,
            )
        )
        rejected_suggestion_id = rejected_suggestion.inserted_primary_key[0]
        if not isinstance(rejected_suggestion_id, int):
            raise ValueError("Failed to persist rejected suggestion")
        return FinalLinkRemovalResult(
            final_link_id=final_link_id,
            local_track_id=int(final_link["local_track_id"]),
            streaming_track_id=int(final_link["streaming_track_id"]),
            rejected_suggestion_id=rejected_suggestion_id,
            rejected_at=rejected_at,
        )

    def _lock_local_track(self, local_track_id: int) -> None:
        row_id = self._connection.execute(
            select(local_tracks_table.c.id)
            .where(local_tracks_table.c.id == local_track_id)
            .with_for_update()
        ).scalar_one_or_none()
        if row_id is None:
            raise FinalLinkConflictError("local_track_not_found")

    def _lock_streaming_tracks(self, streaming_track_ids: tuple[int, ...]) -> None:
        locked_ids = tuple(
            self._connection.execute(
                select(streaming_tracks_table.c.id)
                .where(streaming_tracks_table.c.id.in_(streaming_track_ids))
                .order_by(streaming_tracks_table.c.id.asc())
                .with_for_update()
            ).scalars()
        )
        if set(locked_ids) != set(streaming_track_ids):
            raise FinalLinkConflictError("streaming_track_not_found")

    def _final_link_for_local_track(self, local_track_id: int):
        return (
            self._connection.execute(
                select(
                    final_links_table.c.id,
                    final_links_table.c.local_track_id,
                    final_links_table.c.streaming_track_id,
                    final_links_table.c.approved_at,
                )
                .where(final_links_table.c.local_track_id == local_track_id)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )

    def _conflicting_group_final_links(
        self,
        streaming_track_ids: tuple[int, ...],
        *,
        local_track_id: int,
        replacing_final_link_id: int | None,
    ):
        query = (
            select(
                final_links_table.c.id,
                final_links_table.c.local_track_id,
                final_links_table.c.streaming_track_id,
            )
            .where(
                final_links_table.c.streaming_track_id.in_(streaming_track_ids),
                final_links_table.c.local_track_id != local_track_id,
            )
            .order_by(final_links_table.c.id.asc())
            .with_for_update()
        )
        if replacing_final_link_id is not None:
            query = query.where(final_links_table.c.id != replacing_final_link_id)
        return self._connection.execute(query).mappings().all()

    def _approve_proposal_row(self, proposal_id: int, local_track_id: int) -> None:
        result = self._connection.execute(
            update(suggested_links_table)
            .where(
                suggested_links_table.c.id == proposal_id,
                suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
            )
            .values(status=SUGGESTED_LINK_STATUS_APPROVED)
        )
        if result.rowcount != 1:
            raise StaleProposalError
        self._clear_pending_for_local_track(local_track_id)

    def _clear_pending_for_local_track(self, local_track_id: int) -> None:
        self._connection.execute(
            delete(suggested_links_table).where(
                suggested_links_table.c.local_track_id == local_track_id,
                suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
            )
        )


def detach_final_links(connection: Connection, final_link_ids: tuple[int, ...]) -> None:
    """Delete links while preserving nullable historical references."""
    if not final_link_ids:
        return

    # Imported lazily because Soulseek's store also consumes this module.
    from app.soulseek.models import soulseek_acquisitions_table

    if connection.dialect.has_table(connection, "soulseek_acquisitions"):
        connection.execute(
            update(soulseek_acquisitions_table)
            .where(soulseek_acquisitions_table.c.final_link_id.in_(final_link_ids))
            .values(final_link_id=None)
        )
    connection.execute(
        delete(final_links_table).where(final_links_table.c.id.in_(final_link_ids))
    )


def _result_from_row(
    row,
    *,
    affected_streaming_track_ids: tuple[int, ...],
) -> FinalLinkMutationResult:
    return FinalLinkMutationResult(
        final_link_id=int(row["id"]),
        local_track_id=int(row["local_track_id"]),
        streaming_track_id=int(row["streaming_track_id"]),
        approved_at=row["approved_at"],
        affected_streaming_track_ids=affected_streaming_track_ids,
    )
