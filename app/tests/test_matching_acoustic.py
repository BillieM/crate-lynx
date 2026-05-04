from datetime import UTC, datetime
from pathlib import Path
import subprocess
from typing import Any

from sqlalchemy import create_engine, insert, select

from app.local_tracks.store import local_tracks_table, metadata as local_metadata
from app.matching import (
    AcousticCandidate,
    AcousticMatcher,
    ConfidenceBand,
    StreamingAudioFingerprint,
    StreamingAudioFingerprintExtractor,
    StreamingTrackAudioDownloader,
    StreamingTrackFingerprinter,
    YtDlpAudioDownloader,
    run_acoustic_match_job,
)
from app.streaming.models import metadata as streaming_metadata
from app.streaming.models import streaming_tracks_table


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


def test_acoustic_matcher_scores_raw_chromaprint_frame_similarity(
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
                fingerprint="1, 3, 7, 15",
                beets_id=42,
            )
        )

    result = AcousticMatcher(database_url=database_url).match(
        1,
        [
            AcousticCandidate(streaming_track_id=3, fingerprint="1, 3"),
            AcousticCandidate(streaming_track_id=5, fingerprint="1, 3, 7, 14"),
        ],
    )

    assert result is not None
    assert result.streaming_track_id == 5
    assert result.score == 0.9921875
    assert result.confidence_band is ConfidenceBand.HIGH


def test_acoustic_matcher_aligns_shifted_raw_chromaprint_frames(
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
                fingerprint="10 20 30 40",
                beets_id=42,
            )
        )

    result = AcousticMatcher(database_url=database_url).match(
        1,
        [AcousticCandidate(streaming_track_id=7, fingerprint="999 10 20 30 40")],
    )

    assert result is not None
    assert result.streaming_track_id == 7
    assert result.score == 0.8
    assert result.confidence_band is ConfidenceBand.MEDIUM


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


def test_ytdlp_audio_downloader_downloads_track_to_temporary_file() -> None:
    seen_commands: list[list[str]] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        output_template = Path(command[command.index("--output") + 1])
        downloaded_path = output_template.parent / "video-123.m4a"
        downloaded_path.write_bytes(b"audio")
        return subprocess.CompletedProcess(command, 0)

    downloaded = YtDlpAudioDownloader(
        yt_dlp_binary="yt-dlp-test",
        command_runner=fake_run,
    ).download("video-123")

    assert downloaded.path.name == "video-123.m4a"
    assert downloaded.path.read_bytes() == b"audio"
    assert seen_commands == [
        [
            "yt-dlp-test",
            "--no-playlist",
            "--format",
            "bestaudio/best",
            "--extract-audio",
            "--audio-format",
            "m4a",
            "--output",
            str(downloaded.path.parent / "%(id)s.%(ext)s"),
            "https://music.youtube.com/watch?v=video-123",
        ]
    ]

    download_root = downloaded.path.parent
    downloaded.cleanup()
    assert not download_root.exists()


def test_ytdlp_audio_downloader_cleans_up_when_download_fails() -> None:
    download_roots: list[Path] = []

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        output_template = Path(command[command.index("--output") + 1])
        download_roots.append(output_template.parent)
        raise subprocess.CalledProcessError(1, command)

    try:
        YtDlpAudioDownloader(command_runner=fake_run).download("video-123")
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("Expected yt-dlp failure")

    assert download_roots
    assert not download_roots[0].exists()


def test_streaming_track_audio_downloader_uses_candidate_provider_track_id(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming.db'}"
    engine = create_engine(database_url)
    streaming_metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="video-456",
                title="Track",
                artist="Artist",
                album="Album",
                year=2026,
                isrc=None,
                duration_ms=123000,
                fingerprint=None,
                fingerprint_duration_seconds=None,
                fingerprinted_at=None,
            )
        )

    class FakeYtDlpDownloader:
        def __init__(self) -> None:
            self.provider_track_ids: list[str] = []

        def download(self, provider_track_id: str) -> Any:
            self.provider_track_ids.append(provider_track_id)
            return object()

    yt_dlp_downloader = FakeYtDlpDownloader()
    downloaded = StreamingTrackAudioDownloader(
        database_url=database_url,
        yt_dlp_downloader=yt_dlp_downloader,
    ).download(1)

    assert downloaded is not None
    assert yt_dlp_downloader.provider_track_ids == ["video-456"]


def test_streaming_audio_fingerprint_extractor_runs_fpcalc_and_parses_json(
    tmp_path: Path,
) -> None:
    seen_commands: list[list[str]] = []
    audio_path = tmp_path / "stream.m4a"
    audio_path.write_bytes(b"audio")

    def fake_run(command: list[str]) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"fingerprint":"stream-fp","duration":201.25}',
        )

    fingerprint = StreamingAudioFingerprintExtractor(
        fpcalc_binary="fpcalc-test",
        command_runner=fake_run,
    ).extract(audio_path)

    assert fingerprint == StreamingAudioFingerprint(
        fingerprint="stream-fp",
        duration_seconds=201.25,
    )
    assert seen_commands == [["fpcalc-test", "-json", str(audio_path)]]


def test_streaming_track_fingerprinter_persists_extracted_fingerprint(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'streaming.db'}"
    engine = create_engine(database_url)
    streaming_metadata.create_all(engine)
    audio_path = tmp_path / "downloaded.m4a"
    audio_path.write_bytes(b"audio")
    fingerprinted_at = datetime(2026, 5, 4, 12, 30, tzinfo=UTC)

    with engine.begin() as connection:
        connection.execute(
            insert(streaming_tracks_table).values(
                provider_track_id="video-789",
                title="Track",
                artist="Artist",
                album="Album",
                year=2026,
                isrc=None,
                duration_ms=123000,
                fingerprint=None,
                fingerprint_duration_seconds=None,
                fingerprinted_at=None,
            )
        )

    class FakeDownloadedAudio:
        def __init__(self) -> None:
            self.path = audio_path
            self.cleaned_up = False

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: object) -> None:
            self.cleaned_up = True

    class FakeAudioDownloader:
        def __init__(self) -> None:
            self.streaming_track_ids: list[int] = []
            self.downloaded = FakeDownloadedAudio()

        def download(self, streaming_track_id: int) -> FakeDownloadedAudio:
            self.streaming_track_ids.append(streaming_track_id)
            return self.downloaded

    class FakeFingerprintExtractor:
        def __init__(self) -> None:
            self.audio_paths: list[Path] = []

        def extract(self, path: Path) -> StreamingAudioFingerprint:
            self.audio_paths.append(path)
            return StreamingAudioFingerprint(
                fingerprint="stream-fp-789",
                duration_seconds=198.5,
            )

    audio_downloader = FakeAudioDownloader()
    fingerprint_extractor = FakeFingerprintExtractor()

    candidate = StreamingTrackFingerprinter(
        database_url=database_url,
        audio_downloader=audio_downloader,
        fingerprint_extractor=fingerprint_extractor,
        clock=lambda: fingerprinted_at,
    ).fingerprint(1)

    with engine.connect() as connection:
        stored_track = (
            connection.execute(select(streaming_tracks_table)).mappings().one()
        )

    assert candidate == AcousticCandidate(
        streaming_track_id=1,
        fingerprint="stream-fp-789",
    )
    assert audio_downloader.streaming_track_ids == [1]
    assert fingerprint_extractor.audio_paths == [audio_path]
    assert audio_downloader.downloaded.cleaned_up is True
    assert stored_track["fingerprint"] == "stream-fp-789"
    assert stored_track["fingerprint_duration_seconds"] == 198.5
    assert stored_track["fingerprinted_at"] == fingerprinted_at.replace(tzinfo=None)
