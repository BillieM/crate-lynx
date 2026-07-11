from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.engine import Engine

from app.core.db import create_database_engine, get_engine
from app.local_dedupe.models import LocalDedupeDecisionRecord
from app.local_dedupe.schemas import (
    LocalDedupeDecisionResponse,
    LocalDedupeGroupResponse,
    LocalDedupeQueueResponse,
    LocalDedupeResolveResponse,
    LocalDedupeTrackResponse,
    ResolveLocalDedupeGroupRequest,
)
from app.local_dedupe.store import (
    LocalDedupeFileNotFoundError,
    LocalDedupeGroupNotFoundError,
    LocalDedupeInvalidKeeperError,
    LocalDedupeStore,
    LocalDedupeUnsafePathError,
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

    @router.get("/local-dedupe/queue", response_model=LocalDedupeQueueResponse)
    def list_local_dedupe_queue(
        engine: Engine = Depends(get_engine),
    ) -> LocalDedupeQueueResponse:
        groups = LocalDedupeStore(engine=_engine(engine)).list_groups()
        return LocalDedupeQueueResponse(
            groups=[_group_response(group) for group in groups],
            total_count=len(groups),
        )

    @router.post(
        "/local-dedupe/groups/{group_key}/resolve",
        response_model=LocalDedupeResolveResponse,
    )
    def resolve_local_dedupe_group(
        group_key: str,
        payload: ResolveLocalDedupeGroupRequest,
        engine: Engine = Depends(get_engine),
    ) -> LocalDedupeResolveResponse:
        try:
            result = LocalDedupeStore(engine=_engine(engine)).resolve_group(
                group_key=group_key,
                keeper_local_track_id=payload.keeper_local_track_id,
            )
        except LocalDedupeGroupNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Dedupe group not found"
            ) from exc
        except LocalDedupeInvalidKeeperError as exc:
            raise HTTPException(
                status_code=409,
                detail="Keeper must be a member of the current dedupe group",
            ) from exc
        except LocalDedupeFileNotFoundError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Local file is missing: {exc}",
            ) from exc
        except LocalDedupeUnsafePathError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unsafe local file path: {exc}",
            ) from exc

        return LocalDedupeResolveResponse(
            affected_playlist_ids=list(result.affected_playlist_ids),
            decision=_decision_response(result.decision),
        )

    @router.post(
        "/local-dedupe/groups/{group_key}/dismiss",
        response_model=LocalDedupeDecisionResponse,
    )
    def dismiss_local_dedupe_group(
        group_key: str,
        engine: Engine = Depends(get_engine),
    ) -> LocalDedupeDecisionResponse:
        try:
            decision = LocalDedupeStore(engine=_engine(engine)).dismiss_group(group_key)
        except LocalDedupeGroupNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Dedupe group not found"
            ) from exc
        return _decision_response(decision)

    return router


def _group_response(group) -> LocalDedupeGroupResponse:
    return LocalDedupeGroupResponse(
        group_key=group.group_key,
        source=group.source,
        match_score=group.match_score,
        tracks=[
            LocalDedupeTrackResponse(
                id=track.id,
                album=track.album,
                artist=track.artist,
                beets_id=track.beets_id,
                bitdepth=track.bitdepth,
                bitrate=track.bitrate,
                duration_ms=track.duration_ms,
                file_path=track.file_path,
                final_link_id=track.final_link_id,
                fingerprint=track.fingerprint,
                format=track.format,
                isrc=track.isrc,
                library_root_rel_path=track.library_root_rel_path,
                link_status=track.link_status,
                samplerate=track.samplerate,
                title=track.title,
            )
            for track in group.tracks
        ],
    )


def _decision_response(
    decision: LocalDedupeDecisionRecord,
) -> LocalDedupeDecisionResponse:
    return LocalDedupeDecisionResponse(
        action=decision.action,
        created_at=decision.created_at,
        group_key=decision.group_key,
        id=decision.id,
        keeper_local_track_id=decision.keeper_local_track_id,
        match_score=decision.match_score,
        quarantine_paths=[
            str(value) for value in (decision.quarantine_paths_json or [])
        ],
        quarantined_local_track_ids=[
            int(value) for value in (decision.quarantined_track_ids_json or [])
        ],
        source=decision.source,
        track_ids=[int(value) for value in (decision.track_ids_json or [])],
    )
