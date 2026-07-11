from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from urllib.parse import urlparse

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


def load_slskd_config(environ: Mapping[str, str] | None = None) -> SlskdConfig:
    env = os.environ if environ is None else environ
    base_url = _required_env("SLSKD_BASE_URL", env)
    api_key = _required_env("SLSKD_API_KEY", env)
    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise SoulseekConfigurationError(
            "SLSKD_BASE_URL must be an absolute http:// or https:// URL"
        )

    search_poll_timeout_seconds = _float_env(
        "SLSKD_SEARCH_POLL_TIMEOUT_SECONDS",
        30.0,
        env,
        minimum=0.1,
        maximum=3600.0,
    )
    search_poll_interval_seconds = _float_env(
        "SLSKD_SEARCH_POLL_INTERVAL_SECONDS",
        2.0,
        env,
        minimum=0.05,
        maximum=300.0,
    )
    if search_poll_interval_seconds > search_poll_timeout_seconds:
        raise SoulseekConfigurationError(
            "SLSKD_SEARCH_POLL_INTERVAL_SECONDS must not exceed "
            "SLSKD_SEARCH_POLL_TIMEOUT_SECONDS"
        )

    return SlskdConfig(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        verify_ssl=_bool_env("SLSKD_VERIFY_SSL", default=True, environ=env),
        request_timeout_seconds=_float_env(
            "SLSKD_REQUEST_TIMEOUT_SECONDS",
            10.0,
            env,
            minimum=0.1,
            maximum=120.0,
        ),
        search_timeout_seconds=_int_env(
            "SLSKD_SEARCH_TIMEOUT_SECONDS",
            SOULSEEK_SEARCH_TIMEOUT_SECONDS,
            env,
            minimum=1,
            maximum=3600,
        ),
        search_poll_timeout_seconds=search_poll_timeout_seconds,
        search_poll_interval_seconds=search_poll_interval_seconds,
        response_limit=_int_env(
            "SLSKD_RESPONSE_LIMIT", 100, env, minimum=1, maximum=10_000
        ),
        file_limit=_int_env(
            "SLSKD_FILE_LIMIT", 10_000, env, minimum=1, maximum=1_000_000
        ),
        maximum_peer_queue_length=_int_env(
            "SLSKD_MAXIMUM_PEER_QUEUE_LENGTH",
            1_000_000,
            env,
            minimum=0,
            maximum=10_000_000,
        ),
        minimum_peer_upload_speed=_int_env(
            "SLSKD_MINIMUM_PEER_UPLOAD_SPEED",
            0,
            env,
            minimum=0,
            maximum=1_000_000_000,
        ),
    )


def is_slskd_configured(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return bool(
        env.get("SLSKD_BASE_URL", "").strip() and env.get("SLSKD_API_KEY", "").strip()
    )


def _required_env(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if value is None or value.strip() == "":
        raise SoulseekConfigurationError(f"{name} must be configured for Soulseek")
    return value.strip()


def _bool_env(name: str, *, default: bool, environ: Mapping[str, str]) -> bool:
    value = environ.get(name)
    if value is None:
        return default

    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SoulseekConfigurationError(
        f"{name} must be one of true/false, yes/no, on/off, or 1/0"
    )


def _int_env(
    name: str,
    default: int,
    environ: Mapping[str, str],
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default

    try:
        parsed = int(value)
    except ValueError as exc:
        raise SoulseekConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise SoulseekConfigurationError(
            f"{name} must be between {minimum} and {maximum}; got {parsed}"
        )
    return parsed


def _float_env(
    name: str,
    default: float,
    environ: Mapping[str, str],
    *,
    minimum: float,
    maximum: float,
) -> float:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default

    try:
        parsed = float(value)
    except ValueError as exc:
        raise SoulseekConfigurationError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise SoulseekConfigurationError(
            f"{name} must be between {minimum:g} and {maximum:g}; got {parsed:g}"
        )
    return parsed
