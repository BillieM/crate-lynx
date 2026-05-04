from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import TracebackType
from typing import Callable, Protocol

from rapidfuzz.distance import Levenshtein
from sqlalchemy import create_engine, select, update

from app.local_tracks.store import local_tracks_table
from app.matching.models import ConfidenceBand, MatchResult
from app.streaming.models import streaming_tracks_table


YOUTUBE_MUSIC_WATCH_URL = "https://music.youtube.com/watch?v={provider_track_id}"
PARTIAL_DOWNLOAD_SUFFIXES = frozenset({".part", ".temp", ".tmp", ".ytdl"})


class CommandRunner(Protocol):
    def __call__(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class AcousticCandidate:
    streaming_track_id: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class StreamingAudioFingerprint:
    fingerprint: str
    duration_seconds: float | None


@dataclass(slots=True)
class DownloadedStreamingAudio:
    path: Path
    _temporary_directory: tempfile.TemporaryDirectory[str]

    def cleanup(self) -> None:
        self._temporary_directory.cleanup()

    def __enter__(self) -> DownloadedStreamingAudio:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cleanup()


@dataclass(slots=True)
class YtDlpAudioDownloader:
    yt_dlp_binary: str = "yt-dlp"
    audio_format: str = "m4a"
    command_runner: CommandRunner | None = None

    def download(self, provider_track_id: str) -> DownloadedStreamingAudio:
        temporary_directory = tempfile.TemporaryDirectory(prefix="crate-lynx-acoustic-")
        download_root = Path(temporary_directory.name)
        output_template = download_root / "%(id)s.%(ext)s"
        command = [
            self.yt_dlp_binary,
            "--no-playlist",
            "--format",
            "bestaudio/best",
            "--extract-audio",
            "--audio-format",
            self.audio_format,
            "--output",
            str(output_template),
            YOUTUBE_MUSIC_WATCH_URL.format(provider_track_id=provider_track_id),
        ]

        try:
            self._run(command)
            return DownloadedStreamingAudio(
                path=_find_downloaded_audio_file(download_root),
                _temporary_directory=temporary_directory,
            )
        except Exception:
            temporary_directory.cleanup()
            raise

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if self.command_runner is not None:
            completed = self.command_runner(command)
            completed.check_returncode()
            return completed

        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )


class StreamingTrackAudioDownloader:
    def __init__(
        self,
        *,
        database_url: str,
        yt_dlp_downloader: YtDlpAudioDownloader | None = None,
    ) -> None:
        self._engine = create_engine(database_url)
        self._yt_dlp_downloader = yt_dlp_downloader or YtDlpAudioDownloader()

    def download(self, streaming_track_id: int) -> DownloadedStreamingAudio:
        provider_track_id = self._lookup_provider_track_id(streaming_track_id)
        if provider_track_id is None:
            raise ValueError(
                f"Streaming track {streaming_track_id} does not exist or has no provider track id"
            )

        return self._yt_dlp_downloader.download(provider_track_id)

    def _lookup_provider_track_id(self, streaming_track_id: int) -> str | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(streaming_tracks_table.c.provider_track_id).where(
                        streaming_tracks_table.c.id == streaming_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return _normalize_string(row["provider_track_id"])


@dataclass(slots=True)
class StreamingAudioFingerprintExtractor:
    fpcalc_binary: str = "fpcalc"
    command_runner: CommandRunner | None = None

    def extract(self, audio_path: Path | str) -> StreamingAudioFingerprint:
        command = [
            self.fpcalc_binary,
            "-json",
            str(audio_path),
        ]

        if self.command_runner is not None:
            completed = self.command_runner(command)
            completed.check_returncode()
        else:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )

        return self._parse_fingerprint(completed.stdout)

    def _parse_fingerprint(self, output: str) -> StreamingAudioFingerprint:
        payload = json.loads(output)
        fingerprint = payload.get("fingerprint")
        duration = payload.get("duration")

        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError("fpcalc output did not include a fingerprint")

        return StreamingAudioFingerprint(
            fingerprint=fingerprint,
            duration_seconds=float(duration)
            if isinstance(duration, int | float)
            else None,
        )


class StreamingTrackFingerprinter:
    def __init__(
        self,
        *,
        database_url: str,
        audio_downloader: StreamingTrackAudioDownloader | None = None,
        fingerprint_extractor: StreamingAudioFingerprintExtractor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = create_engine(database_url)
        self._audio_downloader = audio_downloader or StreamingTrackAudioDownloader(
            database_url=database_url
        )
        self._fingerprint_extractor = (
            fingerprint_extractor or StreamingAudioFingerprintExtractor()
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    def fingerprint(self, streaming_track_id: int) -> AcousticCandidate:
        with self._audio_downloader.download(streaming_track_id) as downloaded:
            fingerprint = self._fingerprint_extractor.extract(downloaded.path)

        fingerprinted_at = self._clock()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(streaming_tracks_table)
                .where(streaming_tracks_table.c.id == streaming_track_id)
                .values(
                    fingerprint=fingerprint.fingerprint,
                    fingerprint_duration_seconds=fingerprint.duration_seconds,
                    fingerprinted_at=fingerprinted_at,
                )
            )

        if result.rowcount != 1:
            raise ValueError(f"Streaming track {streaming_track_id} does not exist")

        return AcousticCandidate(
            streaming_track_id=streaming_track_id,
            fingerprint=fingerprint.fingerprint,
        )


class AcousticMatcher:
    def __init__(self, *, database_url: str) -> None:
        self._engine = create_engine(database_url)

    def match(
        self,
        local_track_id: int,
        candidates: Iterable[AcousticCandidate],
    ) -> MatchResult | None:
        local_fingerprint = self._lookup_local_fingerprint(local_track_id)
        if local_fingerprint is None:
            return None

        best_match: MatchResult | None = None
        best_score = -1.0

        for candidate in candidates:
            candidate_fingerprint = _normalize_fingerprint(candidate.fingerprint)
            if candidate_fingerprint is None:
                continue

            score = _score_fingerprints(local_fingerprint, candidate_fingerprint)
            if score <= best_score:
                continue

            best_score = score
            best_match = MatchResult(
                local_track_id=local_track_id,
                streaming_track_id=candidate.streaming_track_id,
                match_method="acoustic",
                score=score,
                confidence_band=ConfidenceBand.from_score(score),
            )

        return best_match

    def _lookup_local_fingerprint(self, local_track_id: int) -> str | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(local_tracks_table.c.fingerprint).where(
                        local_tracks_table.c.id == local_track_id
                    )
                )
                .mappings()
                .one_or_none()
            )

        if row is None:
            return None

        return _normalize_fingerprint(row["fingerprint"])


def run_acoustic_match_job(
    local_track_id: int,
    candidates: list[dict[str, object]],
    *,
    database_url: str | None = None,
) -> MatchResult | None:
    resolved_database_url = database_url or os.environ.get("DATABASE_URL")
    if not resolved_database_url:
        raise RuntimeError("DATABASE_URL must be configured for acoustic matching")

    return AcousticMatcher(database_url=resolved_database_url).match(
        local_track_id,
        [_candidate_from_payload(candidate) for candidate in candidates],
    )


def _candidate_from_payload(payload: dict[str, object]) -> AcousticCandidate:
    streaming_track_id = payload.get("streaming_track_id")
    fingerprint = payload.get("fingerprint")

    if not isinstance(streaming_track_id, int):
        raise ValueError("Acoustic candidate payload is missing streaming_track_id")
    if not isinstance(fingerprint, str):
        raise ValueError("Acoustic candidate payload is missing fingerprint")

    return AcousticCandidate(
        streaming_track_id=streaming_track_id,
        fingerprint=fingerprint,
    )


def _score_fingerprints(left: str, right: str) -> float:
    return Levenshtein.normalized_similarity(left, right)


def _find_downloaded_audio_file(download_root: Path) -> Path:
    downloaded_files = [
        path
        for path in download_root.iterdir()
        if path.is_file() and path.suffix not in PARTIAL_DOWNLOAD_SUFFIXES
    ]

    if len(downloaded_files) != 1:
        raise RuntimeError(
            "yt-dlp did not produce exactly one audio file for acoustic matching"
        )

    return downloaded_files[0]


def _normalize_fingerprint(value: object) -> str | None:
    return _normalize_string(value)


def _normalize_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None
