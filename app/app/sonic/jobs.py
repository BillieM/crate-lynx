from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

from redis import Redis
from rq import Queue

from app.sonic.analyzer import build_sonic_analyzer
from app.sonic.generation import generate_playlist_tree
from app.sonic.models import SONIC_ANALYZER_LIBROSA_V1
from app.sonic.store import PlaylistGenerationRunNotFoundError, SonicStore


logger = logging.getLogger(__name__)

DEFAULT_SONIC_QUEUE_NAME = "sonic"
DEFAULT_SONIC_FEATURE_JOB_TIMEOUT = "30m"
DEFAULT_SONIC_GENERATION_JOB_TIMEOUT = "30m"


@dataclass(slots=True)
class SonicJobEnqueuer:
    redis_url: str
    queue_name: str = DEFAULT_SONIC_QUEUE_NAME

    def enqueue_feature_extraction(self, local_track_id: int) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            "app.sonic.jobs.run_sonic_feature_extraction_job",
            local_track_id,
            job_timeout=DEFAULT_SONIC_FEATURE_JOB_TIMEOUT,
        )
        return job.id

    def enqueue_feature_backfill(self, *, limit: int = 100) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            "app.sonic.jobs.run_sonic_feature_backfill_job",
            limit,
            job_timeout=DEFAULT_SONIC_FEATURE_JOB_TIMEOUT,
        )
        return job.id

    def enqueue_generation(self, run_id: int) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            "app.sonic.jobs.run_playlist_generation_job",
            run_id,
            job_timeout=DEFAULT_SONIC_GENERATION_JOB_TIMEOUT,
        )
        return job.id


def run_sonic_feature_extraction_job(local_track_id: int) -> int:
    database_url = _require_database_url()
    store = SonicStore(database_url)
    analyzer = build_sonic_analyzer(SONIC_ANALYZER_LIBROSA_V1)
    store.mark_feature_pending(
        analyzer_key=analyzer.analyzer_key,
        analyzer_version=analyzer.analyzer_version,
        local_track_id=local_track_id,
    )
    try:
        audio_path = _resolve_local_audio_path(store, local_track_id)
        result = analyzer.analyze(audio_path)
        store.persist_feature_success(
            analyzer_key=result.analyzer_key,
            analyzer_version=result.analyzer_version,
            descriptors=result.descriptors,
            local_track_id=local_track_id,
            vector=result.vector,
        )
    except Exception as exc:
        logger.exception(
            "Sonic feature extraction failed local_track_id=%s", local_track_id
        )
        store.persist_feature_failure(
            analyzer_key=analyzer.analyzer_key,
            analyzer_version=analyzer.analyzer_version,
            failure_detail=str(exc),
            local_track_id=local_track_id,
        )
        raise

    return local_track_id


def run_sonic_feature_backfill_job(limit: int = 100) -> list[int]:
    database_url = _require_database_url()
    store = SonicStore(database_url)
    local_track_ids = store.list_missing_feature_track_ids(
        limit=max(1, min(limit, 1000))
    )
    processed_ids = []
    for local_track_id in local_track_ids:
        try:
            run_sonic_feature_extraction_job(local_track_id)
        except Exception:
            logger.warning(
                "Continuing sonic feature backfill after failure local_track_id=%s",
                local_track_id,
                exc_info=True,
            )
        processed_ids.append(local_track_id)
    return processed_ids


def run_playlist_generation_job(run_id: int) -> int:
    database_url = _require_database_url()
    store = SonicStore(database_url)
    run = store.get_generation_run(run_id)
    if run is None:
        raise PlaylistGenerationRunNotFoundError(str(run_id))

    store.mark_generation_run_running(run_id)
    try:
        tracks = store.ready_tracks_for_source(run.source_filter_json)
        drafts = generate_playlist_tree(tracks, run.generation_config_json)
        store.replace_generated_playlists(
            playlists=drafts,
            run_id=run_id,
            track_count=len(tracks),
        )
    except Exception as exc:
        logger.exception("Playlist generation failed run_id=%s", run_id)
        store.mark_generation_run_failed(run_id, str(exc))
        raise

    return run_id


def _resolve_local_audio_path(store: SonicStore, local_track_id: int) -> Path:
    from app.local_tracks.store import LocalTrackStore

    local_store = LocalTrackStore(engine=store._engine)
    file_path = local_store.get_file_path(local_track_id)
    if file_path is None:
        raise FileNotFoundError(f"Local track not found: {local_track_id}")

    library_root = Path(os.environ.get("LIBRARY_ROOT", "/nas/media/music")).resolve()
    audio_path = (library_root / file_path).resolve()
    audio_path.relative_to(library_root)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Local audio file not found: {audio_path}")
    return audio_path


def _require_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for sonic jobs")
    return database_url
