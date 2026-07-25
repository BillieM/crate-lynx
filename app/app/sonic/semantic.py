from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

CLAP_ONNX_MODEL_ID = "Xenova/clap-htsat-unfused"
CLAP_ONNX_MODEL_REVISION = "7fe18129b081a8cd2a0aba45e858b5b114c03a6b"
CLAP_ONNX_MODEL_FILENAME = "audio_model.onnx"
CLAP_ONNX_MODEL_SIZE = 117_528_416
CLAP_ONNX_MODEL_SHA256 = (
    "a1c2b43c44f71e0fa841a4b86700886c199bf87699ea45632c4d831bc6c88957"
)
CLAP_ONNX_EMBEDDING_DIMENSION = 512
CLAP_SAMPLE_RATE = 48_000
CLAP_WINDOW_SECONDS = 10
CLAP_WINDOW_FRACTIONS = (0.15, 0.5, 0.85)


@dataclass(frozen=True, slots=True)
class SemanticEmbeddingResult:
    embedding: list[float]
    model_key: str
    model_revision: str
    window_count: int


class SemanticAudioEmbedder(Protocol):
    model_key: str
    model_revision: str

    def embed(self, audio_path: Path | str) -> SemanticEmbeddingResult: ...


@dataclass(slots=True)
class ClapOnnxSemanticEmbedder:
    """Offline-only CLAP audio embedding with a verified, pinned ONNX asset."""

    model_path: Path
    model_key: str = "clap_onnx_v1"
    model_revision: str = CLAP_ONNX_MODEL_REVISION

    def __post_init__(self) -> None:
        self.model_path = Path(self.model_path)

    def embed(self, audio_path: Path | str) -> SemanticEmbeddingResult:
        try:
            import librosa
            import numpy as np
        except ImportError as exc:
            raise RuntimeError(
                "CLAP semantic analysis requires librosa and numpy"
            ) from exc

        waveform, _ = librosa.load(
            Path(audio_path),
            sr=CLAP_SAMPLE_RATE,
            mono=True,
            duration=300,
        )
        if waveform.size == 0:
            raise ValueError("Audio file did not contain samples for semantic analysis")

        windows = deterministic_audio_windows(
            waveform,
            sample_rate=CLAP_SAMPLE_RATE,
            window_seconds=CLAP_WINDOW_SECONDS,
        )
        session = _load_clap_runtime(str(self.model_path))
        embeddings = []
        for window in windows:
            inputs = _clap_onnx_inputs(window)
            session_inputs = {
                input_meta.name: inputs[input_meta.name]
                for input_meta in session.get_inputs()
                if input_meta.name in inputs
            }
            if not session_inputs:
                raise RuntimeError("CLAP ONNX inputs did not match feature extractor")
            outputs = session.run(None, session_inputs)
            embedding = _find_embedding_output(outputs)
            embeddings.append(embedding)

        averaged = np.mean(np.asarray(embeddings, dtype=np.float32), axis=0)
        norm = float(np.linalg.norm(averaged))
        if not np.isfinite(norm) or norm <= 1e-12:
            raise RuntimeError("CLAP produced a non-finite or empty embedding")
        normalized = averaged / norm
        return SemanticEmbeddingResult(
            embedding=[float(value) for value in normalized],
            model_key=self.model_key,
            model_revision=self.model_revision,
            window_count=len(windows),
        )


def build_semantic_embedder_from_environment() -> SemanticAudioEmbedder | None:
    enabled = os.environ.get("SONIC_SEMANTIC_ENABLED", "").strip().casefold()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    model_path = os.environ.get(
        "SONIC_SEMANTIC_MODEL_PATH",
        "/data/models/clap-htsat-unfused-audio.onnx",
    ).strip()
    if not model_path:
        raise RuntimeError(
            "SONIC_SEMANTIC_MODEL_PATH is required when semantic analysis is enabled"
        )
    return ClapOnnxSemanticEmbedder(Path(model_path))


def verify_model_asset(model_path: Path) -> None:
    if not model_path.is_file():
        raise FileNotFoundError(f"CLAP ONNX model asset not found: {model_path}")
    size = model_path.stat().st_size
    if size != CLAP_ONNX_MODEL_SIZE:
        raise RuntimeError(
            f"CLAP ONNX model size mismatch: expected {CLAP_ONNX_MODEL_SIZE}, got {size}"
        )
    digest = hashlib.sha256()
    with model_path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != CLAP_ONNX_MODEL_SHA256:
        raise RuntimeError(
            "CLAP ONNX model checksum mismatch: "
            f"expected {CLAP_ONNX_MODEL_SHA256}, got {actual_sha256}"
        )


@lru_cache(maxsize=2)
def _load_clap_runtime(model_path: str):
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("CLAP semantic analysis requires onnxruntime") from exc
    verified_path = Path(model_path)
    verify_model_asset(verified_path)
    session = ort.InferenceSession(
        str(verified_path),
        providers=["CPUExecutionProvider"],
    )
    return session


def _clap_onnx_inputs(window) -> dict[str, object]:
    """Mirror CLAP's exact-length rand_trunc preprocessing without PyTorch."""
    import librosa
    import numpy as np

    waveform = np.asarray(window, dtype=np.float32).reshape(-1)
    expected_samples = CLAP_SAMPLE_RATE * CLAP_WINDOW_SECONDS
    if waveform.size != expected_samples:
        raise ValueError(
            f"CLAP preprocessing requires {expected_samples} samples, "
            f"got {waveform.size}"
        )
    mel = librosa.feature.melspectrogram(
        y=waveform,
        sr=CLAP_SAMPLE_RATE,
        n_fft=1024,
        hop_length=480,
        win_length=1024,
        window="hann",
        center=True,
        pad_mode="reflect",
        power=2.0,
        n_mels=64,
        fmin=50,
        fmax=14_000,
        htk=False,
        norm="slaney",
    )
    log_mel = librosa.power_to_db(
        mel,
        ref=1.0,
        amin=1e-10,
        top_db=None,
    ).T
    return {
        "input_features": log_mel[np.newaxis, np.newaxis, :, :].astype(
            np.float32,
            copy=False,
        ),
        "is_longer": np.asarray([[False]], dtype=np.bool_),
    }


def deterministic_audio_windows(
    waveform,
    *,
    sample_rate: int,
    window_seconds: int,
):
    import numpy as np

    window_samples = sample_rate * window_seconds
    values = np.asarray(waveform, dtype=np.float32).reshape(-1)
    if values.size <= window_samples:
        if values.size == 0:
            return [np.zeros(window_samples, dtype=np.float32)]
        repeats = (window_samples + values.size - 1) // values.size
        return [np.tile(values, repeats)[:window_samples]]

    max_start = values.size - window_samples
    starts = sorted(
        {
            max(0, min(max_start, round(max_start * fraction)))
            for fraction in CLAP_WINDOW_FRACTIONS
        }
    )
    return [values[start : start + window_samples] for start in starts]


def semantic_cache_payload(
    result: SemanticEmbeddingResult,
) -> dict[str, object]:
    return {
        "semantic_embedding": result.embedding,
        "semantic_model_key": result.model_key,
        "semantic_model_revision": result.model_revision,
        "semantic_status": "ready",
        "semantic_window_count": result.window_count,
    }


def _find_embedding_output(outputs) -> list[float]:
    import numpy as np

    for output in outputs:
        array = np.asarray(output)
        if array.size == CLAP_ONNX_EMBEDDING_DIMENSION:
            return [
                float(value) for value in array.reshape(CLAP_ONNX_EMBEDDING_DIMENSION)
            ]
    shapes = [tuple(np.asarray(output).shape) for output in outputs]
    raise RuntimeError(f"CLAP ONNX output did not contain a 512-D embedding: {shapes}")
