from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
import os
import time
import uuid
from typing import Any

from redis import Redis
from rq import Queue

from app.soulseek.client import SlskdClient
from app.soulseek.config import SlskdConfig, load_slskd_config
from app.soulseek.models import (
    SOULSEEK_QUEUE_NAME,
    SOULSEEK_STATUS_COMPLETED,
    SOULSEEK_STATUS_DOWNLOADING,
    SOULSEEK_STATUS_FAILED,
    SOULSEEK_STATUS_LINK_FAILED,
    SOULSEEK_STATUS_QUEUED,
    StreamingTrackForSoulseek,
)
from app.soulseek.ranking import (
    RankedSoulseekCandidate,
    is_weak_candidate_set,
    merge_ranked_candidates,
    rank_search_responses,
    soulseek_query_variants_for_track,
)
from app.soulseek.store import (
    SoulseekAcquisitionNotFoundError,
    SoulseekCandidateConflictError,
    SoulseekCandidateNotFoundError,
    SoulseekStore,
    validate_candidate_enqueue,
)


logger = logging.getLogger(__name__)

SOULSEEK_SEARCH_JOB = "app.soulseek.jobs.search_missing_track"
SOULSEEK_ENQUEUE_JOB = "app.soulseek.jobs.enqueue_soulseek_candidate"
SOULSEEK_REFRESH_JOB = "app.soulseek.jobs.refresh_soulseek_acquisition"
SOULSEEK_BACKFILL_JOB = "app.soulseek.jobs.backfill_soulseek_auto_links"
SOULSEEK_JOB_TIMEOUT = "10m"
SOULSEEK_SEARCH_LOCK_KEY = "crate-lynx:soulseek:search-lock"
SOULSEEK_SEARCH_LOCK_TTL_SECONDS = 240
SOULSEEK_SEARCH_LOCK_WAIT_SECONDS = 120
SOULSEEK_LEGACY_TRANSFER_ID_PREFIX = "transfer:"


@dataclass(slots=True)
class SoulseekJobEnqueuer:
    redis_url: str
    queue_name: str = SOULSEEK_QUEUE_NAME
    job_timeout: str = SOULSEEK_JOB_TIMEOUT

    def enqueue_search(self, acquisition_id: str) -> str:
        return self._enqueue(SOULSEEK_SEARCH_JOB, acquisition_id)

    def enqueue_candidate(self, candidate_id: str) -> str:
        return self._enqueue(SOULSEEK_ENQUEUE_JOB, candidate_id)

    def enqueue_refresh(self, acquisition_id: str) -> str:
        return self._enqueue(SOULSEEK_REFRESH_JOB, acquisition_id)

    def enqueue_backfill(self) -> str:
        return self._enqueue(SOULSEEK_BACKFILL_JOB)

    def _enqueue(self, job_function: str, job_arg: str | None = None) -> str:
        connection = Redis.from_url(self.redis_url)
        queue = Queue(self.queue_name, connection=connection)
        if job_arg is None:
            job = queue.enqueue(job_function, job_timeout=self.job_timeout)
        else:
            job = queue.enqueue(job_function, job_arg, job_timeout=self.job_timeout)
        return job.id


@dataclass(frozen=True, slots=True)
class SoulseekSearchAttempt:
    search_id: str
    search_text: str
    responses: list[dict[str, Any]]
    raw_file_count: int
    candidates: list[RankedSoulseekCandidate]
    rejection_counts: Counter[str]


def search_missing_track(acquisition_id: str) -> dict[str, object]:
    database_url = _require_database_url()
    redis_url = _require_redis_url()
    store = SoulseekStore(database_url)
    acquisition = store.get_acquisition(acquisition_id)
    if acquisition is None:
        raise SoulseekAcquisitionNotFoundError(acquisition_id)
    track = store.get_streaming_track(acquisition.streaming_track_id)
    if track is None:
        store.mark_failed(acquisition_id, "Streaming track not found")
        raise SoulseekAcquisitionNotFoundError(
            f"Streaming track {acquisition.streaming_track_id} not found"
        )

    config = load_slskd_config()
    client = SlskdClient(config)
    try:
        with _search_lock(redis_url):
            attempts: list[SoulseekSearchAttempt] = []
            candidates: list[RankedSoulseekCandidate] = []
            for search_text in soulseek_query_variants_for_track(track):
                attempt = _run_search_attempt(
                    acquisition_id=acquisition_id,
                    client=client,
                    config=config,
                    search_id=str(uuid.uuid4()),
                    search_text=search_text,
                    track=track,
                )
                attempts.append(attempt)
                candidates = merge_ranked_candidates(candidates, attempt.candidates)
                if not is_weak_candidate_set(candidates):
                    break

            search_id = attempts[0].search_id
            search_text = attempts[0].search_text
            fallback_attempts = attempts[1:]
            fallback_search_id = (
                ", ".join(attempt.search_id for attempt in fallback_attempts) or None
            )
            fallback_search_text = (
                " | ".join(attempt.search_text for attempt in fallback_attempts) or None
            )

        updated = store.persist_search_results(
            acquisition_id=acquisition_id,
            candidates=candidates,
            fallback_search_id=fallback_search_id,
            fallback_search_text=fallback_search_text,
            search_id=search_id,
            search_text=search_text,
        )
        return {
            "acquisition_id": updated.id,
            "candidate_count": updated.candidate_count,
            "status": updated.status,
        }
    except Exception as exc:
        logger.exception("Soulseek search failed acquisition_id=%s", acquisition_id)
        store.mark_failed(acquisition_id, str(exc))
        raise


def _run_search_attempt(
    *,
    acquisition_id: str,
    client: SlskdClient,
    config: SlskdConfig,
    search_id: str,
    search_text: str,
    track: StreamingTrackForSoulseek,
) -> SoulseekSearchAttempt:
    client.start_search(search_id=search_id, search_text=search_text)
    deadline = time.monotonic() + max(0.0, config.search_poll_timeout_seconds)
    responses: list[dict[str, Any]] = []
    raw_file_count = 0
    candidates: list[RankedSoulseekCandidate] = []
    rejection_counts: Counter[str] = Counter()

    try:
        while True:
            responses = client.search_responses(search_id)
            raw_file_count = _raw_search_file_count(responses)
            rejection_counts = Counter()
            candidates = rank_search_responses(
                diagnostics=rejection_counts,
                search_id=search_id,
                track=track,
                responses=responses,
            )
            if not is_weak_candidate_set(candidates) or time.monotonic() >= deadline:
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(max(0.0, min(config.search_poll_interval_seconds, remaining)))
    finally:
        _cleanup_search(
            client=client, acquisition_id=acquisition_id, search_id=search_id
        )

    logger.info(
        "Soulseek search diagnostics acquisition_id=%s search_id=%s query=%r "
        "raw_responses=%d raw_files=%d ranked_candidates=%d rejections=%s",
        acquisition_id,
        search_id,
        search_text,
        len(responses),
        raw_file_count,
        len(candidates),
        dict(sorted(rejection_counts.items())),
    )
    return SoulseekSearchAttempt(
        search_id=search_id,
        search_text=search_text,
        responses=responses,
        raw_file_count=raw_file_count,
        candidates=candidates,
        rejection_counts=rejection_counts,
    )


def _cleanup_search(
    *, client: SlskdClient, acquisition_id: str, search_id: str
) -> None:
    try:
        client.delete_search(search_id)
    except Exception:
        logger.warning(
            "Soulseek search cleanup failed acquisition_id=%s search_id=%s",
            acquisition_id,
            search_id,
            exc_info=True,
        )


def _raw_search_file_count(responses: list[dict[str, Any]]) -> int:
    total = 0
    for response in responses:
        total += len(_list_value(response, "files", "Files"))
        total += len(_list_value(response, "lockedFiles", "LockedFiles"))
    return total


def enqueue_soulseek_candidate(candidate_id: str) -> dict[str, object]:
    database_url = _require_database_url()
    store = SoulseekStore(database_url)
    client = SlskdClient(load_slskd_config())
    updated = enqueue_soulseek_candidate_now(
        candidate_id,
        client=client,
        store=store,
    )
    return {
        "acquisition_id": updated.id,
        "batch_id": updated.slskd_batch_id,
        "status": updated.status,
    }


def enqueue_soulseek_candidate_now(
    candidate_id: str,
    *,
    client: SlskdClient,
    store: SoulseekStore,
):
    candidate = store.get_candidate(candidate_id)
    if candidate is None:
        raise SoulseekCandidateNotFoundError(candidate_id)
    acquisition = store.get_acquisition(candidate.acquisition_id)
    if acquisition is None:
        raise SoulseekAcquisitionNotFoundError(candidate.acquisition_id)
    validate_candidate_enqueue(acquisition=acquisition, candidate=candidate)
    if (
        acquisition.slskd_batch_id
        and acquisition.selected_candidate_id == candidate.id
        and acquisition.status
        not in {SOULSEEK_STATUS_FAILED, SOULSEEK_STATUS_LINK_FAILED}
    ):
        return _refresh_enqueued_transfer_status(
            candidate=candidate,
            client=client,
            store=store,
            updated=acquisition,
        )

    try:
        transfer_reference = _enqueue_candidate_download(
            candidate=candidate,
            client=client,
        )
        updated = store.mark_enqueued(
            acquisition_id=acquisition.id,
            batch_id=transfer_reference,
            candidate_id=candidate.id,
            destination=None,
        )
        return _refresh_enqueued_transfer_status(
            candidate=candidate,
            client=client,
            store=store,
            updated=updated,
        )
    except Exception as exc:
        logger.exception("Soulseek enqueue failed candidate_id=%s", candidate_id)
        store.mark_failed(acquisition.id, str(exc))
        raise


def _refresh_enqueued_transfer_status(
    *,
    candidate,
    client: SlskdClient,
    store: SoulseekStore,
    updated,
):
    if not updated.slskd_batch_id:
        return updated
    try:
        payload = client.download(
            transfer_id=_transfer_id(updated.slskd_batch_id),
            username=candidate.username,
        )
    except Exception:
        logger.info(
            "Soulseek transfer status refresh after enqueue failed acquisition_id=%s",
            updated.id,
            exc_info=True,
        )
        return updated
    status, error_detail = _transfer_status(payload)
    return store.mark_transfer_status(
        updated.id,
        error_detail=error_detail,
        status=status,
    )


def refresh_soulseek_acquisition(acquisition_id: str) -> dict[str, object]:
    database_url = _require_database_url()
    store = SoulseekStore(database_url)
    acquisition = store.get_acquisition(acquisition_id)
    if acquisition is None:
        raise SoulseekAcquisitionNotFoundError(acquisition_id)
    if not acquisition.slskd_batch_id:
        updated = store.mark_proposal_available_if_present(acquisition_id)
        return {
            "acquisition_id": acquisition_id,
            "status": updated.status if updated else acquisition.status,
        }

    client = SlskdClient(load_slskd_config())
    try:
        if acquisition.selected_candidate_id is None:
            raise SoulseekCandidateNotFoundError(
                f"Selected candidate missing for acquisition {acquisition_id}"
            )
        candidate = store.get_candidate(acquisition.selected_candidate_id)
        if candidate is None:
            raise SoulseekCandidateNotFoundError(acquisition.selected_candidate_id)
        payload = client.download(
            transfer_id=_transfer_id(acquisition.slskd_batch_id),
            username=candidate.username,
        )
        status, error_detail = _transfer_status(payload)
        updated = store.mark_transfer_status(
            acquisition_id,
            error_detail=error_detail,
            status=status,
        )
        updated = store.mark_proposal_available_if_present(acquisition_id) or updated
        return {"acquisition_id": updated.id, "status": updated.status}
    except Exception as exc:
        logger.exception("Soulseek refresh failed acquisition_id=%s", acquisition_id)
        store.mark_failed(acquisition_id, str(exc))
        raise


def backfill_soulseek_auto_links() -> dict[str, object]:
    store = SoulseekStore(_require_database_url())
    results = [
        *store.backfill_completed_acquisitions_from_existing_final_links(),
        *store.backfill_auto_links_from_pending_suggestions(),
    ]
    affected_playlist_ids = sorted(
        {
            playlist_id
            for result in results
            for playlist_id in result.affected_playlist_ids
        }
    )
    if affected_playlist_ids and (redis_url := os.environ.get("REDIS_URL")):
        from app.m3u.jobs import M3uRegenerationJobEnqueuer

        M3uRegenerationJobEnqueuer(redis_url).enqueue_playlists(affected_playlist_ids)
    return {
        "linked_count": len(results),
        "acquisition_ids": [result.acquisition.id for result in results],
        "affected_playlist_ids": affected_playlist_ids,
    }


def _enqueue_candidate_download(
    *,
    candidate,
    client: SlskdClient,
) -> str:
    payload = client.enqueue_download(
        username=candidate.username,
        filename=candidate.filename,
        size=candidate.size,
    )
    return _stable_enqueue_result(payload)


def _stable_enqueue_result(payload: dict[str, Any]) -> str:
    failures = _list_value(payload, "failed", "Failed")
    if failures:
        raise SoulseekCandidateConflictError(_failure_detail(failures))

    enqueued = _list_value(payload, "enqueued", "Enqueued")
    transfer = next((item for item in enqueued if isinstance(item, dict)), None)
    transfer_id = _string_value(transfer, "id", "Id")
    if transfer_id is None:
        raise RuntimeError("slskd did not return an enqueued transfer id")
    return f"{SOULSEEK_LEGACY_TRANSFER_ID_PREFIX}{transfer_id}"


class _search_lock:
    def __init__(self, redis_url: str) -> None:
        self._connection = Redis.from_url(redis_url)
        self._token = uuid.uuid4().hex
        self._acquired = False

    def __enter__(self) -> None:
        deadline = time.monotonic() + SOULSEEK_SEARCH_LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            if self._connection.set(
                SOULSEEK_SEARCH_LOCK_KEY,
                self._token,
                nx=True,
                ex=SOULSEEK_SEARCH_LOCK_TTL_SECONDS,
            ):
                self._acquired = True
                return
            time.sleep(1)
        raise TimeoutError("Timed out waiting for Soulseek search lock")

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._acquired:
            return
        if self._connection.get(SOULSEEK_SEARCH_LOCK_KEY) == self._token.encode():
            self._connection.delete(SOULSEEK_SEARCH_LOCK_KEY)


def _transfer_status(transfer: dict[str, Any]) -> tuple[str, str | None]:
    state = _transfer_state(transfer)
    error_detail = _string_value(transfer, "exception", "Exception")
    if _is_success_state(state):
        return SOULSEEK_STATUS_COMPLETED, error_detail
    if _is_failed_state(state):
        return SOULSEEK_STATUS_FAILED, error_detail or "Soulseek download failed"
    if _is_downloading_state(state):
        return SOULSEEK_STATUS_DOWNLOADING, error_detail
    return SOULSEEK_STATUS_QUEUED, error_detail


def _transfer_state(transfer: dict[str, Any]) -> str:
    value = _value(transfer, "state", "State")
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _is_success_state(state: str) -> bool:
    normalized = state.casefold()
    return not _is_failed_state(state) and (
        "succeeded" in normalized or "completed" in normalized
    )


def _is_failed_state(state: str) -> bool:
    normalized = state.casefold()
    return any(
        token in normalized
        for token in ("cancelled", "timedout", "errored", "rejected", "aborted")
    )


def _is_downloading_state(state: str) -> bool:
    normalized = state.casefold()
    return "inprogress" in normalized or "initializing" in normalized


def _failure_detail(failures: list[Any]) -> str:
    messages: list[str] = []
    for failure in failures:
        if isinstance(failure, str):
            messages.append(failure)
            continue
        if not isinstance(failure, dict):
            continue
        filename = _string_value(failure, "filename", "Filename")
        message = _string_value(failure, "message", "Message")
        if filename and message:
            messages.append(f"{filename}: {message}")
        elif message:
            messages.append(message)
    return "; ".join(messages) or "Soulseek download failed to enqueue"


def _transfer_id(slskd_batch_id: str) -> str:
    if not slskd_batch_id.startswith(SOULSEEK_LEGACY_TRANSFER_ID_PREFIX):
        return slskd_batch_id
    transfer_id = slskd_batch_id[len(SOULSEEK_LEGACY_TRANSFER_ID_PREFIX) :].strip()
    return transfer_id or slskd_batch_id


def _list_value(mapping: dict[str, Any], *keys: str) -> list[Any]:
    value = _value(mapping, *keys)
    return value if isinstance(value, list) else []


def _string_value(mapping: dict[str, Any] | None, *keys: str) -> str | None:
    if mapping is None:
        return None
    value = _value(mapping, *keys)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _require_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be configured for Soulseek jobs")
    return database_url


def _require_redis_url() -> str:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL must be configured for Soulseek jobs")
    return redis_url
