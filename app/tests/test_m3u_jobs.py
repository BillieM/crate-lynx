from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Engine, create_engine

from app.links.store import metadata as links_metadata
from app.local_tracks.store import metadata as local_tracks_metadata
from app.m3u.jobs import (
    M3uRegenerationJobEnqueuer,
    affected_full_sync_playlist_ids_for_equivalence,
    affected_full_sync_playlist_ids_for_streaming_track,
    run_m3u_regeneration_job,
)
from app.relationships.models import (
    STREAMING_RELATIONSHIP_TYPE_RELATED,
    metadata as relationships_metadata,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    PLAYLIST_SYNC_MODE_MATCH_ONLY,
    PLAYLIST_SYNC_MODE_OFF,
    metadata as streaming_metadata,
)
from tests import factories


def test_affected_playlists_for_streaming_track_use_equivalent_group_only() -> None:
    engine = _create_affected_playlist_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    first_track_id = test_data.streaming_track(provider_track_id="ytm-1")
    equivalent_track_id = test_data.streaming_track(provider_track_id="ytm-2")
    related_track_id = test_data.streaming_track(provider_track_id="ytm-3")
    direct_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-direct",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Direct",
    )
    equivalent_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-equivalent",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Equivalent",
    )
    match_only_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-match-only",
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
        title="Match Only",
    )
    off_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-off",
        sync_mode=PLAYLIST_SYNC_MODE_OFF,
        title="Off",
    )
    related_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-related",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Related",
    )
    test_data.streaming_relationship(
        first_track_id=first_track_id,
        second_track_id=equivalent_track_id,
    )
    test_data.streaming_relationship(
        first_track_id=first_track_id,
        relationship_type=STREAMING_RELATIONSHIP_TYPE_RELATED,
        second_track_id=related_track_id,
    )
    test_data.playlist_membership(
        playlist_id=direct_playlist_id,
        streaming_track_id=first_track_id,
    )
    test_data.playlist_membership(
        playlist_id=equivalent_playlist_id,
        streaming_track_id=equivalent_track_id,
    )
    test_data.playlist_membership(
        playlist_id=match_only_playlist_id,
        streaming_track_id=equivalent_track_id,
    )
    test_data.playlist_membership(
        playlist_id=off_playlist_id,
        streaming_track_id=first_track_id,
    )
    test_data.playlist_membership(
        playlist_id=related_playlist_id,
        streaming_track_id=related_track_id,
    )

    with engine.connect() as connection:
        playlist_ids = affected_full_sync_playlist_ids_for_streaming_track(
            connection,
            first_track_id,
        )

    assert playlist_ids == (direct_playlist_id, equivalent_playlist_id)


def test_affected_playlists_for_equivalence_use_both_connected_groups() -> None:
    engine = _create_affected_playlist_engine()
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    first_track_id = test_data.streaming_track(provider_track_id="ytm-1")
    first_group_track_id = test_data.streaming_track(provider_track_id="ytm-2")
    second_track_id = test_data.streaming_track(provider_track_id="ytm-3")
    second_group_track_id = test_data.streaming_track(provider_track_id="ytm-4")
    first_group_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-first",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="First Group",
    )
    second_group_playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-second",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Second Group",
    )
    test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-match-only",
        sync_mode=PLAYLIST_SYNC_MODE_MATCH_ONLY,
        title="Match Only",
    )
    test_data.streaming_relationship(
        first_track_id=first_track_id,
        second_track_id=first_group_track_id,
    )
    test_data.streaming_relationship(
        first_track_id=second_track_id,
        second_track_id=second_group_track_id,
    )
    test_data.playlist_membership(
        playlist_id=first_group_playlist_id,
        streaming_track_id=first_group_track_id,
    )
    test_data.playlist_membership(
        playlist_id=second_group_playlist_id,
        streaming_track_id=second_group_track_id,
    )

    with engine.connect() as connection:
        playlist_ids = affected_full_sync_playlist_ids_for_equivalence(
            connection,
            first_track_id,
            second_track_id,
        )

    assert playlist_ids == (first_group_playlist_id, second_group_playlist_id)


def test_m3u_regeneration_job_writes_full_sync_playlist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'm3u-job.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    links_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIBRARY_ROOT", str(tmp_path / "library"))
    monkeypatch.setenv("M3U_OUTPUT_DIR", str(tmp_path / "m3u"))
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-job",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Job Playlist",
    )
    local_track_id = test_data.local_track(file_path="Artist/job.mp3")
    streaming_track_id = test_data.streaming_track(
        artist="Artist",
        duration_ms=185000,
        provider_track_id="ytm-job",
        title="Job Track",
    )
    test_data.playlist_membership(
        playlist_id=playlist_id,
        streaming_track_id=streaming_track_id,
    )
    test_data.final_link(
        local_track_id=local_track_id,
        streaming_track_id=streaming_track_id,
    )

    output_path = run_m3u_regeneration_job(playlist_id)

    expected_path = (tmp_path / "m3u" / "Job-Playlist.m3u").resolve()
    assert output_path == str(expected_path)
    assert expected_path.read_text(encoding="utf-8").splitlines() == [
        "#EXTM3U",
        "#EXTINF:185,Artist - Job Track",
        str((tmp_path / "library" / "Artist/job.mp3").resolve()),
    ]


def test_m3u_regeneration_job_enqueuer_enqueues_playlist_jobs(monkeypatch) -> None:
    seen: dict[str, object] = {"jobs": []}

    class FakeRedis:
        @classmethod
        def from_url(cls, url: str) -> object:
            seen["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, connection: object) -> None:
            seen["queue_name"] = name
            seen["connection"] = connection

        def enqueue(
            self,
            func: str,
            playlist_id: int,
            *,
            job_timeout: str,
        ) -> SimpleNamespace:
            seen["jobs"].append((func, playlist_id, job_timeout))
            return SimpleNamespace(id=f"m3u-job-{playlist_id}")

    monkeypatch.setattr("app.m3u.jobs.Redis", FakeRedis)
    monkeypatch.setattr("app.m3u.jobs.Queue", FakeQueue)

    job_ids = M3uRegenerationJobEnqueuer(
        redis_url="redis://redis:6379/4",
        job_timeout="2m",
    ).enqueue_playlists([7, 3, 7])

    assert job_ids == ["m3u-job-3", "m3u-job-7"]
    assert seen == {
        "redis_url": "redis://redis:6379/4",
        "queue_name": "m3u",
        "connection": seen["connection"],
        "jobs": [
            ("app.m3u.jobs.run_m3u_regeneration_job", 3, "2m"),
            ("app.m3u.jobs.run_m3u_regeneration_job", 7, "2m"),
        ],
    }


def _create_affected_playlist_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    streaming_metadata.create_all(engine)
    relationships_metadata.create_all(engine)
    return engine
