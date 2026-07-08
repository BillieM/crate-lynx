from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.engine import Engine

from app.core.db import get_engine
from app.ingestion.failures import failed_ingestion_attempts_table
from app.ingestion.pipeline import SUPPORTED_AUDIO_EXTENSIONS
from app.library.store import LibraryStore
from app.links.store import final_links_table
from app.local_tracks.store import local_tracks_table
from app.matching.pipeline import SUGGESTED_LINK_STATUS_PENDING, suggested_links_table
from app.relationships.store import StreamingRelationshipSuggestionStore
from app.shell.schemas import ShellCountsResponse, ShellSummaryResponse
from app.sonic.schemas import PlaylistGenerationRunResponse
from app.sonic.store import SonicStore
from app.soulseek.store import SoulseekStore
from app.streaming.models import PLAYLIST_SYNC_MODE_FULL, streaming_tracks_table
from app.streaming.schemas import StreamingPlaylistResponse
from app.streaming.store import StreamingAccountStore


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/shell/summary", response_model=ShellSummaryResponse)
    def get_shell_summary(engine: Engine = Depends(get_engine)) -> ShellSummaryResponse:
        return ShellSummaryResponse(
            counts=ShellCountsResponse(
                library_track_total=LibraryStore(engine=engine).compute_stats().total,
                link_proposal_count=_count_link_proposals(engine),
                relationship_suggestion_count=StreamingRelationshipSuggestionStore(
                    engine=engine
                ).count_pending(),
                soulseek_unlinked_count=SoulseekStore(
                    engine=engine
                ).count_unlinked_queue_items(),
                unidentified_active_count=_count_active_unidentified(engine),
            ),
            generated_runs=[
                _generation_run_response(run)
                for run in SonicStore(engine=engine).list_generation_runs()
            ],
            playlists=[
                _streaming_playlist_response(playlist)
                for playlist in StreamingAccountStore(engine=engine).list_playlists(
                    sync_mode=PLAYLIST_SYNC_MODE_FULL
                )
            ],
        )

    return router


def _count_link_proposals(engine: Engine) -> int:
    base_from = (
        suggested_links_table.join(
            local_tracks_table,
            local_tracks_table.c.id == suggested_links_table.c.local_track_id,
        )
        .join(
            streaming_tracks_table,
            streaming_tracks_table.c.id == suggested_links_table.c.streaming_track_id,
        )
        .outerjoin(
            final_links_table,
            final_links_table.c.local_track_id
            == suggested_links_table.c.local_track_id,
        )
    )
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count())
                .select_from(base_from)
                .where(
                    suggested_links_table.c.status == SUGGESTED_LINK_STATUS_PENDING,
                    final_links_table.c.id.is_(None),
                )
            ).scalar_one()
        )


def _count_active_unidentified(engine: Engine) -> int:
    supported_audio_clause = or_(
        *[
            failed_ingestion_attempts_table.c.filename.ilike(f"%{extension}")
            for extension in SUPPORTED_AUDIO_EXTENSIONS
        ]
    )
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count())
                .select_from(failed_ingestion_attempts_table)
                .where(
                    failed_ingestion_attempts_table.c.ignored_at.is_(None),
                    supported_audio_clause,
                )
            ).scalar_one()
        )


def _streaming_playlist_response(playlist: object) -> StreamingPlaylistResponse:
    return StreamingPlaylistResponse(
        id=playlist.id,
        account_id=playlist.account_id,
        provider_playlist_id=playlist.provider_playlist_id,
        title=playlist.title,
        sync_mode=playlist.sync_mode,
        provider_track_count=playlist.provider_track_count,
        imported_track_count=playlist.imported_track_count,
        metadata_synced_at=_optional_isoformat(playlist.metadata_synced_at),
        tracks_synced_at=_optional_isoformat(playlist.tracks_synced_at),
        last_sync_error=playlist.last_sync_error,
        last_sync_error_at=_optional_isoformat(playlist.last_sync_error_at),
    )


def _generation_run_response(run: object) -> PlaylistGenerationRunResponse:
    return PlaylistGenerationRunResponse(
        id=run.id,
        generation_number=run.generation_number,
        status=run.status,
        source_filter=run.source_filter_json,
        generation_config=run.generation_config_json,
        playlist_count=run.playlist_count,
        track_count=run.track_count,
        error_detail=run.error_detail,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _optional_isoformat(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
