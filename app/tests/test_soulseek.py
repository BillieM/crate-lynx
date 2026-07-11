from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, insert, select

from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.matching.pipeline import (
    SUGGESTED_LINK_STATUS_APPROVED,
    SUGGESTED_LINK_STATUS_PENDING,
    metadata as matching_metadata,
    suggested_links_table,
)
from app.relationships.models import metadata as relationships_metadata
from app.soulseek.client import SlskdClient
from app.soulseek.config import SlskdConfig, load_slskd_config
from app.soulseek.jobs import (
    enqueue_soulseek_candidate,
    refresh_soulseek_acquisition,
    search_missing_track,
)
from app.soulseek.models import (
    SOULSEEK_STATUS_CANDIDATES_FOUND,
    SOULSEEK_STATUS_COMPLETED,
    SOULSEEK_STATUS_FAILED,
    SOULSEEK_STATUS_INGESTED,
    SOULSEEK_STATUS_LINK_FAILED,
    SOULSEEK_STATUS_LINKED,
    SOULSEEK_STATUS_PROPOSAL_AVAILABLE,
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_STATUS_SEARCHING,
    metadata as soulseek_metadata,
    soulseek_acquisitions_table,
    soulseek_candidates_table,
)
from app.soulseek.ranking import (
    RankedSoulseekCandidate,
    rank_search_responses,
    soulseek_query_for_track,
    soulseek_query_variants_for_track,
)
from app.soulseek.router import create_router
from app.soulseek.schemas import SlskdDownloadCompleteWebhook, SoulseekBulkSearchRequest
from app.soulseek.store import SoulseekStore, parse_acquisition_from_source_path
from app.streaming.models import metadata as streaming_metadata
from tests.factories import TestDataFactory


def _call_endpoint(endpoint, *args, **kwargs):
    result = endpoint(*args, **kwargs)
    if inspect.isawaitable(result):
        raise AssertionError("Unexpected async Soulseek endpoint")
    return result


def _route(router, method: str, path: str):
    return next(
        route
        for route in router.routes
        if getattr(route, "path", None) == path
        and method in getattr(route, "methods", set())
    )


def _create_engine(path):
    engine = create_engine(f"sqlite:///{path}")
    streaming_metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    matching_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    soulseek_metadata.create_all(engine)
    return engine


class _FakeRedisConnection:
    def __init__(self) -> None:
        self.token: bytes | None = None

    def set(self, key, value, *, nx, ex):
        self.token = str(value).encode()
        return True

    def get(self, key):
        return self.token

    def delete(self, key):
        self.token = None


class _FakeRedis:
    @classmethod
    def from_url(cls, url: str) -> _FakeRedisConnection:
        return _FakeRedisConnection()


def _patch_search_job(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client_class,
    database_url: str,
    poll_interval: str = "0.05",
    poll_timeout: str = "0.1",
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", "redis://redis/0")
    monkeypatch.setenv("SLSKD_BASE_URL", "http://slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setenv("SLSKD_SEARCH_POLL_INTERVAL_SECONDS", poll_interval)
    monkeypatch.setenv("SLSKD_SEARCH_POLL_TIMEOUT_SECONDS", poll_timeout)
    monkeypatch.setattr("app.soulseek.jobs.Redis", _FakeRedis)
    monkeypatch.setattr("app.soulseek.jobs.SlskdClient", client_class)


def _soulseek_file(
    filename: str = "Jon Hopkins - Open Eye Signal.flac",
    *,
    bit_depth: int | None = 16,
    bit_rate: int | None = None,
    length: int | None = 270,
    size: int = 30_000_000,
) -> dict[str, object]:
    file_data: dict[str, object] = {
        "filename": filename,
        "size": size,
    }
    if length is not None:
        file_data["length"] = length
    if bit_depth is not None:
        file_data["bitDepth"] = bit_depth
    if bit_rate is not None:
        file_data["bitRate"] = bit_rate
    return file_data


def _soulseek_response(
    files: list[dict[str, object]],
    *,
    has_free_upload_slot: bool = True,
    queue_length: int = 0,
    upload_speed: int = 500000,
    username: str = "peer",
) -> dict[str, object]:
    return {
        "username": username,
        "hasFreeUploadSlot": has_free_upload_slot,
        "queueLength": queue_length,
        "uploadSpeed": upload_speed,
        "files": files,
    }


def _ranked_candidate(
    *,
    filename: str = "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac",
    search_id: str = "search-1",
    size: int = 123,
    username: str = "peer",
) -> RankedSoulseekCandidate:
    return RankedSoulseekCandidate(
        bit_depth=16,
        bit_rate=None,
        duration_seconds=270,
        extension=".flac",
        filename=filename,
        has_free_upload_slot=True,
        is_variable_bit_rate=None,
        queue_length=0,
        sample_rate=44100,
        score=0.9,
        size=size,
        slskd_search_id=search_id,
        upload_speed=500000,
        username=username,
    )


def _download_complete_payload(
    *,
    event_id: str = "event-1",
    local_filename: str = "/data/soulseek/downloads/Jon Hopkins/01 - Open Eye Signal.flac",
    remote_filename: str = "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac",
    transfer_id: str = "transfer-1",
) -> SlskdDownloadCompleteWebhook:
    return SlskdDownloadCompleteWebhook.model_validate(
        {
            "id": event_id,
            "type": "DownloadFileComplete",
            "version": 1,
            "localFilename": local_filename,
            "remoteFilename": remote_filename,
            "transfer": {
                "id": transfer_id,
                "username": "peer",
                "filename": remote_filename,
                "size": 123,
                "state": "Completed, Succeeded",
            },
        }
    )


class _JsonResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self):
        return self._payload


def test_slskd_client_sends_stable_download_body(monkeypatch) -> None:
    seen: list[dict[str, object]] = []

    def fake_urlopen(request, *, context, timeout):
        seen.append(
            {
                "body": json.loads(request.data.decode("utf-8")),
                "method": request.method,
                "url": request.full_url,
                "x_api_key": request.get_header("X-api-key"),
            }
        )
        return _JsonResponse({"enqueued": [{"id": "transfer-1"}], "failed": []})

    monkeypatch.setattr("app.soulseek.client.urlopen", fake_urlopen)

    response = SlskdClient(
        SlskdConfig(
            api_key="secret",
            base_url="https://slskd.example",
        )
    ).enqueue_download(
        filename="Artist\\Track.flac",
        size=123,
        username="peer/name",
    )

    assert response == {"enqueued": [{"id": "transfer-1"}], "failed": []}
    assert seen == [
        {
            "body": [{"filename": "Artist\\Track.flac", "size": 123}],
            "method": "POST",
            "url": "https://slskd.example/api/v0/transfers/downloads/peer%2Fname",
            "x_api_key": "secret",
        }
    ]


def test_slskd_client_sends_search_timeout_in_milliseconds(monkeypatch) -> None:
    seen: list[dict[str, object]] = []

    def fake_urlopen(request, *, context, timeout):
        seen.append(
            {
                "body": json.loads(request.data.decode("utf-8")),
                "method": request.method,
                "timeout": timeout,
                "url": request.full_url,
            }
        )
        return _JsonResponse({"id": "search-1"})

    monkeypatch.setattr("app.soulseek.client.urlopen", fake_urlopen)

    response = SlskdClient(
        SlskdConfig(
            api_key="secret",
            base_url="https://slskd.example",
            request_timeout_seconds=4,
        )
    ).start_search(search_id="search-1", search_text="Artist Track")

    assert response == {"id": "search-1"}
    assert seen[0]["method"] == "POST"
    assert seen[0]["timeout"] == 4
    assert seen[0]["url"] == "https://slskd.example/api/v0/searches"
    assert seen[0]["body"]["searchTimeout"] == 15000


def test_slskd_client_converts_env_search_timeout_seconds(monkeypatch) -> None:
    seen: list[dict[str, object]] = []

    def fake_urlopen(request, *, context, timeout):
        seen.append(json.loads(request.data.decode("utf-8")))
        return _JsonResponse({"id": "search-1"})

    monkeypatch.setenv("SLSKD_BASE_URL", "https://slskd.example")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setenv("SLSKD_SEARCH_TIMEOUT_SECONDS", "30")
    monkeypatch.setattr("app.soulseek.client.urlopen", fake_urlopen)

    SlskdClient(load_slskd_config()).start_search(
        search_id="search-1",
        search_text="Artist Track",
    )

    assert seen[0]["searchTimeout"] == 30000


def test_candidate_ranking_rejects_locked_unsafe_and_bad_duration_results() -> None:
    streaming_track = SimpleNamespace(
        id=10,
        title="Open Eye Signal",
        artist="Jon Hopkins",
        album="Immunity",
        duration_ms=270000,
    )

    candidates = rank_search_responses(
        search_id="search-1",
        track=streaming_track,
        responses=[
            {
                "username": "peer",
                "hasFreeUploadSlot": True,
                "queueLength": 0,
                "uploadSpeed": 800000,
                "files": [
                    {
                        "filename": "Jon Hopkins - Open Eye Signal.flac",
                        "size": 30_000_000,
                        "length": 270,
                        "bitDepth": 16,
                        "sampleRate": 44100,
                    },
                    {
                        "filename": "..\\Open Eye Signal.mp3",
                        "size": 3_000_000,
                        "length": 270,
                    },
                    {
                        "filename": "Jon Hopkins - Open Eye Signal.mp3",
                        "isLocked": True,
                        "size": 3_000_000,
                        "length": 270,
                    },
                    {
                        "filename": "Jon Hopkins - Open Eye Signal.wav",
                        "size": 50_000_000,
                        "length": 30,
                    },
                ],
            }
        ],
    )

    assert len(candidates) == 1
    assert candidates[0].filename == "Jon Hopkins - Open Eye Signal.flac"
    assert candidates[0].score > 0.7
    assert soulseek_query_for_track(streaming_track) == "Jon Hopkins Open Eye Signal"


def test_candidate_ranking_uses_folder_context_for_artist_and_album() -> None:
    streaming_track = SimpleNamespace(
        id=10,
        title="Open Eye Signal",
        artist="Jon Hopkins",
        album="Immunity",
        duration_ms=270000,
    )

    candidates = rank_search_responses(
        search_id="search-1",
        track=streaming_track,
        responses=[
            _soulseek_response(
                [
                    _soulseek_file(
                        "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac",
                    )
                ]
            )
        ],
    )

    assert len(candidates) == 1
    assert candidates[0].filename == "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac"
    assert candidates[0].score > 0.7


def test_candidate_ranking_rejects_title_only_wrong_artist_result() -> None:
    streaming_track = SimpleNamespace(
        id=10,
        title="Cloudy (Kelbin Remix)",
        artist="Daphni",
        album="Cloudy (Kelbin Remix)",
        duration_ms=240000,
    )

    candidates = rank_search_responses(
        search_id="search-1",
        track=streaming_track,
        responses=[
            _soulseek_response(
                [
                    _soulseek_file(
                        "Bicep\\Cloudy\\01 - Cloudy.flac",
                        length=240,
                    )
                ]
            )
        ],
    )

    assert candidates == []


def test_soulseek_query_variants_are_broadest_useful_order() -> None:
    streaming_track = SimpleNamespace(
        id=10,
        title="Open Eye Signal",
        artist="Jon Hopkins",
        album="Immunity",
        duration_ms=270000,
    )

    assert soulseek_query_variants_for_track(streaming_track) == [
        "Jon Hopkins Open Eye Signal",
        "Jon Hopkins Immunity",
        "Open Eye Signal",
    ]


def test_soulseek_query_variants_strip_remix_noise() -> None:
    streaming_track = SimpleNamespace(
        id=10,
        title="Cloudy (Kelbin Remix)",
        artist="Daphni",
        album="Cloudy (Kelbin Remix)",
        duration_ms=240000,
    )

    assert soulseek_query_variants_for_track(streaming_track) == [
        "Daphni Cloudy Kelbin Remix",
        "Daphni Cloudy",
        "Cloudy Kelbin Remix",
        "Cloudy",
    ]


def test_soulseek_query_variants_split_multi_artist_queries() -> None:
    streaming_track = SimpleNamespace(
        id=10,
        title="STRAIGHT FROM THE HOOD (Ned Bennett Remix) (feat. Ned Bennett)",
        artist="DJ SWISHERMAN & BEADS",
        album="CERTIFIED HOOD WEAPONS EP",
        duration_ms=300000,
    )

    variants = soulseek_query_variants_for_track(streaming_track)

    assert variants[0] == (
        "DJ SWISHERMAN BEADS STRAIGHT FROM THE HOOD Ned Bennett Remix feat Ned Bennett"
    )
    assert "DJ SWISHERMAN STRAIGHT FROM THE HOOD" in variants
    assert "BEADS STRAIGHT FROM THE HOOD" in variants
    assert "STRAIGHT FROM THE HOOD" in variants


def test_store_lifecycle_marks_ingested_and_derives_proposal_summary(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-store.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        artist="Jon Hopkins",
        duration_ms=270000,
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    local_track_id = factory.local_track()
    store = SoulseekStore(engine=engine)

    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)

    assert acquisition.status == SOULSEEK_STATUS_SEARCHING
    parsed = parse_acquisition_from_source_path(
        f"/nas/soulseek/downloads/cratelynx/{streaming_track_id}-{acquisition.id}/Track.flac"
    )
    assert parsed == (streaming_track_id, acquisition.id)

    updated = store.mark_ingested_from_source_path(
        local_track_id=local_track_id,
        source_path=(
            f"/nas/soulseek/downloads/cratelynx/"
            f"{streaming_track_id}-{acquisition.id}/Track.flac"
        ),
    )

    assert updated is not None
    assert updated.status == SOULSEEK_STATUS_INGESTED
    with engine.begin() as connection:
        proposal_id = connection.execute(
            insert(suggested_links_table).values(
                local_track_id=local_track_id,
                match_method="tags",
                score=0.93,
                status=SUGGESTED_LINK_STATUS_PENDING,
                streaming_track_id=streaming_track_id,
            )
        ).inserted_primary_key[0]

    summaries = store.latest_summaries_for_tracks([streaming_track_id])

    assert summaries[streaming_track_id].status == SOULSEEK_STATUS_PROPOSAL_AVAILABLE
    assert summaries[streaming_track_id].proposal_id == proposal_id


def test_store_auto_links_ingested_soulseek_download(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-auto-link.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        artist="Jon Hopkins",
        duration_ms=270000,
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    local_track_id = factory.local_track()
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)

    result = store.mark_ingested_and_auto_link_from_source_path(
        local_track_id=local_track_id,
        source_path=(
            f"/nas/soulseek/downloads/cratelynx/"
            f"{streaming_track_id}-{acquisition.id}/Track.flac"
        ),
    )

    assert result is not None
    assert result.acquisition.status == SOULSEEK_STATUS_LINKED
    assert result.acquisition.local_track_id == local_track_id
    assert result.acquisition.final_link_id is not None
    with engine.connect() as connection:
        final_link = connection.execute(select(final_links_table)).mappings().one()
        suggestion = connection.execute(select(suggested_links_table)).mappings().one()
    assert final_link["local_track_id"] == local_track_id
    assert final_link["streaming_track_id"] == streaming_track_id
    assert suggestion["match_method"] == "soulseek"
    assert suggestion["status"] == SUGGESTED_LINK_STATUS_APPROVED


def test_store_auto_links_stable_slskd_download_path(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-legacy-auto-link.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        artist="Jon Hopkins",
        duration_ms=270000,
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    local_track_id = factory.local_track()
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )
    source_path = tmp_path / "Jon Hopkins" / "Immunity" / "01 - Open Eye Signal.flac"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"x" * candidate.size)

    result = store.mark_ingested_and_auto_link_from_source_path(
        local_track_id=local_track_id,
        source_path=str(source_path),
    )

    assert result is not None
    assert result.acquisition.status == SOULSEEK_STATUS_LINKED
    assert result.acquisition.local_track_id == local_track_id
    assert result.acquisition.final_link_id is not None


def test_store_auto_links_slskd_trimmed_legacy_download_path(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-trimmed-auto-link.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        artist="BAUGRUPPE90",
        duration_ms=322000,
        provider_track_id="ytm-ground-lift",
        title="Ground Lift",
    )
    local_track_id = factory.local_track()
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[
            _ranked_candidate(
                filename="Music\\BAUGRUPPE90 - Laser Cut\\03 - Ground Lift.flac",
                size=3,
            )
        ],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="BAUGRUPPE90 Ground Lift",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )
    source_path = tmp_path / "BAUGRUPPE90 - Laser Cut" / "03 - Ground Lift.flac"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"123")

    result = store.mark_ingested_and_auto_link_from_source_path(
        local_track_id=local_track_id,
        source_path=str(source_path),
    )

    assert result is not None
    assert result.acquisition.status == SOULSEEK_STATUS_LINKED
    assert result.acquisition.local_track_id == local_track_id


def test_store_auto_links_from_completed_webhook_source_path(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-webhook-auto-link.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        artist="Jon Hopkins",
        duration_ms=270000,
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    local_track_id = factory.local_track()
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )
    source_path = tmp_path / "downloads" / "Jon Hopkins" / "01 - Open Eye Signal.flac"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"x")
    completed = store.mark_download_completed_from_webhook(
        event_id="event-1",
        source_path=str(source_path),
        transfer_id="transfer-1",
    )

    result = store.mark_ingested_and_auto_link_from_source_path(
        local_track_id=local_track_id,
        source_path=str(source_path),
    )

    assert completed is not None
    assert completed.status == SOULSEEK_STATUS_COMPLETED
    assert result is not None
    assert result.acquisition.status == SOULSEEK_STATUS_LINKED
    assert result.acquisition.local_track_id == local_track_id


def test_store_marks_auto_link_conflict_without_detaching_existing_link(
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-auto-link-conflict.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    existing_local_track_id = factory.local_track()
    imported_local_track_id = factory.local_track()
    with engine.begin() as connection:
        connection.execute(
            insert(final_links_table).values(
                local_track_id=existing_local_track_id,
                streaming_track_id=streaming_track_id,
            )
        )
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)

    result = store.mark_ingested_and_auto_link_from_source_path(
        local_track_id=imported_local_track_id,
        source_path=(
            f"/nas/soulseek/downloads/cratelynx/"
            f"{streaming_track_id}-{acquisition.id}/Track.flac"
        ),
    )

    assert result is not None
    assert result.acquisition.status == SOULSEEK_STATUS_LINK_FAILED
    assert result.acquisition.final_link_id is None
    assert result.acquisition.link_error_detail is not None
    with engine.connect() as connection:
        final_links = connection.execute(select(final_links_table)).mappings().all()
    assert len(final_links) == 1
    assert final_links[0]["local_track_id"] == existing_local_track_id


def test_store_backfill_links_only_high_confidence_soulseek_suggestions(
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-backfill.db")
    factory = TestDataFactory(engine)
    linked_streaming_track_id = factory.streaming_track(
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    ignored_streaming_track_id = factory.streaming_track(
        provider_track_id="ytm-ignored",
        title="Ignored Track",
    )
    linked_local_track_id = factory.local_track()
    ignored_local_track_id = factory.local_track()
    store = SoulseekStore(engine=engine)

    linked_acquisition = store.create_or_reset_search_acquisition(
        linked_streaming_track_id
    )
    linked_acquisition = store.persist_search_results(
        acquisition_id=linked_acquisition.id,
        candidates=[_ranked_candidate(size=123)],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    linked_candidate = store.list_candidates(linked_acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=linked_acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=linked_candidate.id,
        destination=None,
    )
    store.mark_transfer_status(
        linked_acquisition.id,
        error_detail=None,
        status=SOULSEEK_STATUS_COMPLETED,
    )

    ignored_acquisition = store.create_or_reset_search_acquisition(
        ignored_streaming_track_id
    )
    ignored_acquisition = store.persist_search_results(
        acquisition_id=ignored_acquisition.id,
        candidates=[_ranked_candidate(size=456)],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-2",
        search_text="Ignored Track",
    )
    ignored_candidate = store.list_candidates(ignored_acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=ignored_acquisition.id,
        batch_id="transfer:transfer-2",
        candidate_id=ignored_candidate.id,
        destination=None,
    )
    store.mark_transfer_status(
        ignored_acquisition.id,
        error_detail=None,
        status=SOULSEEK_STATUS_COMPLETED,
    )

    with engine.begin() as connection:
        connection.execute(
            insert(suggested_links_table),
            [
                {
                    "local_track_id": linked_local_track_id,
                    "match_method": "tags",
                    "score": 0.96,
                    "status": SUGGESTED_LINK_STATUS_PENDING,
                    "streaming_track_id": linked_streaming_track_id,
                },
                {
                    "local_track_id": ignored_local_track_id,
                    "match_method": "tags",
                    "score": 0.89,
                    "status": SUGGESTED_LINK_STATUS_PENDING,
                    "streaming_track_id": ignored_streaming_track_id,
                },
            ],
        )

    results = store.backfill_auto_links_from_pending_suggestions()

    assert [result.acquisition.id for result in results] == [linked_acquisition.id]
    linked_updated = store.get_acquisition(linked_acquisition.id)
    ignored_updated = store.get_acquisition(ignored_acquisition.id)
    assert linked_updated is not None
    assert linked_updated.status == SOULSEEK_STATUS_LINKED
    assert linked_updated.local_track_id == linked_local_track_id
    assert ignored_updated is not None
    assert ignored_updated.status == SOULSEEK_STATUS_COMPLETED
    assert ignored_updated.local_track_id is None


def test_store_backfill_promotes_completed_acquisition_with_existing_final_link(
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-existing-link-backfill.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    local_track_id = factory.local_track()
    with engine.begin() as connection:
        final_link_id = connection.execute(
            insert(final_links_table).values(
                local_track_id=local_track_id,
                streaming_track_id=streaming_track_id,
            )
        ).inserted_primary_key[0]

    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )
    store.mark_transfer_status(
        acquisition.id,
        error_detail=None,
        status=SOULSEEK_STATUS_COMPLETED,
    )

    results = store.backfill_completed_acquisitions_from_existing_final_links()

    assert [result.acquisition.id for result in results] == [acquisition.id]
    updated = store.get_acquisition(acquisition.id)
    assert updated is not None
    assert updated.status == SOULSEEK_STATUS_LINKED
    assert updated.local_track_id == local_track_id
    assert updated.final_link_id == final_link_id


def test_search_route_persists_acquisition_and_enqueues_job(
    monkeypatch, tmp_path
) -> None:
    engine = _create_engine(tmp_path / "soulseek-router.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    seen: dict[str, object] = {}

    class FakeEnqueuer:
        def __init__(self, redis_url: str) -> None:
            seen["redis_url"] = redis_url

        def enqueue_search(self, acquisition_id: str) -> str:
            seen["acquisition_id"] = acquisition_id
            return "soulseek-job-1"

    monkeypatch.setenv("SLSKD_BASE_URL", "http://slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setattr("app.soulseek.router.SoulseekJobEnqueuer", FakeEnqueuer)

    router = create_router(require_redis_url=lambda: "redis://redis/0")
    response = _call_endpoint(
        _route(
            router, "POST", "/soulseek/missing-tracks/{streaming_track_id}/search"
        ).endpoint,
        streaming_track_id,
        engine=engine,
    )

    assert response.job_id == "soulseek-job-1"
    assert response.acquisition.status == SOULSEEK_STATUS_SEARCHING
    assert seen == {
        "redis_url": "redis://redis/0",
        "acquisition_id": response.acquisition.id,
    }


def test_approve_route_hands_candidate_to_slskd_immediately(
    monkeypatch,
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-approve-router.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    seen: dict[str, object] = {}

    class FakeSlskdClient:
        def __init__(self, config) -> None:
            seen["base_url"] = config.base_url

        def enqueue_download(self, **kwargs):
            seen["enqueue"] = kwargs
            return {"enqueued": [{"id": "transfer-1"}], "failed": []}

        def download(self, **kwargs):
            seen["download"] = kwargs
            return {"id": "transfer-1", "state": "Queued, Remotely"}

    monkeypatch.setenv("SLSKD_BASE_URL", "http://slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setattr("app.soulseek.router.SlskdClient", FakeSlskdClient)

    router = create_router(require_redis_url=lambda: "redis://redis/0")
    response = _call_endpoint(
        _route(
            router, "POST", "/soulseek/candidates/{candidate_id}/approve-download"
        ).endpoint,
        candidate.id,
        engine=engine,
    )

    assert response.job_id is None
    assert response.acquisition.status == SOULSEEK_STATUS_QUEUED
    assert response.acquisition.selected_candidate_id == candidate.id
    assert response.acquisition.enqueue_job_id is None
    assert response.acquisition.slskd_batch_id == "transfer:transfer-1"
    updated = store.get_acquisition(acquisition.id)
    assert updated is not None
    assert updated.status == SOULSEEK_STATUS_QUEUED
    assert updated.selected_candidate_id == candidate.id
    assert updated.slskd_batch_id == "transfer:transfer-1"
    assert seen == {
        "base_url": "http://slskd",
        "enqueue": {
            "filename": "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac",
            "size": 123,
            "username": "peer",
        },
        "download": {"transfer_id": "transfer-1", "username": "peer"},
    }


def test_bulk_search_request_caps_selected_tracks() -> None:
    with pytest.raises(ValueError):
        SoulseekBulkSearchRequest.model_validate(
            {"streaming_track_ids": list(range(1, 27))}
        )


def test_queue_route_lists_review_candidates(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-queue.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        artist="Jon Hopkins",
        duration_ms=270000,
        title="Open Eye Signal",
    )
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    ranked = rank_search_responses(
        search_id="search-1",
        track=store.get_streaming_track(streaming_track_id),
        responses=[_soulseek_response([_soulseek_file()])],
    )
    store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=ranked,
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )

    router = create_router(require_redis_url=lambda: "redis://redis/0")
    response = _call_endpoint(
        _route(router, "GET", "/soulseek/queue").endpoint,
        filter="review",
        engine=engine,
    )

    assert response.total_count == 1
    assert response.items[0].streaming_track.id == streaming_track_id
    assert response.items[0].acquisition.status == SOULSEEK_STATUS_CANDIDATES_FOUND
    assert response.items[0].candidates[0].filename == (
        "Jon Hopkins - Open Eye Signal.flac"
    )


def test_queue_route_classifies_proposal_available_as_review_with_handoff_id(
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-proposal-review.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    local_track_id = factory.local_track(file_path="Open Eye Signal.flac")
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    store.mark_ingested_from_source_path(
        local_track_id=local_track_id,
        source_path=(
            f"/nas/soulseek/downloads/cratelynx/"
            f"{streaming_track_id}-{acquisition.id}/Track.flac"
        ),
    )
    with engine.begin() as connection:
        proposal_id = connection.execute(
            insert(suggested_links_table).values(
                local_track_id=local_track_id,
                match_method="tags",
                score=0.88,
                status=SUGGESTED_LINK_STATUS_PENDING,
                streaming_track_id=streaming_track_id,
            )
        ).inserted_primary_key[0]
    available = store.mark_proposal_available_if_present(acquisition.id)

    router = create_router()
    response = _call_endpoint(
        _route(router, "GET", "/soulseek/queue").endpoint,
        filter="review",
        engine=engine,
    )
    detail = _call_endpoint(
        _route(
            router,
            "GET",
            "/soulseek/acquisitions/{acquisition_id}",
        ).endpoint,
        acquisition.id,
        engine=engine,
    )

    assert available is not None
    assert available.status == SOULSEEK_STATUS_PROPOSAL_AVAILABLE
    assert available.proposal_id == proposal_id
    assert response.total_count == 1
    assert response.items[0].acquisition.status == SOULSEEK_STATUS_PROPOSAL_AVAILABLE
    assert response.items[0].acquisition.proposal_id == proposal_id
    assert detail.acquisition.proposal_id == proposal_id


def test_download_complete_webhook_rejects_missing_or_bad_token(
    monkeypatch,
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-webhook-auth.db")
    router = create_router(require_redis_url=lambda: "redis://redis/0")
    endpoint = _route(router, "POST", "/soulseek/slskd/download-complete").endpoint
    payload = _download_complete_payload()

    monkeypatch.delenv("SLSKD_WEBHOOK_TOKEN", raising=False)
    with pytest.raises(HTTPException) as missing_exc:
        _call_endpoint(
            endpoint,
            payload,
            x_cratelynx_webhook_token="secret",
            engine=engine,
        )
    assert missing_exc.value.status_code == 503

    monkeypatch.setenv("SLSKD_WEBHOOK_TOKEN", "secret")
    with pytest.raises(HTTPException) as bad_exc:
        _call_endpoint(
            endpoint,
            payload,
            x_cratelynx_webhook_token="wrong",
            engine=engine,
        )
    assert bad_exc.value.status_code == 401


def test_download_complete_webhook_records_source_path_and_is_idempotent(
    monkeypatch,
    tmp_path,
) -> None:
    engine = _create_engine(tmp_path / "soulseek-webhook-complete.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )

    monkeypatch.setenv("SLSKD_WEBHOOK_TOKEN", "secret")
    monkeypatch.setenv("SLSKD_DOWNLOADS_CONTAINER_ROOT", "/data/soulseek/downloads")
    monkeypatch.setenv("SLSKD_DOWNLOADS_APP_ROOT", "/nas/soulseek/downloads")
    router = create_router(require_redis_url=lambda: "redis://redis/0")
    endpoint = _route(router, "POST", "/soulseek/slskd/download-complete").endpoint
    payload = _download_complete_payload(
        local_filename="/data/soulseek/downloads/Jon Hopkins/Track.flac"
    )

    first = _call_endpoint(
        endpoint,
        payload,
        x_cratelynx_webhook_token="secret",
        engine=engine,
    )
    second = _call_endpoint(
        endpoint,
        payload,
        x_cratelynx_webhook_token="secret",
        engine=engine,
    )
    updated = store.get_acquisition(acquisition.id)

    assert first.matched is True
    assert second.matched is True
    assert first.acquisition.slskd_transfer_id == "transfer-1"
    assert updated is not None
    assert updated.status == SOULSEEK_STATUS_COMPLETED
    assert (
        updated.completed_source_path
        == "/nas/soulseek/downloads/Jon Hopkins/Track.flac"
    )
    assert updated.slskd_completed_event_id == "event-1"


def test_search_route_returns_503_when_slskd_is_unconfigured(tmp_path) -> None:
    engine = _create_engine(tmp_path / "soulseek-router-unconfigured.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    router = create_router(require_redis_url=lambda: "redis://redis/0")

    with pytest.raises(HTTPException) as exc_info:
        _call_endpoint(
            _route(
                router, "POST", "/soulseek/missing-tracks/{streaming_track_id}/search"
            ).endpoint,
            streaming_track_id,
            engine=engine,
        )

    assert exc_info.value.status_code == 503


def test_enqueue_job_uses_stable_slskd_endpoint(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-stable-enqueue.db'}"
    engine = _create_engine(tmp_path / "soulseek-stable-enqueue.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.enqueue_calls: list[dict[str, object]] = []
            FakeSlskdClient.instances.append(self)

        def enqueue_download(self, **kwargs):
            self.enqueue_calls.append(kwargs)
            return {"enqueued": [{"id": "transfer-1"}], "failed": []}

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setattr("app.soulseek.jobs.SlskdClient", FakeSlskdClient)

    result = enqueue_soulseek_candidate(candidate.id)

    assert result["batch_id"] == "transfer:transfer-1"
    instance = FakeSlskdClient.instances[0]
    assert instance.enqueue_calls == [
        {
            "filename": "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac",
            "size": 123,
            "username": "peer",
        }
    ]
    updated = store.get_acquisition(acquisition.id)
    assert updated is not None
    assert updated.destination is None
    assert updated.slskd_batch_id == "transfer:transfer-1"


def test_refresh_job_uses_stable_slskd_transfer_endpoint(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-legacy-refresh.db'}"
    engine = _create_engine(tmp_path / "soulseek-legacy-refresh.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.download_calls: list[dict[str, object]] = []
            FakeSlskdClient.instances.append(self)

        def download(self, **kwargs):
            self.download_calls.append(kwargs)
            return {"id": "transfer-1", "state": "Completed, Succeeded"}

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setattr("app.soulseek.jobs.SlskdClient", FakeSlskdClient)

    result = refresh_soulseek_acquisition(acquisition.id)

    assert result["status"] == SOULSEEK_STATUS_COMPLETED
    assert FakeSlskdClient.instances[0].download_calls == [
        {"transfer_id": "transfer-1", "username": "peer"}
    ]


def test_refresh_job_treats_stable_rejected_transfer_as_failed(
    monkeypatch, tmp_path
) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-legacy-refresh-failed.db'}"
    engine = _create_engine(tmp_path / "soulseek-legacy-refresh-failed.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(title="Open Eye Signal")
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)
    acquisition = store.persist_search_results(
        acquisition_id=acquisition.id,
        candidates=[_ranked_candidate()],
        fallback_search_id=None,
        fallback_search_text=None,
        search_id="search-1",
        search_text="Jon Hopkins Open Eye Signal",
    )
    candidate = store.list_candidates(acquisition.id)[0]
    store.mark_enqueued(
        acquisition_id=acquisition.id,
        batch_id="transfer:transfer-1",
        candidate_id=candidate.id,
        destination=None,
    )

    class FakeSlskdClient:
        def __init__(self, config) -> None:
            pass

        def download(self, **kwargs):
            return {
                "exception": "File read error.",
                "id": "transfer-1",
                "state": "Completed, Rejected",
            }

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://slskd")
    monkeypatch.setenv("SLSKD_API_KEY", "secret")
    monkeypatch.setattr("app.soulseek.jobs.SlskdClient", FakeSlskdClient)

    result = refresh_soulseek_acquisition(acquisition.id)

    assert result["status"] == SOULSEEK_STATUS_FAILED
    updated = store.get_acquisition(acquisition.id)
    assert updated is not None
    assert updated.error_detail == "File read error."


def test_search_job_persists_ranked_candidates(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-job.db'}"
    engine = _create_engine(tmp_path / "soulseek-job.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        album="Immunity",
        artist="Jon Hopkins",
        duration_ms=270000,
        provider_track_id="ytm-open-eye",
        title="Open Eye Signal",
    )
    store = SoulseekStore(engine=engine)
    acquisition = store.create_or_reset_search_acquisition(streaming_track_id)

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.config = config
            self.deleted_search_ids: list[str] = []
            self.search_text_by_id: dict[str, str] = {}
            FakeSlskdClient.instances.append(self)

        def start_search(self, *, search_id: str, search_text: str):
            self.search_text_by_id[search_id] = search_text
            return {"id": search_id, "searchText": search_text}

        def search_responses(self, search_id: str):
            return [_soulseek_response([_soulseek_file()])]

        def delete_search(self, search_id: str) -> None:
            self.deleted_search_ids.append(search_id)

    _patch_search_job(
        monkeypatch,
        client_class=FakeSlskdClient,
        database_url=database_url,
    )

    result = search_missing_track(acquisition.id)

    assert result["status"] == SOULSEEK_STATUS_CANDIDATES_FOUND
    assert FakeSlskdClient.instances[0].deleted_search_ids == [
        next(iter(FakeSlskdClient.instances[0].search_text_by_id))
    ]
    with engine.connect() as connection:
        acquisition_row = (
            connection.execute(select(soulseek_acquisitions_table)).mappings().one()
        )
    assert acquisition_row["candidate_count"] == 1


def test_search_job_polls_until_delayed_slskd_responses_arrive(
    monkeypatch, tmp_path
) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-delayed-job.db'}"
    engine = _create_engine(tmp_path / "soulseek-delayed-job.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        album="Immunity",
        artist="Jon Hopkins",
        duration_ms=270000,
        title="Open Eye Signal",
    )
    acquisition = SoulseekStore(engine=engine).create_or_reset_search_acquisition(
        streaming_track_id
    )

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.config = config
            self.deleted_search_ids: list[str] = []
            self.poll_counts: dict[str, int] = {}
            FakeSlskdClient.instances.append(self)

        def start_search(self, *, search_id: str, search_text: str):
            self.poll_counts[search_id] = 0
            return {"id": search_id, "searchText": search_text}

        def search_responses(self, search_id: str):
            self.poll_counts[search_id] += 1
            if self.poll_counts[search_id] == 1:
                return []
            return [
                _soulseek_response(
                    [_soulseek_file("Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac")]
                )
            ]

        def delete_search(self, search_id: str) -> None:
            self.deleted_search_ids.append(search_id)

    _patch_search_job(
        monkeypatch,
        client_class=FakeSlskdClient,
        database_url=database_url,
        poll_timeout="1",
    )

    result = search_missing_track(acquisition.id)

    instance = FakeSlskdClient.instances[0]
    assert result["status"] == SOULSEEK_STATUS_CANDIDATES_FOUND
    assert list(instance.poll_counts.values()) == [2]
    assert len(instance.deleted_search_ids) == 1


def test_search_job_uses_broader_fallback_queries_in_order(
    monkeypatch, tmp_path
) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-fallback-job.db'}"
    engine = _create_engine(tmp_path / "soulseek-fallback-job.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        album="Immunity",
        artist="Jon Hopkins",
        duration_ms=270000,
        title="Open Eye Signal",
    )
    acquisition = SoulseekStore(engine=engine).create_or_reset_search_acquisition(
        streaming_track_id
    )

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.config = config
            self.started: list[tuple[str, str]] = []
            self.search_text_by_id: dict[str, str] = {}
            FakeSlskdClient.instances.append(self)

        def start_search(self, *, search_id: str, search_text: str):
            self.started.append((search_id, search_text))
            self.search_text_by_id[search_id] = search_text
            return {"id": search_id, "searchText": search_text}

        def search_responses(self, search_id: str):
            search_text = self.search_text_by_id[search_id]
            if search_text == "Open Eye Signal":
                return [
                    _soulseek_response(
                        [
                            _soulseek_file(
                                "Jon Hopkins\\Immunity\\01 - Open Eye Signal.flac"
                            )
                        ]
                    )
                ]
            return []

        def delete_search(self, search_id: str) -> None:
            return None

    _patch_search_job(
        monkeypatch,
        client_class=FakeSlskdClient,
        database_url=database_url,
    )

    result = search_missing_track(acquisition.id)

    instance = FakeSlskdClient.instances[0]
    assert result["status"] == SOULSEEK_STATUS_CANDIDATES_FOUND
    assert [search_text for _, search_text in instance.started] == [
        "Jon Hopkins Open Eye Signal",
        "Jon Hopkins Immunity",
        "Open Eye Signal",
    ]
    with engine.connect() as connection:
        acquisition_row = (
            connection.execute(select(soulseek_acquisitions_table)).mappings().one()
        )
        candidate_row = (
            connection.execute(select(soulseek_candidates_table)).mappings().one()
        )
    assert acquisition_row["fallback_search_text"] == (
        "Jon Hopkins Immunity | Open Eye Signal"
    )
    assert candidate_row["slskd_search_id"] == instance.started[2][0]


def test_search_job_persists_candidate_from_cleaned_fallback_query(
    monkeypatch, tmp_path
) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-clean-fallback-job.db'}"
    engine = _create_engine(tmp_path / "soulseek-clean-fallback-job.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        album="Cloudy (Kelbin Remix)",
        artist="Daphni",
        duration_ms=240000,
        title="Cloudy (Kelbin Remix)",
    )
    acquisition = SoulseekStore(engine=engine).create_or_reset_search_acquisition(
        streaming_track_id
    )

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.config = config
            self.started: list[tuple[str, str]] = []
            self.search_text_by_id: dict[str, str] = {}
            FakeSlskdClient.instances.append(self)

        def start_search(self, *, search_id: str, search_text: str):
            self.started.append((search_id, search_text))
            self.search_text_by_id[search_id] = search_text
            return {"id": search_id, "searchText": search_text}

        def search_responses(self, search_id: str):
            search_text = self.search_text_by_id[search_id]
            if search_text == "Daphni Cloudy":
                return [
                    _soulseek_response(
                        [
                            _soulseek_file(
                                "Daphni\\Cloudy\\01 - Cloudy.flac",
                                length=240,
                            )
                        ]
                    )
                ]
            return []

        def delete_search(self, search_id: str) -> None:
            return None

    _patch_search_job(
        monkeypatch,
        client_class=FakeSlskdClient,
        database_url=database_url,
    )

    result = search_missing_track(acquisition.id)

    instance = FakeSlskdClient.instances[0]
    assert result["status"] == SOULSEEK_STATUS_CANDIDATES_FOUND
    assert [search_text for _, search_text in instance.started] == [
        "Daphni Cloudy Kelbin Remix",
        "Daphni Cloudy",
    ]
    with engine.connect() as connection:
        acquisition_row = (
            connection.execute(select(soulseek_acquisitions_table)).mappings().one()
        )
        candidate_row = (
            connection.execute(select(soulseek_candidates_table)).mappings().one()
        )
    assert acquisition_row["fallback_search_text"] == "Daphni Cloudy"
    assert candidate_row["filename"] == "Daphni\\Cloudy\\01 - Cloudy.flac"
    assert candidate_row["slskd_search_id"] == instance.started[1][0]


def test_search_job_dedupes_candidates_across_search_ids(monkeypatch, tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'soulseek-dedupe-job.db'}"
    engine = _create_engine(tmp_path / "soulseek-dedupe-job.db")
    factory = TestDataFactory(engine)
    streaming_track_id = factory.streaming_track(
        album=None,
        artist="Jon Hopkins",
        duration_ms=270000,
        title="Open Eye Signal",
    )
    acquisition = SoulseekStore(engine=engine).create_or_reset_search_acquisition(
        streaming_track_id
    )

    class FakeSlskdClient:
        instances: list["FakeSlskdClient"] = []

        def __init__(self, config) -> None:
            self.config = config
            self.started: list[tuple[str, str]] = []
            FakeSlskdClient.instances.append(self)

        def start_search(self, *, search_id: str, search_text: str):
            self.started.append((search_id, search_text))
            return {"id": search_id, "searchText": search_text}

        def search_responses(self, search_id: str):
            return [
                _soulseek_response(
                    [
                        _soulseek_file(
                            "Jon Hopkins - Open Eye Signal.mp3",
                            bit_depth=None,
                            bit_rate=128,
                            length=None,
                            size=7_000_000,
                        )
                    ],
                    has_free_upload_slot=False,
                    queue_length=99,
                    upload_speed=0,
                )
            ]

        def delete_search(self, search_id: str) -> None:
            return None

    _patch_search_job(
        monkeypatch,
        client_class=FakeSlskdClient,
        database_url=database_url,
    )

    result = search_missing_track(acquisition.id)

    assert result["status"] == SOULSEEK_STATUS_CANDIDATES_FOUND
    assert [search_text for _, search_text in FakeSlskdClient.instances[0].started] == [
        "Jon Hopkins Open Eye Signal",
        "Open Eye Signal",
    ]
    with engine.connect() as connection:
        candidate_rows = (
            connection.execute(select(soulseek_candidates_table)).mappings().all()
        )
    assert len(candidate_rows) == 1
