from __future__ import annotations

from dataclasses import dataclass
import os

from app.soulseek.models import SOULSEEK_SEARCH_TIMEOUT_SECONDS


class SoulseekConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SlskdConfig:
    base_url: str
    api_key: str
    verify_ssl: bool = True
    request_timeout_seconds: float = 10.0
    search_timeout_seconds: int = SOULSEEK_SEARCH_TIMEOUT_SECONDS
    search_poll_timeout_seconds: float = 30.0
    search_poll_interval_seconds: float = 2.0
    response_limit: int = 100
    file_limit: int = 10_000
    maximum_peer_queue_length: int = 1_000_000
    minimum_peer_upload_speed: int = 0


def load_slskd_config() -> SlskdConfig:
    base_url = _required_env("SLSKD_BASE_URL")
    api_key = _required_env("SLSKD_API_KEY")
    return SlskdConfig(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        verify_ssl=_bool_env("SLSKD_VERIFY_SSL", default=True),
        request_timeout_seconds=_float_env("SLSKD_REQUEST_TIMEOUT_SECONDS", 10.0),
        search_timeout_seconds=_int_env(
            "SLSKD_SEARCH_TIMEOUT_SECONDS",
            SOULSEEK_SEARCH_TIMEOUT_SECONDS,
        ),
        search_poll_timeout_seconds=_float_env(
            "SLSKD_SEARCH_POLL_TIMEOUT_SECONDS",
            30.0,
        ),
        search_poll_interval_seconds=_float_env(
            "SLSKD_SEARCH_POLL_INTERVAL_SECONDS",
            2.0,
        ),
        response_limit=_int_env("SLSKD_RESPONSE_LIMIT", 100),
        file_limit=_int_env("SLSKD_FILE_LIMIT", 10_000),
        maximum_peer_queue_length=_int_env(
            "SLSKD_MAXIMUM_PEER_QUEUE_LENGTH", 1_000_000
        ),
        minimum_peer_upload_speed=_int_env("SLSKD_MINIMUM_PEER_UPLOAD_SPEED", 0),
    )


def is_slskd_configured() -> bool:
    return bool(os.environ.get("SLSKD_BASE_URL") and os.environ.get("SLSKD_API_KEY"))


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise SoulseekConfigurationError(f"{name} must be configured for Soulseek")
    return value.strip()


def _bool_env(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.strip().casefold() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default

    try:
        return float(value)
    except ValueError:
        return default
