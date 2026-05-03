from pathlib import Path

from sqlalchemy import create_engine, insert

from app.local_tracks.store import local_tracks_table, metadata as local_metadata
from app.matching import (
    AcousticCandidate,
    AcousticMatcher,
    ConfidenceBand,
    run_acoustic_match_job,
)


def test_acoustic_matcher_returns_best_candidate_for_local_fingerprint(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="ABCD-1234",
                beets_id=42,
            )
        )

    result = AcousticMatcher(database_url=database_url).match(
        1,
        [
            AcousticCandidate(streaming_track_id=11, fingerprint="WXYZ-9999"),
            AcousticCandidate(streaming_track_id=7, fingerprint="ABCD-1234"),
        ],
    )

    assert result is not None
    assert result.local_track_id == 1
    assert result.streaming_track_id == 7
    assert result.match_method == "acoustic"
    assert result.score == 1.0
    assert result.confidence_band is ConfidenceBand.HIGH


def test_acoustic_matcher_returns_none_when_local_fingerprint_is_missing(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint=None,
                beets_id=42,
            )
        )

    result = AcousticMatcher(database_url=database_url).match(
        1,
        [AcousticCandidate(streaming_track_id=7, fingerprint="ABCD-1234")],
    )

    assert result is None


def test_run_acoustic_match_job_uses_database_url_and_payload_candidates(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(database_url)
    local_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(local_tracks_table).values(
                file_path="Artist/Track.mp3",
                library_root_rel_path="Artist/Track.mp3",
                fingerprint="ABC123",
                beets_id=42,
            )
        )

    result = run_acoustic_match_job(
        1,
        [
            {"streaming_track_id": 5, "fingerprint": "ABC124"},
            {"streaming_track_id": 6, "fingerprint": "XYZ999"},
        ],
        database_url=database_url,
    )

    assert result is not None
    assert result.streaming_track_id == 5
    assert result.match_method == "acoustic"
