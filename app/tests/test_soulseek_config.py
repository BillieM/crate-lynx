from __future__ import annotations

import pytest

from app.soulseek.config import SoulseekConfigurationError, load_slskd_config


def test_load_slskd_config_reads_all_supported_numeric_settings() -> None:
    config = load_slskd_config(
        {
            "SLSKD_BASE_URL": "https://slskd.example/",
            "SLSKD_API_KEY": "secret",
            "SLSKD_VERIFY_SSL": "false",
            "SLSKD_REQUEST_TIMEOUT_SECONDS": "12.5",
            "SLSKD_SEARCH_TIMEOUT_SECONDS": "45",
            "SLSKD_SEARCH_POLL_TIMEOUT_SECONDS": "40",
            "SLSKD_SEARCH_POLL_INTERVAL_SECONDS": "1.5",
            "SLSKD_RESPONSE_LIMIT": "250",
            "SLSKD_FILE_LIMIT": "20000",
            "SLSKD_MAXIMUM_PEER_QUEUE_LENGTH": "500",
            "SLSKD_MINIMUM_PEER_UPLOAD_SPEED": "1000",
        }
    )

    assert config.base_url == "https://slskd.example"
    assert config.verify_ssl is False
    assert config.request_timeout_seconds == 12.5
    assert config.search_timeout_seconds == 45
    assert config.search_poll_timeout_seconds == 40
    assert config.search_poll_interval_seconds == 1.5
    assert config.response_limit == 250
    assert config.file_limit == 20_000
    assert config.maximum_peer_queue_length == 500
    assert config.minimum_peer_upload_speed == 1000


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("SLSKD_REQUEST_TIMEOUT_SECONDS", "never", "must be a number"),
        ("SLSKD_SEARCH_TIMEOUT_SECONDS", "0", "must be between 1 and 3600"),
        ("SLSKD_RESPONSE_LIMIT", "10001", "must be between 1 and 10000"),
        ("SLSKD_FILE_LIMIT", "-1", "must be between 1 and 1000000"),
        (
            "SLSKD_MAXIMUM_PEER_QUEUE_LENGTH",
            "10000001",
            "must be between 0 and 10000000",
        ),
        (
            "SLSKD_MINIMUM_PEER_UPLOAD_SPEED",
            "-1",
            "must be between 0 and 1000000000",
        ),
    ],
)
def test_load_slskd_config_rejects_invalid_numeric_settings(
    name: str,
    value: str,
    message: str,
) -> None:
    environ = {
        "SLSKD_BASE_URL": "http://slskd:5030",
        "SLSKD_API_KEY": "secret",
        name: value,
    }

    with pytest.raises(SoulseekConfigurationError, match=message):
        load_slskd_config(environ)


def test_load_slskd_config_rejects_poll_interval_above_timeout() -> None:
    with pytest.raises(SoulseekConfigurationError, match="must not exceed"):
        load_slskd_config(
            {
                "SLSKD_BASE_URL": "http://slskd:5030",
                "SLSKD_API_KEY": "secret",
                "SLSKD_SEARCH_POLL_TIMEOUT_SECONDS": "1",
                "SLSKD_SEARCH_POLL_INTERVAL_SECONDS": "2",
            }
        )
