from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path

from redis import Redis
from rq import Queue
from rq.job import Dependency, Job
from rq.registry import FailedJobRegistry

from app.sonic.analyzer import build_sonic_analyzer
from app.sonic.generation import generate_playlist_tree
from app.sonic.models import (
    DEFAULT_SONIC_BACKFILL_LIMIT,
    MAX_SONIC_FEATURE_ATTEMPTS,
    MAX_SONIC_BACKFILL_LIMIT,
    SONIC_ANALYZER_LIBROSA_V1,
)
from app.sonic.profiles import resolve_feature_profile_from_config
from app.sonic.store import PlaylistGenerationRunNotFoundError, SonicStore


logger = logging.getLogger(__name__)

DEFAULT_SONIC_QUEUE_NAME = "sonic"
DEFAULT_SONIC_FEATURE_JOB_TIMEOUT = "30m"
DEFAULT_SONIC_GENERATION_JOB_TIMEOUT = "30m"
DEFAULT_SONIC_PENDING_RECLAIM_AFTER = timedelta(hours=1)
SONIC_FEATURE_EXTRACTION_FUNC = "app.sonic.jobs.run_sonic_feature_extraction_job"
SONIC_FEATURE_BACKFILL_FUNC = "app.sonic.jobs.run_sonic_feature_backfill_job"
SONIC_FEATURE_RECONCILIATION_FUNC = (
    "app.sonic.jobs.run_sonic_feature_reconciliation_job"
)
SONIC_PLAYLIST_GENERATION_FUNC = "app.sonic.jobs.run_playlist_generation_job"
MAX_FAILED_JOB_DETAIL_LENGTH = 4000


@dataclass(slots=True)
class SonicJobEnqueuer:
    redis_url: str
    queue_name: str = DEFAULT_SONIC_QUEUE_NAME

    def enqueue_feature_extraction(self, local_track_id: int) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            SONIC_FEATURE_EXTRACTION_FUNC,
            local_track_id,
            job_timeout=DEFAULT_SONIC_FEATURE_JOB_TIMEOUT,
        )
        return job.id

    def enqueue_feature_backfill(
        self, *, limit: int = DEFAULT_SONIC_BACKFILL_LIMIT
    ) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            SONIC_FEATURE_BACKFILL_FUNC,
            limit,
            job_timeout=DEFAULT_SONIC_FEATURE_JOB_TIMEOUT,
        )
        return job.id

    def enqueue_generation(self, run_id: int) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        job = queue.enqueue(
            SONIC_PLAYLIST_GENERATION_FUNC,
            run_id,
            job_timeout=DEFAULT_SONIC_GENERATION_JOB_TIMEOUT,
        )
        return job.id


@dataclass(frozen=True, slots=True)
class SonicFeatureBackfillEnqueueResult:
    job_id: str
    job_ids: list[str]
    claimed_count: int


def run_sonic_feature_extraction_job(
    local_track_id: int,
    attempt_count: int | None = None,
) -> int:
    database_url = _require_database_url()
    store = SonicStore(database_url)
    analyzer = build_sonic_analyzer(SONIC_ANALYZER_LIBROSA_V1)
    if attempt_count is None:
        attempt_count = store.mark_feature_pending(
            analyzer_key=analyzer.analyzer_key,
            analyzer_version=analyzer.analyzer_version,
            local_track_id=local_track_id,
        ).attempt_count
    try:
        audio_path = _resolve_local_audio_path(store, local_track_id)
        result = analyzer.analyze(audio_path)
        persisted = store.persist_feature_success_if_current(
            analyzer_key=result.analyzer_key,
            analyzer_version=result.analyzer_version,
            attempt_count=attempt_count,
            descriptors=result.descriptors,
            local_track_id=local_track_id,
            vector=result.vector,
        )
        if not persisted:
            logger.info(
                "Ignored stale Sonic feature success local_track_id=%s attempt_count=%s",
                local_track_id,
                attempt_count,
            )
    except Exception as exc:
        logger.exception(
            "Sonic feature extraction failed local_track_id=%s", local_track_id
        )
        store.persist_feature_failure_if_current(
            analyzer_key=analyzer.analyzer_key,
            analyzer_version=analyzer.analyzer_version,
            attempt_count=attempt_count,
            failure_detail=str(exc),
            local_track_id=local_track_id,
        )
        raise

    return local_track_id


def run_sonic_feature_backfill_job(
    limit: int = DEFAULT_SONIC_BACKFILL_LIMIT,
) -> list[str]:
    database_url = _require_database_url()
    redis_url = _require_redis_url()
    store = SonicStore(database_url)
    reconcile_failed_sonic_feature_jobs(
        database_url=database_url,
        redis_url=redis_url,
    )
    result = enqueue_sonic_feature_backfill(
        limit=limit,
        redis_url=redis_url,
        store=store,
    )
    return result.job_ids


def enqueue_sonic_feature_backfill(
    *,
    limit: int = DEFAULT_SONIC_BACKFILL_LIMIT,
    redis_url: str,
    store: SonicStore,
) -> SonicFeatureBackfillEnqueueResult:
    analyzer = build_sonic_analyzer(SONIC_ANALYZER_LIBROSA_V1)
    attempts = store.claim_missing_feature_attempts(
        analyzer_key=analyzer.analyzer_key,
        analyzer_version=analyzer.analyzer_version,
        limit=max(1, min(limit, MAX_SONIC_BACKFILL_LIMIT)),
        max_attempts=MAX_SONIC_FEATURE_ATTEMPTS,
        pending_stale_before=datetime.now(UTC) - DEFAULT_SONIC_PENDING_RECLAIM_AFTER,
    )
    connection = Redis.from_url(redis_url)
    queue = Queue(DEFAULT_SONIC_QUEUE_NAME, connection=connection)
    enqueued_ids = []
    enqueued_jobs = []
    for attempt in attempts:
        local_track_id = attempt.local_track_id
        try:
            job = queue.enqueue(
                SONIC_FEATURE_EXTRACTION_FUNC,
                local_track_id,
                attempt.attempt_count,
                job_timeout=DEFAULT_SONIC_FEATURE_JOB_TIMEOUT,
            )
        except Exception as exc:
            logger.exception(
                "Sonic feature backfill failed to enqueue extraction local_track_id=%s",
                local_track_id,
            )
            store.persist_feature_failure_if_current(
                analyzer_key=analyzer.analyzer_key,
                analyzer_version=analyzer.analyzer_version,
                attempt_count=attempt.attempt_count,
                failure_detail=f"Failed to enqueue sonic feature extraction job: {exc}",
                local_track_id=local_track_id,
            )
        else:
            enqueued_ids.append(job.id)
            enqueued_jobs.append(job)

    job_id = enqueued_ids[0] if enqueued_ids else ""
    if enqueued_jobs:
        try:
            reconciliation_job = queue.enqueue(
                SONIC_FEATURE_RECONCILIATION_FUNC,
                job_timeout=DEFAULT_SONIC_FEATURE_JOB_TIMEOUT,
                depends_on=Dependency(jobs=enqueued_jobs, allow_failure=True),
            )
            job_id = reconciliation_job.id
        except Exception:
            logger.exception("Sonic feature backfill failed to enqueue reconciliation")
    return SonicFeatureBackfillEnqueueResult(
        job_id=job_id,
        job_ids=enqueued_ids,
        claimed_count=len(attempts),
    )


def run_sonic_feature_reconciliation_job() -> int:
    return reconcile_failed_sonic_feature_jobs()


def reconcile_failed_sonic_feature_jobs(
    *,
    database_url: str | None = None,
    redis_url: str | None = None,
) -> int:
    database_url = database_url or _require_database_url()
    redis_url = redis_url or _require_redis_url()
    connection = Redis.from_url(redis_url)
    failed_registry = FailedJobRegistry(DEFAULT_SONIC_QUEUE_NAME, connection=connection)
    store = SonicStore(database_url)
    analyzer = build_sonic_analyzer(SONIC_ANALYZER_LIBROSA_V1)

    reconciled_count = 0
    for job_id in failed_registry.get_job_ids():
        try:
            job = Job.fetch(job_id, connection=connection)
        except Exception:
            logger.exception("Failed to load failed sonic job job_id=%s", job_id)
            continue

        if job.func_name != SONIC_FEATURE_EXTRACTION_FUNC:
            continue
        if not job.args:
            logger.warning("Failed sonic extraction job has no args job_id=%s", job_id)
            continue

        try:
            local_track_id = int(job.args[0])
        except (TypeError, ValueError):
            logger.warning(
                "Failed sonic extraction job has invalid local_track_id job_id=%s args=%s",
                job_id,
                job.args,
            )
            continue

        if len(job.args) <= 1:
            logger.warning(
                "Skipping unversioned failed sonic extraction job job_id=%s args=%s",
                job_id,
                job.args,
            )
            continue
        try:
            attempt_count = int(job.args[1])
        except (TypeError, ValueError):
            logger.warning(
                "Failed sonic extraction job has invalid attempt_count "
                "job_id=%s args=%s",
                job_id,
                job.args,
            )
            continue

        if store.mark_feature_failed_if_pending(
            analyzer_key=analyzer.analyzer_key,
            analyzer_version=analyzer.analyzer_version,
            failure_detail=_failed_job_detail(job),
            local_track_id=local_track_id,
            attempt_count=attempt_count,
        ):
            logger.warning(
                "Reconciled failed sonic extraction job job_id=%s local_track_id=%s",
                job_id,
                local_track_id,
            )
            reconciled_count += 1

    return reconciled_count


def run_playlist_generation_job(run_id: int) -> int:
    database_url = _require_database_url()
    store = SonicStore(database_url)
    run = store.get_generation_run(run_id)
    if run is None:
        raise PlaylistGenerationRunNotFoundError(str(run_id))

    store.mark_generation_run_running(run_id)
    try:
        profile = resolve_feature_profile_from_config(run.generation_config_json)
        preview = store.generation_preview(
            run.source_filter_json,
            analyzer_key=profile.analyzer_key,
            analyzer_version=profile.analyzer_version,
            feature_profile=profile.key,
        )
        tracks = store.ready_tracks_for_source(
            run.source_filter_json,
            analyzer_key=profile.analyzer_key,
            analyzer_version=profile.analyzer_version,
        )
        drafts = generate_playlist_tree(tracks, run.generation_config_json)
        source_summary = {
            "failed_feature_count": preview.failed_feature_count,
            "missing_feature_count": preview.missing_feature_count,
            "pending_feature_count": preview.pending_feature_count,
            "ready_track_count": preview.ready_track_count,
            "skipped_track_count": preview.skipped_track_count,
            "source_track_count": preview.source_track_count,
        }
        for draft in drafts:
            draft["summary"] = {
                **draft["summary"],
                "source_summary": source_summary,
            }
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


def _require_redis_url() -> str:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL must be configured for sonic jobs")
    return redis_url


def _failed_job_detail(job: Job) -> str:
    detail = str(job.exc_info or "Sonic feature extraction job failed").strip()
    if len(detail) > MAX_FAILED_JOB_DETAIL_LENGTH:
        detail = detail[:MAX_FAILED_JOB_DETAIL_LENGTH] + "..."
    return f"RQ sonic extraction job {job.id} failed: {detail}"
