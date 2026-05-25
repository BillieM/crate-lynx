from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.sonic.analyzer import vector_descriptor_keys
from app.sonic.models import SONIC_ANALYZER_LIBROSA_V1


SONIC_FEATURE_PROFILE_BALANCED_V1 = "balanced_v1"
SONIC_FEATURE_PROFILE_ENERGY_V1 = "energy_v1"
SONIC_FEATURE_PROFILE_TEXTURE_V1 = "texture_v1"
SONIC_FEATURE_PROFILE_HARMONY_V1 = "harmony_v1"
DEFAULT_SONIC_FEATURE_PROFILE = SONIC_FEATURE_PROFILE_BALANCED_V1

SONIC_FEATURE_PROFILE_KEYS = (
    SONIC_FEATURE_PROFILE_BALANCED_V1,
    SONIC_FEATURE_PROFILE_ENERGY_V1,
    SONIC_FEATURE_PROFILE_TEXTURE_V1,
    SONIC_FEATURE_PROFILE_HARMONY_V1,
)


@dataclass(frozen=True, slots=True)
class SonicFeatureProfile:
    key: str
    analyzer_key: str
    analyzer_version: str
    descriptor_weights: dict[str, float]

    @property
    def vector_keys(self) -> list[str]:
        return list(self.descriptor_weights.keys())

    def to_config(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "analyzer_key": self.analyzer_key,
            "analyzer_version": self.analyzer_version,
            "descriptor_weights": dict(self.descriptor_weights),
            "vector_keys": self.vector_keys,
        }


def resolve_feature_profile(profile_key: str | None) -> SonicFeatureProfile:
    key = str(profile_key or DEFAULT_SONIC_FEATURE_PROFILE).strip()
    return _PROFILE_BUILDERS.get(key, _balanced_profile)()


def resolve_feature_profile_from_config(config: dict[str, Any]) -> SonicFeatureProfile:
    resolved = config.get("resolved_feature_profile")
    if isinstance(resolved, dict):
        weights = resolved.get("descriptor_weights")
        analyzer_key = str(resolved.get("analyzer_key") or SONIC_ANALYZER_LIBROSA_V1)
        analyzer_version = str(resolved.get("analyzer_version") or "1")
        key = str(
            resolved.get("key")
            or config.get("feature_profile")
            or DEFAULT_SONIC_FEATURE_PROFILE
        )
        if isinstance(weights, dict):
            normalized_weights = {
                str(weight_key): float(weight_value)
                for weight_key, weight_value in weights.items()
                if _positive_number(weight_value)
            }
            if normalized_weights:
                return SonicFeatureProfile(
                    analyzer_key=analyzer_key,
                    analyzer_version=analyzer_version,
                    descriptor_weights=normalized_weights,
                    key=key,
                )

    return resolve_feature_profile(str(config.get("feature_profile", "")))


def resolved_feature_profile_config(profile_key: str | None) -> dict[str, Any]:
    return resolve_feature_profile(profile_key).to_config()


def _balanced_profile() -> SonicFeatureProfile:
    return SonicFeatureProfile(
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="1",
        descriptor_weights={key: 1.0 for key in vector_descriptor_keys()},
        key=SONIC_FEATURE_PROFILE_BALANCED_V1,
    )


def _energy_profile() -> SonicFeatureProfile:
    weights = _base_weight_map(0.25)
    weights.update(
        {
            "tempo_bpm": 2.0,
            "onset_strength_mean": 2.0,
            "onset_strength_std": 1.2,
            "rms_mean": 1.8,
            "rms_std": 1.0,
            "zero_crossing_rate_mean": 0.9,
            "spectral_rolloff_mean": 0.75,
        }
    )
    return SonicFeatureProfile(
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="1",
        descriptor_weights=weights,
        key=SONIC_FEATURE_PROFILE_ENERGY_V1,
    )


def _texture_profile() -> SonicFeatureProfile:
    weights = _base_weight_map(0.2)
    weights.update(
        {
            "spectral_centroid_mean": 1.8,
            "spectral_centroid_std": 1.2,
            "spectral_bandwidth_mean": 1.4,
            "spectral_rolloff_mean": 1.5,
            "spectral_flatness_mean": 1.8,
            "zero_crossing_rate_mean": 1.2,
        }
    )
    for index in range(1, 8):
        weights[f"spectral_contrast_{index:02d}_mean"] = 1.3
    return SonicFeatureProfile(
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="1",
        descriptor_weights=weights,
        key=SONIC_FEATURE_PROFILE_TEXTURE_V1,
    )


def _harmony_profile() -> SonicFeatureProfile:
    weights = _base_weight_map(0.15)
    for index in range(12):
        weights[f"chroma_{index:02d}_mean"] = 1.8
    for index in range(1, 13):
        weights[f"mfcc_{index:02d}_mean"] = 0.9
    return SonicFeatureProfile(
        analyzer_key=SONIC_ANALYZER_LIBROSA_V1,
        analyzer_version="1",
        descriptor_weights=weights,
        key=SONIC_FEATURE_PROFILE_HARMONY_V1,
    )


def _base_weight_map(default_weight: float) -> dict[str, float]:
    return {key: default_weight for key in vector_descriptor_keys()}


def _positive_number(value: object) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


_PROFILE_BUILDERS = {
    SONIC_FEATURE_PROFILE_BALANCED_V1: _balanced_profile,
    SONIC_FEATURE_PROFILE_ENERGY_V1: _energy_profile,
    SONIC_FEATURE_PROFILE_TEXTURE_V1: _texture_profile,
    SONIC_FEATURE_PROFILE_HARMONY_V1: _harmony_profile,
}
