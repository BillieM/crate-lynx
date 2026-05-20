from __future__ import annotations

from collections.abc import Callable
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine, get_engine
from app.m3u.jobs import M3uRegenerationJobEnqueuer
from app.relationships.schemas import (
    AcceptStreamingRelationshipSuggestionRequest,
    AcceptStreamingRelationshipSuggestionResponse,
    GenerateStreamingRelationshipSuggestionsResponse,
    RejectStreamingRelationshipSuggestionResponse,
    StreamingRelationshipConflictResponse,
    StreamingRelationshipLocalLinkResponse,
    StreamingRelationshipSuggestionListResponse,
    StreamingRelationshipSuggestionResponse,
    StreamingRelationshipTrackResponse,
)
from app.relationships.store import (
    InvalidWinningFinalLinkError,
    StaleStreamingRelationshipSuggestionError,
    StreamingRelationshipAcceptanceConflictError,
    StreamingRelationshipConflictContext,
    StreamingRelationshipLocalLinkContext,
    StreamingRelationshipSuggestionNotFoundError,
    StreamingRelationshipSuggestionRecord,
    StreamingRelationshipSuggestionStore,
    StreamingRelationshipTrackRecord,
)


logger = logging.getLogger(__name__)


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

    def _m3u_redis_url(playlist_ids: tuple[int, ...]) -> str | None:
        if not playlist_ids:
            return None

        redis_url = (
            require_redis_url()
            if require_redis_url is not None
            else os.environ.get("REDIS_URL")
        )
        if not redis_url:
            logger.warning(
                "REDIS_URL is not configured; skipping M3U regeneration for "
                "relationship playlist_ids=%s",
                playlist_ids,
            )
            return None

        return redis_url

    def _enqueue_m3u_regeneration(
        playlist_ids: tuple[int, ...],
        redis_url: str | None,
    ) -> None:
        if not playlist_ids or redis_url is None:
            return

        M3uRegenerationJobEnqueuer(redis_url).enqueue_playlists(playlist_ids)

    @router.get(
        "/streaming/relationships/suggestions",
        response_model=StreamingRelationshipSuggestionListResponse,
    )
    def list_relationship_suggestions(
        engine: Engine = Depends(get_engine),
    ) -> StreamingRelationshipSuggestionListResponse:
        store = StreamingRelationshipSuggestionStore(engine=_engine(engine))
        return StreamingRelationshipSuggestionListResponse(
            suggestions=[
                _suggestion_response(suggestion) for suggestion in store.list_pending()
            ]
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
        return GenerateStreamingRelationshipSuggestionsResponse(
            created_count=store.generate(),
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

        redis_url = _m3u_redis_url(result.affected_playlist_ids)
        _enqueue_m3u_regeneration(result.affected_playlist_ids, redis_url)

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

    return router


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
