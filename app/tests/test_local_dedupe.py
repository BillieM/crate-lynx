from __future__ import annotations

from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, insert, select, update

from app.ingestion.beets_mirror import metadata as beets_metadata
from app.ingestion.failures import (
    failed_ingestion_attempts_table,
    metadata as failed_ingestion_metadata,
)
from app.links.store import final_links_table, metadata as links_metadata
from app.local_dedupe.models import (
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT,
    LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR,
    LOCAL_DEDUPE_SOURCE_ISRC,
    LOCAL_DEDUPE_SOURCE_METADATA,
    local_dedupe_decisions_table,
    metadata as local_dedupe_metadata,
)
from app.local_dedupe.store import LocalDedupeGroupNotFoundError, LocalDedupeStore
from app.local_tracks.store import local_tracks_table, metadata as local_tracks_metadata
from app.matching.pipeline import (
    suggested_links_table,
    metadata as suggested_links_metadata,
)
from app.sonic.models import (
    generated_playlist_tracks_table,
    metadata as sonic_metadata,
    sonic_track_features_table,
)
from app.soulseek.models import (
    SOULSEEK_STATUS_LINKED,
    soulseek_acquisitions_table,
    metadata as soulseek_metadata,
)
from app.streaming.models import (
    PLAYLIST_SYNC_MODE_FULL,
    metadata as streaming_metadata,
)
from tests import factories


def test_queue_detects_exact_fuzzy_isrc_and_metadata_groups(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = _create_local_dedupe_engine(tmp_path / "local-dedupe.db")
    test_data = factories.TestDataFactory(engine)

    exact_a = _local_track_with_item(
        test_data,
        beets_id=101,
        file_path="Exact/A.mp3",
        fingerprint="fp-exact",
        title="Exact A",
    )
    exact_b = _local_track_with_item(
        test_data,
        beets_id=102,
        file_path="Exact/B.mp3",
        fingerprint="fp-exact",
        title="Exact B",
    )
    fuzzy_a = _local_track_with_item(
        test_data,
        beets_id=201,
        file_path="Fuzzy/A.mp3",
        fingerprint="fp-fuzzy-a",
        length=180.0,
        title="Fuzzy A",
    )
    fuzzy_b = _local_track_with_item(
        test_data,
        beets_id=202,
        file_path="Fuzzy/B.mp3",
        fingerprint="fp-fuzzy-b",
        length=181.0,
        title="Fuzzy B",
    )
    isrc_a = _local_track_with_item(
        test_data,
        beets_id=301,
        file_path="Isrc/A.mp3",
        fingerprint="fp-isrc-a",
        isrc="gb-abc-24-00001",
        title="ISRC A",
    )
    isrc_b = _local_track_with_item(
        test_data,
        beets_id=302,
        file_path="Isrc/B.mp3",
        fingerprint="fp-isrc-b",
        isrc="GBABC2400001",
        title="ISRC B",
    )
    metadata_a = _local_track_with_item(
        test_data,
        beets_id=401,
        file_path="Metadata/A.mp3",
        fingerprint=None,
        length=245.0,
        title="Memory Lane",
    )
    metadata_b = _local_track_with_item(
        test_data,
        beets_id=402,
        file_path="Metadata/B.mp3",
        fingerprint=None,
        length=247.0,
        title="Memory Lane",
    )

    def fake_compare(left: str, right: str) -> float | None:
        return 0.86 if {left, right} == {"fp-fuzzy-a", "fp-fuzzy-b"} else 0.0

    monkeypatch.setattr(
        "app.local_dedupe.store._compare_chromaprint_fingerprints",
        fake_compare,
    )

    groups = LocalDedupeStore(engine=engine).list_groups()
    groups_by_source = {group.source: group for group in groups}

    assert {
        track.id
        for track in groups_by_source[LOCAL_DEDUPE_SOURCE_FINGERPRINT_EXACT].tracks
    } == {
        exact_a,
        exact_b,
    }
    assert groups_by_source[LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR].match_score == 0.86
    assert {
        track.id
        for track in groups_by_source[LOCAL_DEDUPE_SOURCE_FINGERPRINT_SIMILAR].tracks
    } == {fuzzy_a, fuzzy_b}
    assert {
        track.id for track in groups_by_source[LOCAL_DEDUPE_SOURCE_ISRC].tracks
    } == {
        isrc_a,
        isrc_b,
    }
    assert {
        track.id for track in groups_by_source[LOCAL_DEDUPE_SOURCE_METADATA].tracks
    } == {
        metadata_a,
        metadata_b,
    }


def test_fuzzy_chromaprint_compare_uses_stored_fpcalc_fingerprints(
    monkeypatch,
) -> None:
    captured_pairs = []

    def fake_compare(left, right) -> float:
        captured_pairs.append((left, right))
        return 0.8123

    monkeypatch.setattr("acoustid.compare_fingerprints", fake_compare)

    from app.local_dedupe.store import _compare_chromaprint_fingerprints

    assert (
        _compare_chromaprint_fingerprints("left-fingerprint", "right-fingerprint")
        == 0.8123
    )
    assert captured_pairs == [
        ((0, "left-fingerprint"), (0, "right-fingerprint")),
    ]


def test_dismiss_group_hides_current_candidate(tmp_path: Path) -> None:
    engine = _create_local_dedupe_engine(tmp_path / "local-dedupe-dismiss.db")
    test_data = factories.TestDataFactory(engine)
    _local_track_with_item(
        test_data,
        beets_id=101,
        file_path="Exact/A.mp3",
        fingerprint="fp-exact",
    )
    _local_track_with_item(
        test_data,
        beets_id=102,
        file_path="Exact/B.mp3",
        fingerprint="fp-exact",
    )
    store = LocalDedupeStore(engine=engine)

    group = store.list_groups()[0]
    decision = store.dismiss_group(group.group_key)

    assert decision.action == "dismissed"
    assert store.list_groups() == []


def test_resolve_rejects_stale_group_key(tmp_path: Path) -> None:
    engine = _create_local_dedupe_engine(tmp_path / "local-dedupe-stale.db")
    test_data = factories.TestDataFactory(engine)
    keep_id = _local_track_with_item(
        test_data,
        beets_id=101,
        file_path="Exact/A.mp3",
        fingerprint="fp-exact",
    )
    duplicate_id = _local_track_with_item(
        test_data,
        beets_id=102,
        file_path="Exact/B.mp3",
        fingerprint="fp-exact",
    )
    store = LocalDedupeStore(engine=engine)
    group = store.list_groups()[0]

    with engine.begin() as connection:
        connection.execute(
            update(local_tracks_table)
            .where(local_tracks_table.c.id == duplicate_id)
            .values(fingerprint="fp-new")
        )

    try:
        store.resolve_group(group_key=group.group_key, keeper_local_track_id=keep_id)
    except LocalDedupeGroupNotFoundError:
        pass
    else:
        raise AssertionError("Expected stale dedupe group key to be rejected")


def test_resolve_group_quarantines_duplicates_and_removes_records(
    tmp_path: Path,
) -> None:
    engine = _create_local_dedupe_engine(tmp_path / "local-dedupe-resolve.db")
    library_root = tmp_path / "library"
    quarantine_root = tmp_path / "quarantine"
    beets_library = tmp_path / "beets" / "library.db"
    _create_beets_sqlite(beets_library, beets_ids=[101, 102])
    _write_audio_file(library_root / "Artist/keep.mp3")
    duplicate_file = library_root / "Artist/duplicate.mp3"
    _write_audio_file(duplicate_file)
    test_data = factories.TestDataFactory(engine)
    account_id = test_data.streaming_account()
    playlist_id = test_data.streaming_playlist(
        account_id=account_id,
        provider_playlist_id="PL-dedupe",
        sync_mode=PLAYLIST_SYNC_MODE_FULL,
        title="Dedupe Playlist",
    )
    streaming_track_id = test_data.streaming_track(provider_track_id="ytm-dedupe")
    test_data.playlist_membership(
        playlist_id=playlist_id,
        streaming_track_id=streaming_track_id,
    )
    keep_id = _local_track_with_item(
        test_data,
        beets_id=101,
        file_path="Artist/keep.mp3",
        fingerprint="fp-exact",
        title="Keep",
    )
    duplicate_id = _local_track_with_item(
        test_data,
        beets_id=102,
        file_path="Artist/duplicate.mp3",
        fingerprint="fp-exact",
        title="Duplicate",
    )
    duplicate_final_link_id = test_data.final_link(
        local_track_id=duplicate_id,
        streaming_track_id=streaming_track_id,
    )
    test_data.suggested_link(
        local_track_id=duplicate_id,
        streaming_track_id=streaming_track_id,
    )
    test_data.sonic_track_feature(local_track_id=duplicate_id)
    run_id = test_data.playlist_generation_run(track_count=1)
    generated_playlist_id = test_data.generated_playlist(
        run_id=run_id,
        track_count=1,
    )
    test_data.generated_playlist_track(
        generated_playlist_id=generated_playlist_id,
        local_track_id=duplicate_id,
    )
    with engine.begin() as connection:
        connection.execute(
            insert(failed_ingestion_attempts_table).values(
                source_path="/incoming/duplicate.mp3",
                filename="duplicate.mp3",
                fingerprint="fp-exact",
                failure_reason="duplicate",
                local_track_id=duplicate_id,
            )
        )
        connection.execute(
            insert(soulseek_acquisitions_table).values(
                id="acq-dedupe",
                streaming_track_id=streaming_track_id,
                status=SOULSEEK_STATUS_LINKED,
                local_track_id=duplicate_id,
                final_link_id=duplicate_final_link_id,
            )
        )

    store = LocalDedupeStore(engine=engine)
    group = store.list_groups()[0]
    result = store.resolve_group(
        group_key=group.group_key,
        keeper_local_track_id=keep_id,
        beets_library=beets_library,
        library_root=library_root,
        quarantine_root=quarantine_root,
    )

    assert result.affected_playlist_ids == (playlist_id,)
    assert result.decision.action == "resolved"
    assert result.decision.keeper_local_track_id == keep_id
    assert result.decision.quarantined_track_ids_json == [duplicate_id]
    assert not duplicate_file.exists()
    assert list(quarantine_root.glob("*/local-*/Artist/duplicate.mp3"))

    with engine.connect() as connection:
        assert (
            connection.execute(
                select(local_tracks_table.c.id).where(
                    local_tracks_table.c.id == keep_id
                )
            ).scalar_one_or_none()
            == keep_id
        )
        assert (
            connection.execute(
                select(local_tracks_table.c.id).where(
                    local_tracks_table.c.id == duplicate_id
                )
            ).scalar_one_or_none()
            is None
        )
        assert connection.execute(select(final_links_table)).all() == []
        assert connection.execute(select(suggested_links_table)).all() == []
        assert connection.execute(select(sonic_track_features_table)).all() == []
        assert connection.execute(select(generated_playlist_tracks_table)).all() == []
        failed_attempt = (
            connection.execute(select(failed_ingestion_attempts_table)).mappings().one()
        )
        assert failed_attempt["local_track_id"] is None
        acquisition = (
            connection.execute(select(soulseek_acquisitions_table)).mappings().one()
        )
        assert acquisition["local_track_id"] is None
        assert acquisition["final_link_id"] is None
        assert (
            connection.execute(select(local_dedupe_decisions_table.c.group_key))
            .scalars()
            .one()
            == group.group_key
        )

    with sqlite3.connect(beets_library) as connection:
        assert connection.execute("SELECT id FROM items ORDER BY id").fetchall() == [
            (101,)
        ]


def test_resolve_group_restores_file_and_database_when_beets_cleanup_fails(
    tmp_path: Path,
) -> None:
    engine = _create_local_dedupe_engine(tmp_path / "local-dedupe-rollback.db")
    library_root = tmp_path / "library"
    quarantine_root = tmp_path / "quarantine"
    beets_library = tmp_path / "beets" / "library.db"
    beets_library.parent.mkdir(parents=True)
    with sqlite3.connect(beets_library):
        pass
    _write_audio_file(library_root / "Artist/keep.mp3")
    duplicate_file = library_root / "Artist/duplicate.mp3"
    _write_audio_file(duplicate_file)
    test_data = factories.TestDataFactory(engine)
    keep_id = _local_track_with_item(
        test_data,
        beets_id=101,
        file_path="Artist/keep.mp3",
        fingerprint="fp-exact",
    )
    duplicate_id = _local_track_with_item(
        test_data,
        beets_id=102,
        file_path="Artist/duplicate.mp3",
        fingerprint="fp-exact",
    )
    store = LocalDedupeStore(engine=engine)
    group = store.list_groups()[0]

    try:
        store.resolve_group(
            group_key=group.group_key,
            keeper_local_track_id=keep_id,
            beets_library=beets_library,
            library_root=library_root,
            quarantine_root=quarantine_root,
        )
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("Expected Beets cleanup failure to abort resolution")

    assert duplicate_file.exists()
    assert not list(quarantine_root.glob("*/local-*/Artist/duplicate.mp3"))
    with engine.connect() as connection:
        assert set(connection.execute(select(local_tracks_table.c.id)).scalars()) == {
            keep_id,
            duplicate_id,
        }
        assert connection.execute(select(local_dedupe_decisions_table)).all() == []


def _create_local_dedupe_engine(path: Path):
    engine = create_engine(f"sqlite:///{path}")
    streaming_metadata.create_all(engine)
    beets_metadata.create_all(engine)
    local_tracks_metadata.create_all(engine)
    links_metadata.create_all(engine)
    suggested_links_metadata.create_all(engine)
    sonic_metadata.create_all(engine)
    soulseek_metadata.create_all(engine)
    failed_ingestion_metadata.create_all(engine)
    local_dedupe_metadata.create_all(engine)
    return engine


def _local_track_with_item(
    test_data: factories.TestDataFactory,
    *,
    beets_id: int,
    file_path: str,
    fingerprint: str | None = "fingerprint",
    isrc: str | None = None,
    length: float | None = 180.0,
    title: str = "Track",
) -> int:
    local_track_id = test_data.local_track(
        beets_id=beets_id,
        file_path=file_path,
        fingerprint=fingerprint,
    )
    test_data.beets_item(
        beets_id=beets_id,
        album="Album",
        artist="Artist",
        bitdepth=16,
        bitrate=320000,
        format="MP3",
        isrc=isrc,
        length=length,
        samplerate=44100,
        title=title,
    )
    return local_track_id


def _write_audio_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"audio")


def _create_beets_sqlite(path: Path, *, beets_ids: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE item_attributes (entity_id INTEGER, key TEXT, value TEXT)"
        )
        for beets_id in beets_ids:
            connection.execute("INSERT INTO items (id) VALUES (?)", (beets_id,))
            connection.execute(
                "INSERT INTO item_attributes (entity_id, key, value) VALUES (?, ?, ?)",
                (beets_id, "mood", "warm"),
            )
