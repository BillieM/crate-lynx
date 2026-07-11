from __future__ import annotations

from pathlib import Path

import beets
from beets.library import Item, Library
from cryptography.fernet import Fernet
from fastapi import HTTPException
from mutagen.id3 import ID3
import pytest
from sqlalchemy import create_engine, insert, select

from app.ingestion.beets_mirror import (
    beets_items_table,
    metadata as beets_mirror_metadata,
)
from app.ingestion.failures import (
    failed_ingestion_attempts_table,
    metadata as failures_metadata,
)
from app.links.store import final_links_table, metadata as links_metadata
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.rescue.metadata import (
    ArtworkPayload,
    MetadataRescueConflictError,
    RescueMetadata,
    RescueStageResult,
    rescue_metadata,
)
from app.rescue.router import create_router
from app.streaming.models import (
    metadata as streaming_metadata,
    playlist_membership_table,
    streaming_playlists_table,
    streaming_tracks_table,
)
from app.streaming.store import StreamingAccountStore


def test_rescue_metadata_completes_tags_catalogues_mirror_and_attempt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = _build_rescue_state(monkeypatch, tmp_path)

    result = rescue_metadata(
        5,
        failed_attempt_id=40,
        engine=state.engine,
        library_root=state.library_root,
        beets_library=state.beets_library,
    )

    assert result.completed is True
    assert result.partial_failure is False
    assert result.failed_attempt_id == 40
    assert _stage_statuses(result.stages) == {
        "metadata_fetch": "succeeded",
        "file_tags": "succeeded",
        "beets_catalogue": "succeeded",
        "postgres_mirror": "succeeded",
        "failed_attempt": "succeeded",
    }

    tags = ID3(state.track_path)
    assert tags.getall("TIT2")[0].text == ["Rescue Title"]
    assert tags.getall("TPE1")[0].text == ["Rescue Artist"]
    assert tags.getall("TALB")[0].text == ["Rescue Album"]
    assert str(tags.getall("TDRC")[0].text[0]) == "2022"
    apic = tags.getall("APIC")[0]
    assert apic.mime == "image/jpeg"
    assert apic.data == b"cover-bytes"

    item = Library(str(state.beets_library)).get_item(state.beets_id)
    assert item is not None
    assert item.title == "Rescue Title"
    assert item.artist == "Rescue Artist"
    assert item.album == "Rescue Album"
    assert item.year == 2022

    with state.engine.connect() as connection:
        mirrored = connection.execute(select(beets_items_table)).mappings().one()
        remaining_attempt_ids = list(
            connection.scalars(
                select(failed_ingestion_attempts_table.c.id).order_by(
                    failed_ingestion_attempts_table.c.id
                )
            )
        )

    assert mirrored["beets_id"] == state.beets_id
    assert mirrored["title"] == "Rescue Title"
    assert mirrored["artist"] == "Rescue Artist"
    assert mirrored["album"] == "Rescue Album"
    assert mirrored["year"] == 2022
    assert remaining_attempt_ids == [41]


def test_rescue_metadata_reports_catalogue_partial_failure_and_keeps_attempt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = _build_rescue_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.rescue.metadata.update_beets_catalogue",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("catalogue busy")),
    )

    result = rescue_metadata(
        5,
        failed_attempt_id=40,
        engine=state.engine,
        library_root=state.library_root,
        beets_library=state.beets_library,
    )

    assert result.completed is False
    assert result.partial_failure is True
    assert _stage_statuses(result.stages) == {
        "metadata_fetch": "succeeded",
        "file_tags": "succeeded",
        "beets_catalogue": "failed",
        "postgres_mirror": "skipped",
        "failed_attempt": "skipped",
    }
    assert (
        next(stage.detail for stage in result.stages if stage.name == "beets_catalogue")
        == "catalogue busy"
    )

    tags = ID3(state.track_path)
    assert tags.getall("TIT2")[0].text == ["Rescue Title"]
    item = Library(str(state.beets_library)).get_item(state.beets_id)
    assert item is not None
    assert item.title == "Old Title"
    with state.engine.connect() as connection:
        assert (
            connection.scalar(
                select(failed_ingestion_attempts_table.c.id).where(
                    failed_ingestion_attempts_table.c.id == 40
                )
            )
            == 40
        )


def test_rescue_metadata_reports_mirror_partial_failure_after_catalogue_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = _build_rescue_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "app.rescue.metadata.reconcile_beets_mirror",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mirror offline")),
    )

    result = rescue_metadata(
        5,
        failed_attempt_id=40,
        engine=state.engine,
        library_root=state.library_root,
        beets_library=state.beets_library,
    )

    assert result.completed is False
    assert result.partial_failure is True
    assert _stage_statuses(result.stages)["beets_catalogue"] == "succeeded"
    assert _stage_statuses(result.stages)["postgres_mirror"] == "failed"
    assert _stage_statuses(result.stages)["failed_attempt"] == "skipped"
    item = Library(str(state.beets_library)).get_item(state.beets_id)
    assert item is not None
    assert item.title == "Rescue Title"
    with state.engine.connect() as connection:
        assert (
            connection.scalar(
                select(failed_ingestion_attempts_table.c.id).where(
                    failed_ingestion_attempts_table.c.id == 40
                )
            )
            == 40
        )


def test_rescue_metadata_requires_attempt_id_when_local_track_has_multiple_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = _build_rescue_state(monkeypatch, tmp_path)
    with state.engine.begin() as connection:
        connection.execute(
            insert(failed_ingestion_attempts_table).values(
                id=42,
                source_path=str(tmp_path / "second-failure.mp3"),
                filename="second-failure.mp3",
                failure_reason="second failure",
                local_track_id=5,
            )
        )

    with pytest.raises(
        MetadataRescueConflictError,
        match="multiple failed attempts; provide failed_attempt_id explicitly",
    ):
        rescue_metadata(
            5,
            engine=state.engine,
            library_root=state.library_root,
            beets_library=state.beets_library,
        )

    with pytest.raises(Exception):
        ID3(state.track_path)


def test_rescue_router_returns_structured_partial_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = _build_rescue_state(monkeypatch, tmp_path)
    partial_result = rescue_metadata(
        5,
        failed_attempt_id=40,
        engine=state.engine,
        library_root=state.library_root,
        beets_library=tmp_path / "missing-beets.db",
    )
    monkeypatch.setattr(
        "app.rescue.router.rescue_metadata",
        lambda *args, **kwargs: partial_result,
    )
    endpoint = next(
        route.endpoint
        for route in create_router().routes
        if route.path == "/local-tracks/{local_track_id}/rescue"
    )

    with pytest.raises(HTTPException) as exc_info:
        endpoint(5, failed_attempt_id=40, engine=state.engine)

    assert exc_info.value.status_code == 500
    detail = exc_info.value.detail
    assert detail["message"] == "Metadata rescue completed only partially"
    assert detail["result"]["rescue"]["completed"] is False
    assert detail["result"]["rescue"]["partial_failure"] is True
    assert detail["result"]["metadata"]["title"] == "Rescue Title"


class _RescueState:
    def __init__(
        self,
        *,
        engine,
        library_root: Path,
        track_path: Path,
        beets_library: Path,
        beets_id: int,
    ) -> None:
        self.engine = engine
        self.library_root = library_root
        self.track_path = track_path
        self.beets_library = beets_library
        self.beets_id = beets_id


def _build_rescue_state(monkeypatch, tmp_path: Path) -> _RescueState:
    database_url = f"sqlite:///{tmp_path / 'rescue.db'}"
    engine = create_engine(database_url)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    streaming_metadata.create_all(engine)
    failures_metadata.create_all(engine)
    beets_mirror_metadata.create_all(engine)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    beets.config.clear()
    beets.config.read(user=False, defaults=True)

    library_root = tmp_path / "library"
    track_path = library_root / "Artist" / "track.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"")

    beets_library = tmp_path / "beets" / "library.db"
    beets_library.parent.mkdir(parents=True)
    library = Library(str(beets_library))
    item = Item(
        path=str(track_path),
        title="Old Title",
        artist="Old Artist",
        album="Old Album",
        year=2019,
    )
    library.add(item)
    beets_id = int(item.id)

    account = StreamingAccountStore(database_url).create_youtube_music_account(
        display_name="Main Account",
        browser_headers={"Authorization": "Bearer token"},
    )
    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table),
            [
                {
                    "id": 5,
                    "file_path": "Artist/track.mp3",
                    "library_root_rel_path": "Artist/track.mp3",
                    "fingerprint": "fp-5",
                    "beets_id": beets_id,
                },
                {
                    "id": 6,
                    "file_path": "Other/track.mp3",
                    "library_root_rel_path": "Other/track.mp3",
                    "fingerprint": "fp-6",
                    "beets_id": None,
                },
            ],
        )
        connection.execute(
            insert(streaming_playlists_table).values(
                id=7,
                account_id=account.id,
                provider_playlist_id="PL7",
                title="Rescue Mix",
            )
        )
        connection.execute(
            insert(streaming_tracks_table).values(
                id=9,
                provider_track_id="ytm-9",
                title="Stored Title",
                artist="Stored Artist",
                album="Stored Album",
                year=2019,
                isrc=None,
                duration_ms=180000,
            )
        )
        connection.execute(
            insert(playlist_membership_table).values(
                playlist_id=7,
                streaming_track_id=9,
                position=1,
            )
        )
        connection.execute(
            insert(final_links_table).values(
                local_track_id=5,
                streaming_track_id=9,
            )
        )
        connection.execute(
            insert(failed_ingestion_attempts_table),
            [
                {
                    "id": 40,
                    "source_path": str(track_path),
                    "filename": track_path.name,
                    "failure_reason": "missing metadata",
                    "local_track_id": 5,
                },
                {
                    "id": 41,
                    "source_path": str(tmp_path / "other.mp3"),
                    "filename": "other.mp3",
                    "failure_reason": "other failure",
                    "local_track_id": 6,
                },
            ],
        )

    class FakeAdapter:
        def get_track_metadata(self, provider_track_id: str) -> RescueMetadata:
            assert provider_track_id == "ytm-9"
            return RescueMetadata(
                title="Rescue Title",
                artist="Rescue Artist",
                album="Rescue Album",
                year=2022,
                album_art_url="https://img.example/cover.jpg",
            )

    monkeypatch.setattr(
        "app.rescue.metadata.YouTubeMusicAdapter.from_browser_auth",
        lambda browser_headers: FakeAdapter(),
    )
    monkeypatch.setattr(
        "app.rescue.metadata._download_artwork",
        lambda album_art_url: ArtworkPayload(
            data=b"cover-bytes",
            mime_type="image/jpeg",
        ),
    )
    return _RescueState(
        engine=engine,
        library_root=library_root,
        track_path=track_path,
        beets_library=beets_library,
        beets_id=beets_id,
    )


def _stage_statuses(
    stages: tuple[RescueStageResult, ...],
) -> dict[str, str]:
    return {stage.name: stage.status for stage in stages}
