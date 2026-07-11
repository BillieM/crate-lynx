from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.engine import Engine

from app.core.cursors import decode_score_id_cursor, encode_score_id_cursor
from app.core.db import create_database_engine, get_engine
from app.relationships.schemas import (
    AcceptStreamingRelationshipSuggestionRequest,
    AcceptStreamingRelationshipSuggestionResponse,
    CreateStreamingRelationshipRequest,
    GenerateStreamingRelationshipSuggestionsResponse,
    RejectStreamingRelationshipSuggestionResponse,
    StreamingRelationshipConflictResponse,
    StreamingRelationshipLocalLinkResponse,
    StreamingRelationshipMutationResponse,
    StreamingRelationshipSuggestionListResponse,
    StreamingRelationshipSuggestionResponse,
    StreamingRelationshipType,
    StreamingRelationshipTrackResponse,
    UpdateStreamingRelationshipRequest,
)
from app.relationships.store import (
    DEFAULT_RELATIONSHIP_SUGGESTION_LIST_LIMIT,
    InvalidWinningFinalLinkError,
    StaleStreamingRelationshipSuggestionError,
    StreamingRelationshipAcceptanceConflictError,
    StreamingRelationshipAlreadyExistsError,
    StreamingRelationshipConflictContext,
    StreamingRelationshipLocalLinkContext,
    StreamingRelationshipNotFoundError,
    StreamingRelationshipStore,
    StreamingRelationshipSuggestionNotFoundError,
    StreamingRelationshipSuggestionRecord,
    StreamingRelationshipSuggestionStore,
    StreamingRelationshipTrackRecord,
)


def create_router(
    *,
    require_redis_url: Callable[[], str] | None = None,
    require_database_url: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter()

    def _engine(engine: object) -> Engine:
        if isinstance(engine, Engine):
            return engine
        return create_database_engine(
            require_database_url() if require_database_url is not None else None
        )

    @router.get(
        "/streaming/relationships/suggestions",
        response_model=StreamingRelationshipSuggestionListResponse,
    )
    def list_relationship_suggestions(
        cursor: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = (
            DEFAULT_RELATIONSHIP_SUGGESTION_LIST_LIMIT
        ),
        relationship_type: Annotated[StreamingRelationshipType | None, Query()] = None,
        engine: Engine = Depends(get_engine),
    ) -> StreamingRelationshipSuggestionListResponse:
        store = StreamingRelationshipSuggestionStore(engine=_engine(engine))
        decoded_cursor = None
        if cursor is not None:
            try:
                decoded_cursor = decode_score_id_cursor(cursor)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        suggestions = store.list_pending(
            cursor=decoded_cursor,
            limit=limit + 1,
            relationship_type=relationship_type,
        )
        page_suggestions = suggestions[:limit]
        next_cursor = (
            encode_score_id_cursor(
                score=page_suggestions[-1].score,
                row_id=page_suggestions[-1].id,
            )
            if len(suggestions) > limit and page_suggestions
            else None
        )
        return StreamingRelationshipSuggestionListResponse(
            suggestions=[
                _suggestion_response(suggestion) for suggestion in page_suggestions
            ],
            total_count=store.count_pending(relationship_type=relationship_type),
            returned_count=len(page_suggestions),
            limit=limit,
            next_cursor=next_cursor,
        )

    @router.post(
        "/streaming/relationships/suggestions/generate",
        status_code=201,
        response_model=GenerateStreamingRelationshipSuggestionsResponse,
    )
    def generate_relationship_suggestions(
        engine: Engine = Depends(get_engine),
    ) -> GenerateStreamingRelationshipSuggestionsResponse:
        store = StreamingRelationshipSuggestionStore(engine=_engine(engine))
        result = store.generate()
        return GenerateStreamingRelationshipSuggestionsResponse(
            created_count=result.created_count,
            pruned_count=result.pruned_count,
        )

    @router.post(
        "/streaming/relationships/suggestions/{suggestion_id}/accept",
        status_code=201,
        response_model=AcceptStreamingRelationshipSuggestionResponse,
    )
    def accept_relationship_suggestion(
        suggestion_id: int,
        request: AcceptStreamingRelationshipSuggestionRequest | None = None,
        engine: Engine = Depends(get_engine),
    ) -> AcceptStreamingRelationshipSuggestionResponse:
        store = StreamingRelationshipSuggestionStore(engine=_engine(engine))
        try:
            result = store.accept(
                suggestion_id,
                relationship_type=(
                    request.relationship_type if request is not None else None
                ),
                winning_final_link_id=(
                    request.winning_final_link_id if request is not None else None
                ),
            )
        except StreamingRelationshipSuggestionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Relationship suggestion not found",
            ) from exc
        except StaleStreamingRelationshipSuggestionError as exc:
            raise HTTPException(
                status_code=409,
                detail="Relationship suggestion is no longer pending",
            ) from exc
        except StreamingRelationshipAcceptanceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidWinningFinalLinkError as exc:
            raise HTTPException(
                status_code=409,
                detail="winning_final_link_id must reference a conflicting final link",
            ) from exc

        return AcceptStreamingRelationshipSuggestionResponse(
            suggestion_id=result.suggestion_id,
            relationship_id=result.relationship_id,
            relationship_type=result.relationship_type,
            status="accepted",
            accepted_at=result.accepted_at.isoformat(),
            detached_final_link_ids=list(result.detached_final_link_ids),
        )

    @router.post(
        "/streaming/relationships/suggestions/{suggestion_id}/reject",
        response_model=RejectStreamingRelationshipSuggestionResponse,
    )
    def reject_relationship_suggestion(
        suggestion_id: int,
        engine: Engine = Depends(get_engine),
    ) -> RejectStreamingRelationshipSuggestionResponse:
        store = StreamingRelationshipSuggestionStore(engine=_engine(engine))
        try:
            result = store.reject(suggestion_id)
        except StreamingRelationshipSuggestionNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Relationship suggestion not found",
            ) from exc
        except StaleStreamingRelationshipSuggestionError as exc:
            raise HTTPException(
                status_code=409,
                detail="Relationship suggestion is no longer pending",
            ) from exc

        return RejectStreamingRelationshipSuggestionResponse(
            suggestion_id=result.suggestion_id,
            status="rejected",
            rejected_at=result.rejected_at.isoformat(),
        )

    @router.post(
        "/streaming/relationships",
        status_code=201,
        response_model=StreamingRelationshipMutationResponse,
    )
    def create_streaming_relationship(
        request: CreateStreamingRelationshipRequest,
        engine: Engine = Depends(get_engine),
    ) -> StreamingRelationshipMutationResponse:
        store = StreamingRelationshipStore(engine=_engine(engine))
        try:
            result = store.create(
                first_track_id=request.first_track_id,
                second_track_id=request.second_track_id,
                relationship_type=request.relationship_type,
                winning_final_link_id=request.winning_final_link_id,
            )
        except StreamingRelationshipNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Streaming relationship tracks not found",
            ) from exc
        except StreamingRelationshipAlreadyExistsError as exc:
            raise HTTPException(
                status_code=409,
                detail="Streaming relationship already exists",
            ) from exc
        except StreamingRelationshipAcceptanceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidWinningFinalLinkError as exc:
            raise HTTPException(
                status_code=409,
                detail="winning_final_link_id must reference a conflicting final link",
            ) from exc

        return _relationship_mutation_response(result, status="created")

    @router.patch(
        "/streaming/relationships/{relationship_id}",
        response_model=StreamingRelationshipMutationResponse,
    )
    def update_streaming_relationship(
        relationship_id: int,
        request: UpdateStreamingRelationshipRequest,
        engine: Engine = Depends(get_engine),
    ) -> StreamingRelationshipMutationResponse:
        store = StreamingRelationshipStore(engine=_engine(engine))
        try:
            result = store.update(
                relationship_id,
                relationship_type=request.relationship_type,
                winning_final_link_id=request.winning_final_link_id,
            )
        except StreamingRelationshipNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Streaming relationship not found",
            ) from exc
        except StreamingRelationshipAcceptanceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidWinningFinalLinkError as exc:
            raise HTTPException(
                status_code=409,
                detail="winning_final_link_id must reference a conflicting final link",
            ) from exc

        return _relationship_mutation_response(result, status="updated")

    @router.delete(
        "/streaming/relationships/{relationship_id}",
        response_model=StreamingRelationshipMutationResponse,
    )
    def delete_streaming_relationship(
        relationship_id: int,
        engine: Engine = Depends(get_engine),
    ) -> StreamingRelationshipMutationResponse:
        store = StreamingRelationshipStore(engine=_engine(engine))
        try:
            result = store.delete(relationship_id)
        except StreamingRelationshipNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Streaming relationship not found",
            ) from exc

        return _relationship_mutation_response(result, status="deleted")

    return router


def _relationship_mutation_response(
    result,
    *,
    status: str,
) -> StreamingRelationshipMutationResponse:
    return StreamingRelationshipMutationResponse(
        relationship_id=result.relationship_id,
        relationship_type=result.relationship_type,
        status=status,
        accepted_at=(
            result.accepted_at.isoformat() if result.accepted_at is not None else None
        ),
        detached_final_link_ids=list(result.detached_final_link_ids),
    )


def _suggestion_response(
    suggestion: StreamingRelationshipSuggestionRecord,
) -> StreamingRelationshipSuggestionResponse:
    return StreamingRelationshipSuggestionResponse(
        id=suggestion.id,
        relationship_type=suggestion.relationship_type,
        match_method=suggestion.match_method,
        score=suggestion.score,
        confidence=suggestion.confidence,
        status=suggestion.status,
        created_at=_isoformat(suggestion.created_at),
        first_track=_track_response(suggestion.first_track),
        second_track=_track_response(suggestion.second_track),
        first_link=_link_response(suggestion.first_link),
        second_link=_link_response(suggestion.second_link),
        conflict_state=suggestion.conflict_state,
        conflict=_conflict_response(suggestion.conflict),
    )


def _track_response(
    track: StreamingRelationshipTrackRecord,
) -> StreamingRelationshipTrackResponse:
    return StreamingRelationshipTrackResponse(
        id=track.id,
        provider_track_id=track.provider_track_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        year=track.year,
        isrc=track.isrc,
        duration_ms=track.duration_ms,
    )


def _link_response(
    link: StreamingRelationshipLocalLinkContext | None,
) -> StreamingRelationshipLocalLinkResponse | None:
    if link is None:
        return None

    return StreamingRelationshipLocalLinkResponse(
        final_link_id=link.final_link_id,
        local_track_id=link.local_track_id,
        local_file_path=link.local_file_path,
        local_title=link.local_title,
        local_artist=link.local_artist,
        local_album=link.local_album,
        streaming_track_id=link.streaming_track_id,
        source_streaming_track_id=link.source_streaming_track_id,
        resolution_source=link.resolution_source,
        approved_at=_isoformat(link.approved_at),
    )


def _conflict_response(
    conflict: StreamingRelationshipConflictContext | None,
) -> StreamingRelationshipConflictResponse | None:
    if conflict is None:
        return None

    return StreamingRelationshipConflictResponse(
        first_group_track_ids=list(conflict.first_group_track_ids),
        second_group_track_ids=list(conflict.second_group_track_ids),
        local_track_ids=list(conflict.local_track_ids),
        final_links=[
            response
            for link in conflict.final_links
            if (response := _link_response(link)) is not None
        ],
    )


def _isoformat(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
