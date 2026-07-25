from __future__ import annotations

import pytest
from app.autopilot.gateway import ExistingServicesGateway
from app.links.store import metadata as links_metadata
from app.local_tracks.store import local_tracks_table
from app.local_tracks.store import metadata as local_tracks_metadata
from app.matching.pipeline import metadata as suggested_links_metadata
from app.relationships.models import metadata as relationships_metadata
from app.soulseek.models import (
    SOULSEEK_STATUS_INGESTED,
    SOULSEEK_STATUS_LINK_FAILED,
    SOULSEEK_STATUS_LINKED,
    SOULSEEK_STATUS_QUEUED,
    SOULSEEK_VERIFICATION_PENDING,
    SOULSEEK_VERIFICATION_REVIEW,
    SOULSEEK_VERIFICATION_VERIFIED,
    soulseek_acquisitions_table,
)
from app.soulseek.models import (
    metadata as soulseek_metadata,
)
from app.soulseek.store import SoulseekStore
from app.streaming.models import (
    metadata as streaming_metadata,
)
from app.streaming.models import (
    playlist_membership_table,
    streaming_accounts_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from sqlalchemy import create_engine, insert, update


def _schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'soulseek-autopilot.db'}")
    for table_metadata in (
        streaming_metadata,
        local_tracks_metadata,
        links_metadata,
        relationships_metadata,
        suggested_links_metadata,
        soulseek_metadata,
    ):
        table_metadata.create_all(engine)
    return engine


def test_unattended_import_waits_for_verification_before_linking(tmp_path) -> None:
    engine = _schema(tmp_path)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Listener",
                auth_token_blob="encrypted",
                auth_state="connected",
            )
        ).inserted_primary_key[0]
        playlist_id = connection.execute(
            insert(streaming_playlists_table).values(
                account_id=account_id,
                provider_playlist_id="PL1",
                title="Autopilot",
                sync_mode="full",
                automation_level="full",
            )
        ).inserted_primary_key[0]
        automation_only_playlist_id = connection.execute(
            insert(streaming_playlists_table).values(
                account_id=account_id,
                provider_playlist_id="PL2",
                title="Autopilot with sync off",
                sync_mode="off",
                automation_level="full",
            )
        ).inserted_primary_key[0]
        streaming_track_id = connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="track-1",
                title="Track",
                artist="Artist",
                duration_ms=240_000,
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=playlist_id,
                streaming_track_id=streaming_track_id,
                position=1,
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=automation_only_playlist_id,
                streaming_track_id=streaming_track_id,
                position=1,
            )
        )
        local_track_id = connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
            )
        ).inserted_primary_key[0]

    store = SoulseekStore(engine=engine)
    acquisition = store.create_autopilot_search_acquisition(
        automation_run_id="run-1",
        streaming_track_id=streaming_track_id,
    )
    ingested = store.mark_ingested_and_auto_link_from_source_path(
        local_track_id=local_track_id,
        source_path=(
            f"/nas/soulseek/downloads/cratelynx/"
            f"{streaming_track_id}-{acquisition.id}/Track.mp3"
        ),
    )

    assert ingested is not None
    assert ingested.acquisition.status == SOULSEEK_STATUS_INGESTED
    assert ingested.acquisition.verification_status == SOULSEEK_VERIFICATION_PENDING
    assert ingested.acquisition.final_link_id is None

    linked = store.mark_unattended_verified_and_auto_link(
        acquisition.id,
        detail="Readable audio and duration verified",
    )

    assert linked.acquisition.status == SOULSEEK_STATUS_LINKED
    assert linked.acquisition.verification_status == SOULSEEK_VERIFICATION_VERIFIED
    assert linked.acquisition.final_link_id is not None
    assert linked.affected_playlist_ids == (
        playlist_id,
        automation_only_playlist_id,
    )


def test_cross_run_unattended_acquisition_resumes_without_duplicate_download(
    tmp_path,
    monkeypatch,
) -> None:
    engine = _schema(tmp_path)
    with engine.begin() as connection:
        streaming_track_id = connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="track-inflight",
                title="Track",
                artist="Artist",
                duration_ms=240_000,
            )
        ).inserted_primary_key[0]

    store = SoulseekStore(engine=engine)
    first = store.create_autopilot_search_acquisition(
        automation_run_id="run-1",
        streaming_track_id=streaming_track_id,
    )
    with engine.begin() as connection:
        connection.execute(
            update(soulseek_acquisitions_table)
            .where(soulseek_acquisitions_table.c.id == first.id)
            .values(status=SOULSEEK_STATUS_QUEUED)
        )

    resumed = store.create_autopilot_search_acquisition(
        automation_run_id="run-2",
        streaming_track_id=streaming_track_id,
    )
    assert resumed.id == first.id
    assert resumed.status == SOULSEEK_STATUS_QUEUED
    assert (
        len(store.list_unattended_acquisitions(statuses={SOULSEEK_STATUS_QUEUED})) == 1
    )

    monkeypatch.setattr(
        "app.autopilot.gateway.search_missing_track",
        lambda acquisition_id: pytest.fail("in-flight acquisition was re-searched"),
    )
    result = ExistingServicesGateway(engine).search_track(
        automation_run_id="run-3",
        streaming_track_id=streaming_track_id,
        unattended=True,
    )
    assert result.acquisition.id == first.id
    assert result.download_suppressed_reason == "unattended_acquisition_in_flight"

    with engine.begin() as connection:
        connection.execute(
            update(soulseek_acquisitions_table)
            .where(soulseek_acquisitions_table.c.id == first.id)
            .values(
                status=SOULSEEK_STATUS_LINK_FAILED,
                completed_source_path="/downloads/already-imported.flac",
                verification_status=SOULSEEK_VERIFICATION_REVIEW,
                verification_detail="Final link conflicted",
            )
        )
    review_result = ExistingServicesGateway(engine).search_track(
        automation_run_id="run-4",
        streaming_track_id=streaming_track_id,
        unattended=True,
    )
    assert review_result.acquisition.id == first.id
    assert (
        review_result.download_suppressed_reason
        == "unattended_acquisition_review_required"
    )
    assert review_result.acquisition.verification_status == SOULSEEK_VERIFICATION_REVIEW
    assert review_result.acquisition.verification_detail == "Final link conflicted"
