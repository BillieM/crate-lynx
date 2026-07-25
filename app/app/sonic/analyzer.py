from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.sonic.models import (
    SONIC_ANALYZER_CURRENT_VERSION,
    SONIC_ANALYZER_LIBROSA_V1,
)
from app.sonic.semantic import (
    SemanticAudioEmbedder,
    build_semantic_embedder_from_environment,
    semantic_cache_payload,
)

MAX_SEMANTIC_ANALYSIS_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class SonicAnalysisResult:
    analyzer_key: str
    analyzer_version: str
    descriptors: dict[str, Any]
    vector: list[float]


class SonicAnalyzer(Protocol):
    analyzer_key: str
    analyzer_version: str

    def analyze(self, audio_path: Path | str) -> SonicAnalysisResult: ...


@dataclass(slots=True)
class LibrosaSonicAnalyzer:
    analyzer_key: str = SONIC_ANALYZER_LIBROSA_V1
    analyzer_version: str = SONIC_ANALYZER_CURRENT_VERSION
    sample_rate: int = 22050
    max_duration_seconds: int = 300
    semantic_embedder: SemanticAudioEmbedder | None = None
    semantic_unavailable_reason: str | None = None

    def analyze(self, audio_path: Path | str) -> SonicAnalysisResult:
        try:
            import librosa
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "librosa and numpy must be installed for sonic feature extraction"
            ) from exc

        y, sr = librosa.load(
            Path(audio_path),
            sr=self.sample_rate,
            mono=True,
            duration=self.max_duration_seconds,
        )
        if y.size == 0:
            raise ValueError("Audio file did not contain analyzable samples")

        descriptors: dict[str, Any] = {}

        def add_scalar(name: str, value: object) -> None:
            scalar = float(np.asarray(value).reshape(-1)[0])
            if np.isfinite(scalar):
                descriptors[name] = scalar

        def add_stats(name: str, values: object) -> None:
            array = np.asarray(values, dtype=float)
            finite = array[np.isfinite(array)]
            if finite.size == 0:
                return
            descriptors[f"{name}_mean"] = float(np.mean(finite))
            descriptors[f"{name}_std"] = float(np.std(finite))

        onset_envelope = librosa.onset.onset_strength(y=y, sr=sr)
        tempo = librosa.feature.tempo(y=y, sr=sr, onset_envelope=onset_envelope)
        add_scalar("tempo_bpm", tempo)
        add_stats("onset_strength", onset_envelope)
        add_stats("rms", librosa.feature.rms(y=y))
        add_stats("spectral_centroid", librosa.feature.spectral_centroid(y=y, sr=sr))
        add_stats("spectral_bandwidth", librosa.feature.spectral_bandwidth(y=y, sr=sr))
        add_stats("spectral_rolloff", librosa.feature.spectral_rolloff(y=y, sr=sr))
        add_stats("spectral_flatness", librosa.feature.spectral_flatness(y=y))
        add_stats("zero_crossing_rate", librosa.feature.zero_crossing_rate(y))

        contrast = librosa.feature.spectral_contrast(y=y, sr=sr)
        for index, row in enumerate(contrast, start=1):
            add_stats(f"spectral_contrast_{index:02d}", row)

        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=12)
        for index, row in enumerate(mfcc, start=1):
            add_stats(f"mfcc_{index:02d}", row)

        chroma = librosa.feature.chroma_cens(y=y, sr=sr)
        chroma_means = np.mean(chroma, axis=1)
        for index, value in enumerate(chroma_means):
            add_scalar(f"chroma_{index:02d}_mean", value)
        add_scalar("chroma_peak", int(np.argmax(chroma_means)))
        add_scalar("chroma_peak_strength", float(np.max(chroma_means)))
        chroma_total = float(np.sum(chroma_means))
        if chroma_total > 1e-12:
            add_scalar(
                "chroma_tonal_confidence",
                float(np.max(chroma_means)) / chroma_total,
            )

        if self.semantic_embedder is None:
            descriptors["semantic_status"] = (
                "unavailable" if self.semantic_unavailable_reason else "disabled"
            )
            if self.semantic_unavailable_reason:
                descriptors["semantic_failure_code"] = self.semantic_unavailable_reason
        else:
            for attempt in range(1, MAX_SEMANTIC_ANALYSIS_ATTEMPTS + 1):
                try:
                    semantic_result = self.semantic_embedder.embed(audio_path)
                except Exception as exc:  # noqa: BLE001 - semantic failure degrades safely
                    descriptors["semantic_status"] = "failed"
                    descriptors["semantic_failure_code"] = type(exc).__name__
                    descriptors["semantic_attempt_count"] = attempt
                else:
                    descriptors.update(semantic_cache_payload(semantic_result))
                    descriptors["semantic_attempt_count"] = attempt
                    break

        vector_keys = vector_descriptor_keys()
        vector = [descriptors.get(key, 0.0) for key in vector_keys]

        return SonicAnalysisResult(
            analyzer_key=self.analyzer_key,
            analyzer_version=self.analyzer_version,
            descriptors=descriptors,
            vector=vector,
        )


def build_sonic_analyzer(
    analyzer_key: str = SONIC_ANALYZER_LIBROSA_V1,
) -> SonicAnalyzer:
    if analyzer_key == SONIC_ANALYZER_LIBROSA_V1:
        try:
            semantic_embedder = build_semantic_embedder_from_environment()
        except Exception as exc:  # noqa: BLE001 - configuration failure is evidence
            return LibrosaSonicAnalyzer(
                semantic_unavailable_reason=type(exc).__name__,
            )
        return LibrosaSonicAnalyzer(semantic_embedder=semantic_embedder)

    raise ValueError(f"Unsupported sonic analyzer: {analyzer_key}")


def vector_descriptor_keys() -> list[str]:
    scalar_keys = [
        "tempo_bpm",
        "onset_strength_mean",
        "onset_strength_std",
        "rms_mean",
        "rms_std",
        "spectral_centroid_mean",
        "spectral_centroid_std",
        "spectral_bandwidth_mean",
        "spectral_rolloff_mean",
        "spectral_flatness_mean",
        "zero_crossing_rate_mean",
    ]
    contrast_keys = [f"spectral_contrast_{index:02d}_mean" for index in range(1, 8)]
    mfcc_keys = [f"mfcc_{index:02d}_mean" for index in range(1, 13)]
    chroma_keys = [f"chroma_{index:02d}_mean" for index in range(12)]
    return [*scalar_keys, *contrast_keys, *mfcc_keys, *chroma_keys]
